"""5d. 相場の深掘り分析(学習アプリ「相場の見立て」用、2026-11追加)

なぜ株価が上がった・下がったのかを、セクター・金利・商品・世界の市場・ニュースから分析し、
learn/data/analysis.json に書き出す。毎朝のBotがSlackへの投稿の後に動かす(失敗しても配信は止めない)。

流れ
  1. Yahoo Finance から米国12セクター・日本17業種(TOPIX-17のETF)・世界の指数・金利・商品・信用を取得
  2. 各銘柄の騰落を「ふだんの値動きの何倍か(z値)」にそろえ、資金の流れ(景気敏感とディフェンシブ等)を計算
  3. 規則にもとづく主因の候補を作る(AIが使えない日もこれは出る)
  4. Geminiで役割の違うアナリストを順に重ねる
       マクロ・金利 → セクター・資金の流れ → 世界情勢・ニュース → 弱気筋(バーリ・空売り筋) → 強気筋
       → チーフアナリストの統合 → 査読(データとの矛盾を探す) → 指摘があれば統合をやり直す
  5. AIの文章の数字をデータと照合し、確かめられない数字を含む文は捨てる(AIを信用せず、毎回プログラムで確かめる)
  6. 過去の見立てを履歴に残し、その後の値動きで答え合わせできるようにする
"""
import json
import math
import re
import sys
import time
from datetime import datetime

ANALYSIS_PATH = "learn/data/analysis.json"
HISTORY_DAYS = 90          # 答え合わせ用に残す見立ての日数
DEEP_BUDGET = 600          # 深掘り分析でGeminiに使う時間の合計の上限(秒)。投稿の後に動くので要約の時間とは別に数える
CHIEF_RESERVE = 200        # チーフの統合と査読のために残しておく時間(秒)。足りなくなりそうなら残りの役割を飛ばす
REVIEW_MIN = 100           # 査読と改訂を始める時に残っているべき時間(秒)
DEEP_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]   # 推論が深い方を先に試す
MIN_US = 8                 # 米国セクターがこれより少なく取れた日は分析しない

# ---------- 対象 ----------
US_SECTORS = [
    ("XLK", "テクノロジー"), ("SMH", "半導体"), ("XLC", "通信サービス"), ("XLY", "一般消費財"),
    ("XLF", "金融"), ("XLI", "資本財"), ("XLE", "エネルギー"), ("XLB", "素材"),
    ("XLV", "ヘルスケア"), ("XLP", "生活必需品"), ("XLU", "公益"), ("XLRE", "不動産"),
]
# TOPIX-17業種のETF(NEXT FUNDS)。売買が少ない日は指数とずれることがある
JP_SECTORS = [
    ("1617.T", "食品"), ("1618.T", "エネルギー資源"), ("1619.T", "建設・資材"), ("1620.T", "素材・化学"),
    ("1621.T", "医薬品"), ("1622.T", "自動車・輸送機"), ("1623.T", "鉄鋼・非鉄"), ("1624.T", "機械"),
    ("1625.T", "電機・精密"), ("1626.T", "情報通信・サービス"), ("1627.T", "電力・ガス"), ("1628.T", "運輸・物流"),
    ("1629.T", "商社・卸売"), ("1630.T", "小売"), ("1631.T", "銀行"), ("1632.T", "金融(除く銀行)"),
    ("1633.T", "不動産"),
]
STYLE = [("SPY", "S&P 500"), ("RSP", "S&P 500 均等加重"), ("IWM", "米小型株(ラッセル2000)"),
         ("HYG", "ハイイールド債"), ("TLT", "米長期国債")]
CROSS = [("^TNX", "米10年債利回り", "yield"), ("^IRX", "米3か月債利回り", "yield"), ("^VIX", "VIX(恐怖指数)", "level"),
         ("CL=F", "WTI原油", "px"), ("GC=F", "金", "px"), ("HG=F", "銅", "px"), ("DX-Y.NYB", "ドル指数", "px"),
         ("JPY=X", "ドル円", "px"), ("BTC-USD", "ビットコイン", "px")]
CHECK = [("^GSPC", "S&P 500指数")]   # 照合用(SPYの騰落が正しいかを確かめる)
GLOBAL = [("^N225", "日経平均"), ("1306.T", "TOPIX(ETF)"), ("^STOXX50E", "ユーロ・ストックス50"),
          ("^GDAXI", "ドイツDAX"), ("^HSI", "香港ハンセン"), ("000001.SS", "上海総合"), ("^KS11", "韓国KOSPI")]

# 資金の流れ(買われた側 − 売られた側)。(id, 名前, 買い側, 売り側, 何を意味するか)
SIGNALS = [
    ("cyc_def", "景気敏感 − ディフェンシブ", ["XLY", "XLI", "XLF", "XLB"], ["XLP", "XLU", "XLV"],
     "プラスは景気に強気(リスクを取る)、マイナスは守りに入っている"),
    ("semi", "半導体 − S&P 500", ["SMH"], ["SPY"], "AI・半導体が相場を引っ張っているか、足を引っ張っているか"),
    ("breadth", "均等加重 − 時価総額加重", ["RSP"], ["SPY"], "プラスは上昇が幅広い銘柄に広がっている、マイナスは一部の大型株頼み"),
    ("small", "小型株 − 大型株", ["IWM"], ["SPY"], "小型株は金利と国内景気に敏感。プラスは利下げ期待や景気回復期待"),
    ("rate_sens", "金利敏感株 − S&P 500", ["XLRE", "XLU"], ["SPY"], "不動産・公益は金利が下がると買われ、上がると売られやすい"),
    ("credit", "ハイイールド債 − 米長期国債", ["HYG"], ["TLT"], "マイナスは信用不安(低格付けの社債が売られ、国債に逃げる)"),
    ("cu_au", "銅 − 金", ["HG=F"], ["GC=F"], "銅は景気、金は不安の指標。プラスは景気期待、マイナスは警戒"),
    ("jp_ext", "日本: 外需株 − 内需株", ["1622.T", "1625.T", "1624.T"], ["1630.T", "1627.T", "1617.T"],
     "プラスは円安や世界景気への期待で輸出株が買われている"),
    ("jp_bank", "日本: 銀行 − TOPIX", ["1631.T"], ["1306.T"], "銀行は国内金利の上昇で買われやすい。金利観測の手がかり"),
    ("jp_n225", "日経平均 − TOPIX", ["^N225"], ["1306.T"], "プラスは値がさの半導体・ハイテク株が主導、マイナスは幅広い銘柄が主導"),
]


def _eb():
    """econobot本体(直接実行の時は __main__)。循環importを避けるため、使う時に取り出す"""
    m = sys.modules.get("econobot")
    if m is None or not hasattr(m, "_call_gemini"):
        m = sys.modules.get("__main__")
    if m is None or not hasattr(m, "_call_gemini"):
        import econobot as m  # noqa: F811
    return m


# ---------- 1. 取得(正確さの確認つき) ----------
# 正確さのための決まり(2026-11-26 実データで確認した問題への対策)
#  - ETFは配当落ちの日に価格が下がる → 騰落は配当を調整した値(adjclose)で計算し、表示する水準は実際の終値
#  - Yahooの株式分割の調整が一部の日だけ二重にかかる(1306.T・1629.Tの2026-03-30〜31) → 前後の日の中央値から
#    半分未満・2倍超に外れた値は誤りとして捨てる
#  - 原油・金・銅・ドル指数は夕方18時(米東部)から翌日の取引が始まり、取引中の値が前日の終値の欄を上書きする
#    → 取引時間の始まりで日付を付け(6時間ずらす)、米国株の最新の取引日より後の取引(途中の値)は使わない
#  - ドル円は米東部17時の値(本体の _yahoo_fx_rows)、ビットコインはUTCの日足
#  - 米国はNYSEの休日を入れた「その日あるべき最新の取引日」と照らし、遅れた銘柄は時間をおいて取り直す
RT_SYMS = {"CL=F", "GC=F", "HG=F", "DX-Y.NYB"}   # ほぼ24時間取引(取引の日付は前日の夕方から始まる)
FX_SYMS = {"JPY=X"}
CRYPTO_SYMS = {"BTC-USD"}
RETRY_WAITS = (60, 120, 240)   # 遅れ・失敗の銘柄を取り直すまでの待ち(秒)。合計約7分
BACKUP_WAITS = (60, 120)       # 予備の起動(8:10)での取り直しの待ち
SPIKE_LO, SPIKE_HI = 0.5, 2.0  # 前後の中央値に対してこの範囲の外の値はデータの誤り


def all_symbols():
    out = [(s, n, "us") for s, n in US_SECTORS] + [(s, n, "jp") for s, n in JP_SECTORS]
    out += [(s, n, "style") for s, n in STYLE] + [(s, n, "cross") for s, n, _ in CROSS] + [(s, n, "global") for s, n in GLOBAL]
    out += [(s, n, "check") for s, n in CHECK]
    out += [(s, n, "heavy_us") for s, n in HEAVY_US] + [(s, n, "heavy_jp") for s, n in HEAVY_JP]
    return out


def region(sym):
    """どの市場の取引日に合わせるか"""
    if sym.endswith(".T") or sym == "^N225":
        return "jp"
    if sym in ("^HSI", "000001.SS", "^KS11"):
        return "asia"
    if sym in ("^STOXX50E", "^GDAXI"):
        return "eu"
    return "us"


# --- NYSEの休日(取引所の規則。早帰りの日は終値があるので休日に入れない) ---
def _nth_weekday(y, m, wd, n):
    from datetime import date, timedelta
    d = date(y, m, 1)
    d += timedelta(days=(wd - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y, m, wd):
    from datetime import date, timedelta
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() - wd) % 7)


def _easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    from datetime import date
    return date(y, (h + l_ - 7 * m + 114) // 31, ((h + l_ - 7 * m + 114) % 31) + 1)


def nyse_holidays(y):
    from datetime import date, timedelta

    def obs(d):   # 土曜は前の金曜、日曜は次の月曜に休む(元日が土曜の時は前年12/31を休まない)
        return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d
    hs = {obs(date(y, 1, 1)), _nth_weekday(y, 1, 0, 3), _nth_weekday(y, 2, 0, 3), _easter(y) - timedelta(days=2),
          _last_weekday(y, 5, 0), obs(date(y, 7, 4)), _nth_weekday(y, 9, 0, 1), _nth_weekday(y, 11, 3, 4), obs(date(y, 12, 25))}
    if y >= 2022:
        hs.add(obs(date(y, 6, 19)))
    return {d for d in hs if d.year == y}


def us_trading_day(d):
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def expected_us_date(now_utc):
    """今の時刻で、終値が出ているはずの米国の最新の取引日(引けの30分後から当日を数える)"""
    from datetime import timedelta
    et = _eb()._to_et(now_utc)
    d = et.date()
    if not (us_trading_day(d) and (et.hour, et.minute) >= (16, 30)):
        d -= timedelta(days=1)
        while not us_trading_day(d):
            d -= timedelta(days=1)
    return d.isoformat()


def _drop_spikes(rows):
    """前後3日ずつの中央値から大きく外れた値(分割の調整の誤りなど)を捨てる"""
    out = []
    for i, (d, v) in enumerate(rows):
        nb = [x for _, x in rows[max(0, i - 3):i] + rows[i + 1:i + 4] if x > 0]
        if nb and v > 0:
            med = sorted(nb)[len(nb) // 2]
            if not (SPIKE_LO <= v / med <= SPIKE_HI):
                continue
        out.append((d, v))
    return out


def parse_chart(res, sym, now=None):
    """Yahoo chart API の結果から、(騰落の計算に使う値, 表示する実際の終値) をそれぞれ [(日付, 値)] で返す"""
    from datetime import datetime, timezone, timedelta
    now = now or datetime.now(timezone.utc)
    meta = res.get("meta") or {}
    off = meta.get("gmtoffset") or 0
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    close = ((ind.get("quote") or [{}])[0]).get("close") or []
    adj = ((ind.get("adjclose") or [{}])[0]).get("adjclose") or close
    shift = 6 * 3600 if sym in RT_SYMS else 0
    by_c, by_a = {}, {}
    for t, c, a in zip(ts, close, adj):
        if not isinstance(c, (int, float)) or isinstance(c, bool):
            continue
        if sym in CRYPTO_SYMS:
            day = datetime.fromtimestamp(t, timezone.utc).date()
        else:
            day = datetime.fromtimestamp(t + off + shift, timezone.utc).date()
        by_c[day.isoformat()] = float(c)
        by_a[day.isoformat()] = float(a) if isinstance(a, (int, float)) and not isinstance(a, bool) else float(c)
    days = sorted(by_c)
    # 取引中の足(指数・株・ETF)は終値ではないので使わない
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    if days and sym not in RT_SYMS | CRYPTO_SYMS | FX_SYMS and reg.get("start") and reg.get("end"):
        n = now.timestamp()
        if reg["start"] <= n < reg["end"] + 1200 and datetime.fromtimestamp(reg["start"] + off, timezone.utc).date().isoformat() == days[-1]:
            days = days[:-1]
    if sym in CRYPTO_SYMS and days and days[-1] >= now.date().isoformat():
        days = days[:-1]   # UTCの今日の足は途中
    ret = _drop_spikes([(d, by_a[d]) for d in days])
    ok = {d for d, _ in ret}
    return ret, [(d, by_c[d]) for d in days if d in ok]


def _get_chart(sym, host):
    import urllib.parse
    import urllib.request
    url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
           "?range=1y&interval=1d&events=div%7Csplit")
    req = urllib.request.Request(url, headers={"User-Agent": _eb()._UA})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode())["chart"]["result"][0]


def us_close_rows(res, hour=16):
    """1時間足から、米国の取引日ごとに米東部 hour 時直前の値を [(日付, 値)] で返す(ビットコイン用)"""
    from datetime import datetime, timezone
    ts = res.get("timestamp") or []
    closes = (((res.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    out = {}
    for t, c in zip(ts, closes):
        if not isinstance(c, (int, float)) or isinstance(c, bool):
            continue
        et = _eb()._to_et(datetime.fromtimestamp(t, timezone.utc))
        if us_trading_day(et.date()) and 9 <= et.hour < hour:
            out[et.date().isoformat()] = float(c)   # 時刻の順に上書きされ、引け直前の足が残る
    return sorted(out.items())


def _get_hourly(sym, host):
    import urllib.parse
    import urllib.request
    url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1mo&interval=60m"
    req = urllib.request.Request(url, headers={"User-Agent": _eb()._UA})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode())["chart"]["result"][0]


def fetch_one(sym, now=None):
    """1銘柄を取得。query1 → query2 の順に試す。戻り値 (騰落用の行, 終値の行)"""
    if sym in FX_SYMS:
        rows, _ok = _eb()._yahoo_fx_rows(sym, now=now)   # 米東部17時の値(本体と同じ)
        return rows, rows
    if sym in CRYPTO_SYMS:
        # 日足は日が抜けることがある(2026-11-25が無かった)。直近1か月は米国株の引け(米東部16時)の値で置き換える
        daily, _ = parse_chart(_get_chart(sym, "query1"), sym, now)
        recent = []
        for host in ("query1", "query2"):
            try:
                recent = us_close_rows(_get_hourly(sym, host))
                break
            except Exception as e:
                print(f"    [Yahoo {sym} 1時間足 {host}] 取得失敗 {type(e).__name__}")
        if recent:
            rows = [r for r in daily if r[0] < recent[0][0]] + recent
            return rows, rows
        return daily, daily
    err = None
    for host in ("query1", "query2"):
        try:
            return parse_chart(_get_chart(sym, host), sym, now)
        except Exception as e:  # 次の取得元へ
            err = e
    raise err


def fetch_all(fetch=None, now=None, sleep=time.sleep, waits=None, fetch_movers_fn=None):
    """全銘柄を取得し、各市場の最新の取引日と照らす。遅れ・失敗の銘柄は時間をおいて取り直す。
    戻り値 {"rows": {記号: 騰落用の行}, "close": {記号: 終値の行}, "quality": {...}}"""
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    waits = RETRY_WAITS if waits is None else waits
    if fetch is None:
        fetch = lambda s: fetch_one(s, now)   # noqa: E731
        fetch_movers_fn = fetch_movers_fn or fetch_movers
    syms = [s for s, _, _ in all_symbols()]
    rows, close, fails = {}, {}, {}
    exp_us = expected_us_date(now)

    def expected(sym):
        reg = region(sym)
        if reg == "us":
            return exp_us
        mates = [rows[s][-1][0] for s in rows if region(s) == reg]
        return max(mates) if mates else None   # 同じ市場の銘柄でいちばん新しい日(祝日でもそろう)

    def get(todo):
        for s in todo:
            try:
                r, c = fetch(s)
            except Exception as e:  # 1銘柄の失敗で止めない
                fails[s] = f"{type(e).__name__}"
                continue
            if len(r) >= 70:
                rows[s], close[s] = r, c
                fails.pop(s, None)
            else:
                fails[s] = f"データが少ない({len(r)}日)"

    def late():
        return [s for s in syms if s not in rows or (expected(s) and rows[s][-1][0] < expected(s))]
    get(syms)
    for w in waits:
        todo = late()
        if not todo:
            break
        print(f"  深掘り用: 遅れ・失敗 {len(todo)}銘柄({', '.join(todo[:8])}…)→ {w}秒後に取り直す")
        sleep(w)
        get(todo)
    # 米国株の最新の取引日より後の値(原油などの翌日の取引の途中の値、為替の当日分)は使わない
    for s in list(rows):
        if region(s) == "us":
            rows[s] = [x for x in rows[s] if x[0] <= exp_us]
            close[s] = [x for x in close[s] if x[0] <= exp_us]
    stale = {s: rows[s][-1][0] for s in rows if expected(s) and rows[s][-1][0] < expected(s)}
    movers, merr = [], []
    if fetch_movers_fn:
        try:
            movers, merr = fetch_movers_fn(exp_us)
        except Exception as e:  # 動的な銘柄が取れなくても、固定の銘柄で分析する
            merr = [f"{type(e).__name__}"]
    q = {"expected_us": exp_us, "expected_jp": expected("1306.T"), "movers": len(movers), "movers_errors": merr, "missing": sorted(set(syms) - set(rows)),
         "stale": stale, "fails": fails, "checks": cross_checks(rows, close)}
    q["complete"] = not q["missing"] and not stale and all(c["ok"] for c in q["checks"])
    print(f"  深掘り用: {len(rows)}/{len(syms)}銘柄 米国の取引日 {exp_us} 遅れ {len(stale)} 欠け {len(q['missing'])}"
          f" 照合 {'OK' if all(c['ok'] for c in q['checks']) else 'ずれあり'}")
    return {"rows": rows, "close": close, "quality": q, "movers": movers}


def cross_checks(rows, close):
    """別の値と照らして、取得した値が正しいかを確かめる(同じ日の騰落の差が小さいこと)"""
    out = []

    def day_chg(r, d):
        dd = dict(r)
        ks = [k for k, _ in r]
        if d not in dd or ks.index(d) == 0:
            return None
        p = dd[ks[ks.index(d) - 1]]
        return (dd[d] / p - 1) * 100 if p else None
    if "SPY" in rows and "^GSPC" in close:
        d = rows["SPY"][-1][0]
        a, b = day_chg(rows["SPY"], d), day_chg(close["^GSPC"], d)
        if a is not None and b is not None:
            out.append({"name": "S&P 500 ETF(SPY)とS&P 500指数", "date": d, "a": round(a, 2), "b": round(b, 2),
                        "ok": abs(a - b) <= 0.3})
    if "^TNX" in close:
        try:
            tr = dict(_eb().treasury_rows("10 Yr"))
            d = close["^TNX"][-1][0]
            if d in tr:
                a, b = close["^TNX"][-1][1], tr[d]
                out.append({"name": "米10年債利回り(Yahoo)と米国財務省", "date": d, "a": round(a, 3), "b": round(b, 3),
                            "ok": abs(a - b) <= 0.05})
        except Exception as e:  # 財務省が取れない日は照合を飛ばす
            print(f"    [照合 10年債] 財務省のCSVが取れない({type(e).__name__})")
    return out


# ---------- 2. 特徴量 ----------
YIELD_SYMS = {s for s, _, k in CROSS if k == "yield"}
LEVEL_SYMS = {s for s, _, k in CROSS if k == "level"}


def _daily(rows, sym):
    """[(日付, 1日の変化)]。利回りはbp(0.01%)、それ以外は%"""
    out = []
    for (d0, v0), (d1, v1) in zip(rows, rows[1:]):
        if sym in YIELD_SYMS:
            out.append((d1, (v1 - v0) * 100))
        elif v0:
            out.append((d1, (v1 / v0 - 1) * 100))
    return out


def _std(xs):
    if len(xs) < 10:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) or None


def _chg(rows, sym, h):
    if len(rows) <= h:
        return None
    v0, v1 = rows[-1 - h][1], rows[-1][1]
    if sym in YIELD_SYMS:
        return (v1 - v0) * 100
    return (v1 / v0 - 1) * 100 if v0 else None


def _sma(rows, n):
    if len(rows) < n:
        return None
    return sum(v for _, v in rows[-n:]) / n


def _r(x, nd=2):
    return None if x is None else round(x, nd)


def features(rows, close=None, stale=None):
    """記号ごとの特徴量。z = 変化 ÷ (ふだんの1日の値動き × √日数)。|z|が2を超えると、めったにない大きさ。
    騰落は配当を調整した値、水準(last)は実際の終値。遅れている銘柄は1日の値を出さない(古い日の動きを今日の動きと見せない)"""
    names = {s: (n, g) for s, n, g in all_symbols()}
    close, stale = close or {}, stale or {}
    out = {}
    for sym, r in rows.items():
        name, group = names.get(sym, (sym, ""))
        if group in ("check", "heavy_us", "heavy_jp"):
            continue
        daily = _daily(r, sym)
        sd = _std([x for _, x in daily[-61:-1]])   # 当日を除いた直近60日
        lastv = (close.get(sym) or r)[-1][1]
        f = {"sym": sym, "name": name, "group": group, "date": r[-1][0], "last": _r(lastv, 4),
             "unit": "bp" if sym in YIELD_SYMS else "%", "sd": _r(sd, 3)}
        for h in (1, 5, 20, 60):
            c = _chg(r, sym, h)
            f[f"c{h}"] = _r(c)
            f[f"z{h}"] = _r(c / (sd * math.sqrt(h)), 2) if (c is not None and sd) else None
        s50, s200 = _sma(r, 50), _sma(r, 200)
        f["above50"] = None if s50 is None else r[-1][1] > s50
        f["above200"] = None if s200 is None else r[-1][1] > s200
        f["dist50"] = _r((r[-1][1] / s50 - 1) * 100) if s50 and sym not in YIELD_SYMS else None
        if sym in stale:
            f["stale"] = True
            for k in ("c1", "z1"):
                f[k] = None
        out[sym] = f
    # 対ベンチマーク(米国はS&P 500、日本はTOPIX)
    for sym, f in out.items():
        bench = {"us": "SPY", "jp": "1306.T"}.get(f["group"])
        if bench and bench in out:
            for h in (1, 5, 20):
                a, b = f.get(f"c{h}"), out[bench].get(f"c{h}")
                f[f"rs{h}"] = _r(a - b) if a is not None and b is not None else None
    return out


def _mean_daily(rows, syms):
    """複数銘柄の1日の変化の平均を日付ごとに(全銘柄がそろった日だけ)"""
    per = [dict(_daily(rows[s], s)) for s in syms if s in rows]
    if len(per) != len(syms):
        return None
    days = sorted(set.intersection(*[set(p) for p in per]))
    return [(d, sum(p[d] for p in per) / len(per)) for d in days]


def signals(rows):
    """資金の流れ。買い側の平均 − 売り側の平均を、1日・5日・20日で。z値も付ける"""
    out = []
    for sid, name, buy, sell, meaning in SIGNALS:
        a, b = _mean_daily(rows, buy), _mean_daily(rows, sell)
        if not a or not b:
            continue
        bd = dict(b)
        spread = [(d, x - bd[d]) for d, x in a if d in bd]
        if len(spread) < 61:
            continue
        sd = _std([x for _, x in spread[-61:-1]])
        s = {"id": sid, "name": name, "meaning": meaning, "date": spread[-1][0]}
        for h in (1, 5, 20):
            c = sum(x for _, x in spread[-h:])
            s[f"c{h}"] = _r(c)
            s[f"z{h}"] = _r(c / (sd * math.sqrt(h)), 2) if sd else None
        out.append(s)
    return out


def breadth(feat, group):
    xs = [f for f in feat.values() if f["group"] == group]
    if not xs:
        return None
    up = sum(1 for f in xs if (f.get("c1") or 0) > 0)
    a50 = sum(1 for f in xs if f.get("above50"))
    return {"n": len(xs), "up1": up, "above50": a50}


# ---------- 2b. 指数を動かした銘柄(固定の主力銘柄)と、その日に大きく動いた大型株(動的) ----------
# 2026-11-26の検証(過去250日、前150日で推定し残り約100日で確かめた):
#   日経平均−TOPIXの差は、17業種だけで77%、主力10銘柄を加えると92%まで説明できる(値がさ株の影響が大きい)
#   米国の時価総額加重−均等加重の差は、セクターで96%、主力を加えて97%。説明力の上乗せは小さいが、
#   ±1%以上動いた日の約3割で、1銘柄が巨大株の影響の半分以上を占める(どの会社かを名指しできる)
#   その日の値動き上位75件のうち、時価総額1000億ドル以上は13件で、半導体などその日の主役が入っていた
HEAVY_US = [("NVDA", "エヌビディア"), ("MSFT", "マイクロソフト"), ("AAPL", "アップル"), ("AMZN", "アマゾン"),
            ("GOOGL", "アルファベット"), ("META", "メタ"), ("AVGO", "ブロードコム"), ("TSLA", "テスラ"),
            ("BRK-B", "バークシャー・ハサウェイ"), ("JPM", "JPモルガン")]
HEAVY_JP = [("9983.T", "ファーストリテイリング"), ("8035.T", "東京エレクトロン"), ("6857.T", "アドバンテスト"),
            ("9984.T", "ソフトバンクグループ"), ("4063.T", "信越化学"), ("6954.T", "ファナック"), ("6758.T", "ソニーグループ"),
            ("7203.T", "トヨタ自動車"), ("8306.T", "三菱UFJ"), ("6501.T", "日立製作所")]
MOVER_MIN_CAP = 5e10      # 動的に拾う大型株の下限(500億ドル)。小型株の急騰・急落は指数の説明に使えない
MOVER_MIN_MOVE = 2.0      # 値動き上位から拾う下限(%)
SCREENS = ("day_gainers", "day_losers", "most_actives")


def _ridge(y, X, lam=0.5):
    """切片つきの最小二乗(小さな正則化)。重みを返す"""
    k = len(X[0]) + 1
    A = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for yi, xi in zip(y, X):
        v = [1.0] + list(xi)
        for i in range(k):
            b[i] += v[i] * yi
            for j in range(k):
                A[i][j] += v[i] * v[j]
    for i in range(1, k):
        A[i][i] += lam
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[p], b[i], b[p] = A[p], A[i], b[p], b[i]
        for r in range(k):
            if r != i and A[i][i]:
                f = A[r][i] / A[i][i]
                A[r] = [x - f * y_ for x, y_ in zip(A[r], A[i])]
                b[r] -= f * b[i]
    return [b[i] / A[i][i] if A[i][i] else 0.0 for i in range(k)]


def contributions(rows, index, bench, heavy, stale=None):
    """指数(index)と幅広い指標(bench)の差を、主力銘柄の「benchとの差」に分ける。
    重みは前日までの約1年で推定し(当日を推定に使わない)、当日と5日の寄与を出す"""
    stale = stale or {}
    syms = [s for s, _ in heavy if s in rows and s not in stale]
    if index not in rows or bench not in rows or len(syms) < 5:
        return None
    rr = {s: dict((b[0], (b[1] / a[1] - 1) * 100) for a, b in zip(rows[s], rows[s][1:])) for s in syms + [index, bench]}
    days = sorted(set.intersection(*[set(v) for v in rr.values()]))
    if len(days) < 120:
        return None
    last = days[-1]
    if last != rows[index][-1][0]:
        return None   # 主力銘柄の当日分が欠けている
    hist = days[:-1]
    y = [rr[index][d] - rr[bench][d] for d in hist]
    use = list(syms)
    for _ in range(len(syms)):   # 重みがマイナスの銘柄を外して推定し直す(指数に入っている銘柄の重みは0以上)
        X = [[rr[s][d] - rr[bench][d] for s in use] for d in hist]
        coef = _ridge(y, X)
        neg = [s for s, c in zip(use, coef[1:]) if c < 0]
        if not neg:
            break
        use = [s for s in use if s not in neg]
    wmap = dict(zip(use, coef[1:]))
    w = [0.0] + [wmap.get(s, 0.0) for s in syms]
    names = dict(heavy)
    out = {"index": index, "bench": bench, "date": last}
    for h in (1, 5):
        ds = days[-h:]
        gap = sum(rr[index][d] - rr[bench][d] for d in ds)
        items = []
        for j, s in enumerate(syms):
            ex = sum(rr[s][d] - rr[bench][d] for d in ds)
            ret = sum(rr[s][d] for d in ds)
            items.append({"sym": s, "name": names[s], "ret": _r(ret), "contrib": _r(w[j + 1] * ex), "weight": _r(w[j + 1], 3)})
        items.sort(key=lambda x: -abs(x["contrib"] or 0))
        out[f"d{h}"] = {"gap": _r(gap), "items": items}
    return out


def fetch_movers(expected_us, get=None):
    """Yahooのスクリーナーから、その日に大きく動いた大型の米国株。当日(米国の最新の取引日)の値でなければ使わない"""
    from datetime import datetime, timezone
    import urllib.request
    get = get or (lambda u: json.loads(urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": _eb()._UA}), timeout=20).read().decode()))
    seen, out, errors = set(), [], []
    for sc in SCREENS:
        quotes = None
        for host in ("query1", "query2"):
            try:
                d = get(f"https://{host}.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={sc}&count=50")
                quotes = d["finance"]["result"][0]["quotes"]
                break
            except Exception as e:
                errors.append(f"{sc} {host}: {type(e).__name__}")
        for q in quotes or []:
            sym, cap, chg, t = q.get("symbol"), q.get("marketCap") or 0, q.get("regularMarketChangePercent"), q.get("regularMarketTime")
            if not sym or sym in seen or cap < MOVER_MIN_CAP or not isinstance(chg, (int, float)) or not t:
                continue
            day = _eb()._to_et(datetime.fromtimestamp(t, timezone.utc)).date().isoformat()
            if day != expected_us or (sc != "most_actives" and abs(chg) < MOVER_MIN_MOVE):
                continue
            seen.add(sym)
            et = q.get("earningsTimestamp") or q.get("earningsTimestampStart")
            earn = bool(et and abs(et - t) <= 2 * 86400)   # 決算の発表が前後2日以内
            out.append({"sym": sym, "name": q.get("shortName") or q.get("longName") or sym, "chg": _r(chg),
                        "cap_b": round(cap / 1e9), "earnings": earn, "list": sc})
    out.sort(key=lambda x: -abs(x["chg"]))
    return out[:15], errors


# ---------- 3. 規則にもとづく主因の候補 ----------
def _f(feat, sym, key):
    return (feat.get(sym) or {}).get(key)


def _sig(sigs, sid):
    return next((s for s in sigs if s["id"] == sid), None)


def _fmt(x, unit="%"):
    if x is None:
        return "—"
    return f"{x:+.2f}{unit}" if unit == "%" else f"{x:+.0f}{unit}"


def rule_drivers(feat, sigs, h=5, contrib=None):
    """h日の値動きの主因の候補を、強さ(z値)の順に。各候補は材料の数字つき"""
    k, zk = f"c{h}", f"z{h}"
    spx = _f(feat, "SPY", k)
    out = []

    def add(title, score, side, text, evid):
        out.append({"title": title, "score": round(abs(score), 2), "side": side, "text": text, "evidence": evid})

    tnx_z, tnx = _f(feat, "^TNX", zk), _f(feat, "^TNX", k)
    rs = _sig(sigs, "rate_sens")
    if tnx_z is not None and abs(tnx_z) >= 1 and rs and rs.get(zk) is not None and rs[zk] * tnx_z < 0:
        up = tnx_z > 0
        add("金利の上昇が株価の重し" if up else "金利の低下が株価の追い風", (abs(tnx_z) + abs(rs[zk])) / 2,
            "下落要因" if up else "上昇要因",
            f"米10年債利回りが{h}日で{_fmt(tnx, 'bp')}。金利に敏感な不動産・公益はS&P 500より{_fmt(rs[k])}"
            + ("(金利が上がると、将来の利益の今の価値が下がり、特に高PERの株と借入の多い業種が売られる)" if up else
               "(金利が下がると、将来の利益の今の価値が上がり、借入の多い業種や高PERの株の支えになる)"),
            ["^TNX", "rate_sens"])
    sm = _sig(sigs, "semi")
    if sm and sm.get(zk) is not None and abs(sm[zk]) >= 1:
        up = sm[k] > 0
        add("AI・半導体株が相場を主導" if up else "AI・半導体株の売りが相場の重し", abs(sm[zk]),
            "上昇要因" if up else "下落要因",
            f"半導体(SMH)はS&P 500より{h}日で{_fmt(sm[k])}。指数に占める比率が大きく、指数全体の方向を左右する",
            ["SMH", "semi"])
    cd = _sig(sigs, "cyc_def")
    vix_z = _f(feat, "^VIX", zk)
    if cd and cd.get(zk) is not None and abs(cd[zk]) >= 1:
        on = cd[k] > 0
        add("景気に強気な買い(リスクオン)" if on else "守りの売買(リスクオフ)", abs(cd[zk]),
            "上昇要因" if on else "下落要因",
            f"景気敏感株はディフェンシブ株より{h}日で{_fmt(cd[k])}"
            + (f"、VIXの変化は{_fmt(_f(feat, '^VIX', k))}" if vix_z is not None else ""),
            ["cyc_def", "^VIX"])
    cr = _sig(sigs, "credit")
    if cr and cr.get(zk) is not None and cr[zk] <= -1:
        add("信用への不安(社債が売られ国債へ逃避)", abs(cr[zk]), "下落要因",
            f"ハイイールド債は米長期国債より{h}日で{_fmt(cr[k])}。株より先に動きやすい信用市場の警戒信号",
            ["HYG", "credit"])
    oil_z, oil = _f(feat, "CL=F", zk), _f(feat, "CL=F", k)
    if oil_z is not None and abs(oil_z) >= 1.2:
        up = oil > 0
        add("原油高(インフレ・利下げ遠のく懸念)" if up else "原油安(インフレ鈍化・需要減速)", abs(oil_z),
            "下落要因" if up else "中立",
            f"WTI原油が{h}日で{_fmt(oil)}。エネルギー株はS&P 500より{_fmt(_f(feat, 'XLE', 'rs' + str(h)))}", ["CL=F", "XLE"])
    dx_z, dx = _f(feat, "DX-Y.NYB", zk), _f(feat, "DX-Y.NYB", k)
    if dx_z is not None and abs(dx_z) >= 1.2:
        add("ドル高(米国外の企業と新興国に逆風)" if dx > 0 else "ドル安(米国の多国籍企業・新興国に追い風)", abs(dx_z),
            "下落要因" if dx > 0 else "上昇要因", f"ドル指数が{h}日で{_fmt(dx)}", ["DX-Y.NYB"])
    br = _sig(sigs, "breadth")
    if br and br.get(zk) is not None and br[zk] <= -1 and (spx or 0) > 0:
        add("一部の大型株頼みの上昇(相場の幅が狭い)", abs(br[zk]), "中立",
            f"S&P 500は{h}日で{_fmt(spx)}だが、均等加重は時価総額加重より{_fmt(br[k])}。上昇の土台が細い", ["RSP", "breadth"])
    if br and br.get(zk) is not None and br[zk] >= 1:
        add("大型株から幅広い銘柄への資金の移動(ローテーション)", abs(br[zk]), "中立",
            f"均等加重のS&P 500は時価総額加重より{h}日で{_fmt(br[k])}。巨大ハイテク株の比重を落とし、出遅れ株へ乗り換える動き"
            + ("。指数は下げても、多くの銘柄は持ちこたえている" if (spx or 0) < 0 else ""), ["RSP", "breadth"])
    glob = [s for s in ("^STOXX50E", "^HSI", "^N225", "^KS11") if _f(feat, s, zk) is not None]
    if len(glob) >= 3 and spx is not None:
        zs = [_f(feat, s, zk) for s in glob]
        if all(z <= -1 for z in zs) or all(z >= 1 for z in zs):
            down = zs[0] < 0
            add("世界の株が同時に" + ("下落(世界共通の不安)" if down else "上昇(世界的なリスク選好)"),
                sum(abs(z) for z in zs) / len(zs), "下落要因" if down else "上昇要因",
                "、".join(f"{feat[s]['name']}{_fmt(feat[s][k])}" for s in glob), glob)
    jy_z, jy = _f(feat, "JPY=X", zk), _f(feat, "JPY=X", k)
    ext = _sig(sigs, "jp_ext")
    if jy_z is not None and abs(jy_z) >= 1 and ext and ext.get(k) is not None and ext[k] * jy > 0:
        add("日本: 円安で輸出株が買われる" if jy > 0 else "日本: 円高で輸出株が売られる", (abs(jy_z) + abs(ext.get(zk) or 0)) / 2,
            "上昇要因" if jy > 0 else "下落要因",
            f"ドル円が{h}日で{_fmt(jy)}、外需株は内需株より{_fmt(ext[k])}", ["JPY=X", "jp_ext"])
    # 指数が一部の主力銘柄に引っ張られた(日経平均−TOPIX、時価総額加重−均等加重)
    for key, sid, label in (("jp", "jp_n225", "日経平均"), ("us", "breadth", "S&P 500")):
        c = (contrib or {}).get(key) or {}
        d = c.get(f"d{h}")
        sg = _sig(sigs, sid)
        if not d or not d["items"] or not sg or sg.get(zk) is None or abs(sg[zk]) < 1:
            continue
        top = [x for x in d["items"] if x["contrib"] is not None and abs(x["contrib"]) >= 0.15 * abs(d["gap"]) and x["contrib"] * d["gap"] > 0][:3]
        share = sum(x["contrib"] for x in top) / d["gap"] if d["gap"] else 0
        if not top or share < 0.4:
            continue
        idx_gap = "日経平均とTOPIXの差" if key == "jp" else "時価総額加重と均等加重の差"
        add(f"{label}は一部の主力銘柄に{'押し下げ' if d['gap'] < 0 else '押し上げ'}られた", abs(sg[zk]), "中立",
            f"{idx_gap}は{h}日で{_fmt(d['gap'])}。うち" + "、".join(f"{x['name']}({_fmt(x['ret'])})が{_fmt(x['contrib'])}" for x in top)
            + "(推定)。指数の動きほど、多くの銘柄は動いていない", [sid] + [x["sym"] for x in top])
    # ここまでの型に当てはまらないが、ふだんより大きく動いた資金の流れ
    used = {e for x in out for e in x["evidence"]}
    for s in sigs:
        z = s.get(zk)
        if s["id"] in used or z is None or abs(z) < 1.5:
            continue
        add(f"資金の流れ: {s['name']}が{'プラス' if z > 0 else 'マイナス'}に大きく振れた", abs(z), "中立",
            f"{h}日で{_fmt(s[k])}(ふだんの{abs(z):.1f}倍の動き)。{s['meaning']}", [s["id"]])
    out.sort(key=lambda x: -x["score"])
    return out[:6]


# ---------- 4. AIの多段分析 ----------
def _line(f):
    if f["unit"] == "bp":
        ch = " ".join(f"{h}日{_fmt(f.get('c' + str(h)), 'bp')}" for h in (1, 5, 20))
        return f"{f['sym']} {f['name']} 水準{f['last']:.2f}% {ch} (z1 {f.get('z1')}, z5 {f.get('z5')})"
    rs = f" 対指数 1日{_fmt(f.get('rs1'))} 20日{_fmt(f.get('rs20'))}" if f.get("rs1") is not None else ""
    pos = {True: "上", False: "下", None: "—"}
    return (f"{f['sym']} {f['name']} 1日{_fmt(f.get('c1'))} 5日{_fmt(f.get('c5'))} 20日{_fmt(f.get('c20'))} "
            f"60日{_fmt(f.get('c60'))} (z1 {f.get('z1')}, z5 {f.get('z5')}){rs} 50日線の{pos[f.get('above50')]}・200日線の{pos[f.get('above200')]}")


def data_block(feat, sigs, macro=None, contrib=None, movers=None):
    """AIに渡すデータの表(記号つき。主張の根拠にはこの記号を使わせる)"""
    parts = []
    for g, title in (("style", "米国株の全体と信用"), ("us", "米国のセクター(ETF)"), ("jp", "日本の業種(TOPIX-17のETF)"),
                     ("global", "世界の株価指数"), ("cross", "金利・恐怖指数・商品・為替")):
        xs = [f for f in feat.values() if f["group"] == g]
        if xs:
            parts.append(f"■{title}(日付 {max(f['date'] for f in xs)})\n" + "\n".join(_line(f) for f in xs))
    if sigs:
        parts.append("■資金の流れ(買い側 − 売り側の騰落の差)\n" + "\n".join(
            f"{s['id']} {s['name']} 1日{_fmt(s['c1'])} 5日{_fmt(s['c5'])} 20日{_fmt(s['c20'])} (z5 {s['z5']}): {s['meaning']}"
            for s in sigs))
    for key, title in (("us", "米国: 時価総額加重(SPY)と均等加重(RSP)の差を動かした主力銘柄(推定の寄与)"),
                       ("jp", "日本: 日経平均とTOPIXの差を動かした値がさ株(推定の寄与)")):
        c = (contrib or {}).get(key)
        if c:
            parts.append(f"■{title}(日付 {c['date']})\n" + "\n".join(
                f"{h[1:]}日: 差{_fmt(c[h]['gap'])} / " + "、".join(f"{x['sym']} {x['name']} 騰落{_fmt(x['ret'])} 寄与{_fmt(x['contrib'])}" for x in c[h]["items"][:6])
                for h in ("d1", "d5")))
    if movers:
        parts.append("■当日に大きく動いた大型の米国株(時価総額500億ドル以上)\n" + "\n".join(
            f"{m['sym']} {m['name']} {_fmt(m['chg'])} 時価総額{m['cap_b'] * 10:,}億ドル{' 決算発表の前後' if m['earnings'] else ''}"
            for m in movers))
    if macro:
        parts.append("■マクロ(FRED)\n" + "\n".join(f"{k} {v}" for k, v in macro.items()))
    return "\n\n".join(parts)


def macro_lines(market):
    """学習アプリ用データ(FRED)から、マクロの水準と変化を短い文に"""
    if not market:
        return {}
    out = {}
    for sid, s in (market.get("series") or {}).items():
        rows = s.get("rows") or []
        if len(rows) < 25:
            continue
        last, prev = rows[-1][1], rows[-21][1] if len(rows) > 21 else rows[0][1]
        out[sid] = f"{s['name']}: {rows[-1][0]} {last:g}(約1か月前 {prev:g})"
    return out


def news_block(out, saved=None):
    """その日のニュース要約(検証済み)と見出し。番号はN1〜。outが無い時(取り直し)は保存した行を使う"""
    if not out:
        if saved:
            return "\n".join(saved), list(saved)
        return "(ニュースは取得できませんでした)", []
    econ, major = out.get("econ") or {}, out.get("major") or {}
    lines, texts = [], []
    if econ.get("ok"):
        lines.append(f"経済ニュースの見出し: {econ.get('headline', '')}")
        for p in econ.get("key_points") or []:
            lines.append(f"- [{p.get('category', '')}] {p.get('text', '')} {p.get('why') or ''}")
        for u in econ.get("upcoming") or []:
            lines.append(f"- 予定 {u.get('date', '')}: {u.get('event', '')}")
    for it in (major.get("items") or []) if major.get("ok") else []:
        lines.append(f"- [主要・{it.get('category', '')}] {it.get('title', '')}: {it.get('lead', '')} {it.get('why_it_matters', '')}")
    arts = list(out.get("econ_articles") or [])[:14] + list(out.get("major_articles") or [])[:10]
    for i, a in enumerate(arts, 1):
        t = f"{a.get('title', '')} — {(a.get('description') or '')[:220]}"
        lines.append(f"N{i} ({a.get('source', '')}, {str(a.get('publishedAt', ''))[:10]}) {t}")
        texts.append(t)
    return "\n".join(lines) or "(ニュースは取得できませんでした)", texts + lines


COMMON = """あなたは米国株と日本株の両方を扱う、実績のあるプロの投資家・アナリストのチームの一員です。
読み手は株式投資を本気で学んでいる個人です。専門用語には短い言い換えを添え、「何が起きた → なぜ株価が動く(仕組み) → どの業種に効く」の順で、
プロの視点を省略せずに書いてください。すべて日本語。
厳守:
- 数字はデータの表とニュースにあるものだけを使う。表に無い数字(PER、決算の数字、目標株価など)を作らない
- 根拠(evidence)には、表の記号(例 XLK, ^TNX, cyc_def)かニュースの番号(例 N3)を入れる
- 文章(title・explain・summaryなど)には記号や番号を書かない。「テクノロジー株」「半導体株」「ハイイールド債」「ニュース」のように日本語の名前で書く
- 日本の金利(国債利回り)のデータは無い。日本の銀行株を米国の金利だけで説明しない。データから原因を特定できない時は、そう書く
- ニュースに無い出来事を事実として書かない。推測は「〜の可能性」と書く
- 断定的な売買の推奨はしない
"""

ITEM = {"type": "OBJECT", "properties": {
    "title": {"type": "STRING"}, "explain": {"type": "STRING"},
    "impact": {"type": "STRING", "enum": ["上昇要因", "下落要因", "中立"]},
    "confidence": {"type": "STRING", "enum": ["高", "中", "低"]},
    "evidence": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["title", "explain", "impact", "evidence"]}
ANALYST_SCHEMA = {"type": "OBJECT", "properties": {
    "view": {"type": "STRING"}, "items": {"type": "ARRAY", "items": ITEM},
    "watch": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["view", "items"]}
CAUSE = {"type": "OBJECT", "properties": {
    "title": {"type": "STRING"}, "weight": {"type": "INTEGER"}, "explain": {"type": "STRING"},
    "evidence": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["title", "weight", "explain", "evidence"]}
MKT = {"type": "OBJECT", "properties": {
    "direction": {"type": "STRING", "enum": ["上昇", "下落", "もみ合い"]},
    "summary": {"type": "STRING"}, "causes": {"type": "ARRAY", "items": CAUSE}},
    "required": ["direction", "summary", "causes"]}
CHIEF_SCHEMA = {"type": "OBJECT", "properties": {
    "headline": {"type": "STRING"}, "us": MKT, "jp": MKT,
    "sectors": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "name": {"type": "STRING"}, "why": {"type": "STRING"}}, "required": ["name", "why"]}},
    "debate": {"type": "STRING"},
    "outlook_short": {"type": "STRING"}, "outlook_mid": {"type": "STRING"},
    "watch": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "what": {"type": "STRING"}, "why": {"type": "STRING"}}, "required": ["what", "why"]}},
    "change": {"type": "ARRAY", "items": {"type": "STRING"}},
    "confidence": {"type": "STRING", "enum": ["高", "中", "低"]},
    "lesson": {"type": "STRING"}},
    "required": ["headline", "us", "jp", "debate", "outlook_short", "outlook_mid", "change", "confidence", "lesson"]}
REVIEW_SCHEMA = {"type": "OBJECT", "properties": {
    "ok": {"type": "BOOLEAN"},
    "issues": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "where": {"type": "STRING"}, "problem": {"type": "STRING"}, "fix": {"type": "STRING"}},
        "required": ["problem", "fix"]}}}, "required": ["ok", "issues"]}

ROLES = [
    ("macro", "マクロ・金利ストラテジスト",
     "金利(10年債・3か月債・長短金利差)、ドル、原油、信用スプレッド、FRBの政策と経済指標の観点から、"
     "直近1日と5日の株価の動きの原因を分析する。金利の変化がどの業種のバリュエーションにどう効いたかを、仕組みまで説明する。"),
    ("sector", "セクター・資金の流れのアナリスト",
     "米国12セクターと日本17業種の騰落、資金の流れの表(景気敏感とディフェンシブ、半導体、相場の幅、小型株、外需と内需)から、"
     "お金がどこから出てどこへ向かったかを特定し、それが何を織り込んでいるか(景気、金利、AI投資、円相場)を分析する。"
     "z値が大きい(ふだんより大きく動いた)業種を優先する。さらに、指数を動かした主力銘柄の推定の寄与(日経平均−TOPIX、"
     "時価総額加重−均等加重)と、当日に大きく動いた大型株の表から、指数の動きが一部の銘柄によるものか、幅広い銘柄によるものかを判定し、"
     "同じ業種の大型株がそろって動いていれば業種全体の材料、1社だけなら(決算など)個別の材料として区別する。"),
    ("world", "世界情勢・ニュースのアナリスト",
     "ニュース(政策、地政学、貿易、AI・半導体、決算)と世界の株価指数(欧州・中国・香港・韓国・日本)から、"
     "市場を動かした出来事を特定し、それが米国株と日本株にどう波及したかを分析する。当日に大きく動いた大型株(決算の前後の印つき)と"
     "ニュースを結び付ける。ニュースと値動きが一致しない場合はそう書く。"),
]
BEAR = ("bear", "弱気筋(マイケル・バーリや空売り筋の思考)",
        "ここまでの3人の分析を読み、懐疑的な空売り筋として反論する。過熱、一部銘柄への集中、信用の悪化、"
        "金利と株価の不整合、強気の前提の弱さを探し、「何が起きたら下落が本格化するか」まで書く。items の impact は主に下落要因。")
BULL = ("bull", "強気筋(トレンドフォロワーとオプション・需給を見るトレーダー)",
        "ここまでの分析と弱気筋の主張を読み、強気の側から反論する。トレンド、資金の流れの改善、悲観の行き過ぎ(VIXの高さ)、"
        "政策の追い風を探し、弱気筋の主張のどこが弱いかを具体的に書く。items の impact は主に上昇要因。")


def _ask(prompt, schema, label):
    eb = _eb()
    text = eb._call_gemini(prompt, schema, label, models=DEEP_MODELS)
    data = eb._loads_loose(text) if text else None
    if not isinstance(data, dict):
        raise ValueError(f"{label}: JSONとして読めない応答")
    return data


def _analyst_prompt(role, data_txt, news_txt, prior):
    _, name, task = role
    p = COMMON + f"\nあなたの役割: {name}\n課題: {task}\n\n出力(JSON): view=この役割としての結論を2〜4文、" \
        "items=原因や論点を3〜5個(title 25字以内、explain 120〜220字で仕組みまで、impact、confidence、evidence)、watch=今後の注目点を2〜3個\n"
    if prior:
        p += "\n■ほかのアナリストの分析\n" + prior + "\n"
    return p + "\n■データ\n" + data_txt + "\n\n■ニュース\n" + news_txt


def _prior_txt(passes):
    out = []
    for k, v in passes.items():
        out.append(f"[{v['role']}] {v['view']}\n" + "\n".join(
            f"- {it['title']}({it.get('impact', '')}): {it['explain']}" for it in v["items"]))
    return "\n\n".join(out)


def _chief_prompt(data_txt, news_txt, passes, rules, issues=None, draft=None):
    p = COMMON + """
あなたの役割: チーフアナリスト。5人の分析(マクロ・金利、セクター・資金、世界情勢、弱気筋、強気筋)を突き合わせ、
データでいちばん裏付けのある説明を選び、チームの最終的な見解をまとめる。意見が割れる点は、どちらがデータで優勢かを判定する。
出力(JSON):
- headline: 今日の相場を一言で(40字以内)
- us / jp: direction(直近5日の方向)、summary(なぜそう動いたかを3〜5文)、causes(主因を3〜4個。weightは説明できる割合の目安で合計100、explainは仕組みまで120〜200字、evidence)
- sectors: 大きく動いた業種を米日あわせて4〜6個、name と why(なぜその業種が買われた・売られたか、80〜140字)
- debate: 弱気筋と強気筋のどちらがデータで優勢か、その理由(3〜4文)
- outlook_short: 数日〜2週間の見通し(3〜4文、条件つきで)
- outlook_mid: 1〜3か月の見通し(3〜4文、条件つきで)
- watch: これから注目する指標・出来事と、その理由(3〜4個)
- change: この見解が変わる条件(3〜4個)
- confidence: 見解の確信度
- lesson: 今日の相場から学べる一般的な原則(2〜3文)
"""
    p += "\n■規則にもとづく主因の候補(データから自動計算)\n" + "\n".join(f"- {r['title']}({r['side']}): {r['text']}" for r in rules)
    p += "\n\n■5人の分析\n" + _prior_txt(passes)
    if issues and draft:
        p += "\n\n■あなたの前回の案\n" + json.dumps(draft, ensure_ascii=False) + \
             "\n\n■査読で指摘された問題(すべて直した最終版を出す)\n" + "\n".join(f"- {i.get('where', '')}: {i['problem']} → {i['fix']}" for i in issues)
    return p + "\n\n■データ\n" + data_txt + "\n\n■ニュース\n" + news_txt


def _review_prompt(data_txt, news_txt, draft):
    return COMMON + """
あなたの役割: 査読者(リスク管理の責任者)。チーフアナリストの案を、データの表とニュースに照らして厳しく確かめる。
探すもの: データと逆の記述(上がった業種を下がったと書く等)、表やニュースに無い数字、根拠の無い断定、ニュースに無い出来事、
米国と日本の取り違え、weightの合計が100でない、見通しが条件なしの断定になっている。
問題がなければ ok=true・issues=[]。問題があれば ok=false で、場所(where)・問題(problem)・直し方(fix)を具体的に。
""" + "\n■チーフの案\n" + json.dumps(draft, ensure_ascii=False) + "\n\n■データ\n" + data_txt + "\n\n■ニュース\n" + news_txt


# ---------- 5. 数字の照合 ----------
_NUM = re.compile(r"([+\-−▲]?)(\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|％|bp|ベーシス|ポイント|pt|円|ドル|倍)")


def allowed_numbers(feat, sigs, macro, news_texts, contrib=None, movers=None):
    """単位ごとに、使ってよい数字の集合。{"pct": [...], "bp": [...], "x": [...], "lvl": [...]}
    %はデータの騰落率と利回りの水準、bpは利回りの変化、倍はz値、価格(円・ドル・ポイント)は水準。ニュースの数字はどの単位でも使ってよい"""
    vals = {"pct": set(), "bp": set(), "x": set(), "lvl": set()}

    def add(kind, x):
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            vals[kind].add(abs(float(x)))
    for f in feat.values():
        bp = f["unit"] == "bp"
        for k, v in f.items():
            if k[:1] in ("c", "r", "d") and k[1:2].isdigit() or k in ("dist50",) or k.startswith("rs"):
                add("bp" if bp and k.startswith("c") else "pct", v)
            elif k.startswith("z"):
                add("x", v)
        add("pct" if bp else "lvl", f.get("last"))
    for s in sigs:
        for h in (1, 5, 20):
            add("pct", s.get(f"c{h}"))
            add("x", s.get(f"z{h}"))
    for c in (contrib or {}).values():
        for h in ("d1", "d5"):
            for x in ((c or {}).get(h) or {}).get("items") or []:
                add("pct", x.get("ret"))
                add("pct", x.get("contrib"))
            add("pct", ((c or {}).get(h) or {}).get("gap"))
    for m in movers or []:
        add("pct", m.get("chg"))
        add("lvl", m.get("cap_b"))
        add("lvl", (m.get("cap_b") or 0) * 10)
    for t in list((macro or {}).values()) + list(news_texts or []):
        t = re.sub(r"\d{4}-\d{2}-\d{2}", " ", str(t))   # 日付の数字は使ってよい数字に入れない
        for m in re.finditer(r"\d+(?:,\d{3})*(?:\.\d+)?", t):
            for kind in vals:
                add(kind, float(m.group(0).replace(",", "")))
    return {k: sorted(v) for k, v in vals.items()}


_UNIT_KIND = {"%": "pct", "％": "pct", "ポイント": "lvl", "pt": "lvl", "円": "lvl", "ドル": "lvl", "倍": "x", "bp": "bp", "ベーシス": "bp"}


def _ok_num(x, allowed, small=True):
    if small and x <= 10 and float(x).is_integer():
        return True   # 「3つ」「2日」程度の小さな整数
    tol = max(0.06, abs(x) * 0.01)
    return any(abs(x - a) <= tol for a in allowed)


def bad_numbers(text, allowed):
    if isinstance(allowed, list):   # 単位を分けない数字の並び(試験用)
        allowed = {k: allowed for k in ("pct", "bp", "x", "lvl")}
    out = []
    for m in _NUM.finditer(text or ""):
        x = float(m.group(2).replace(",", ""))
        kind = _UNIT_KIND[m.group(3)]
        ok = _ok_num(x, allowed[kind], small=kind != "x") or (kind == "bp" and _ok_num(x / 100, allowed["pct"]))
        if kind == "pct" and not ok:   # 利回りの変化を%ポイントで書いた場合(0.22%)
            ok = _ok_num(x * 100, allowed["bp"], small=False)
        if not ok:
            out.append(m.group(0))
    return out


_CODE = r"(?:N\d{1,2}|\^?[A-Z][A-Z0-9]{0,11}(?:[.=\-][A-Z0-9]{1,4})?|\d{4}\.T|[a-z]+_[a-z0-9_]+|breadth|credit|semi|small|cyc_def|rate_sens|cu_au)"
_CODE_PAREN = re.compile(r"\s*[（(]\s*" + _CODE + r"(?:\s*[,、・/]\s*" + _CODE + r")*\s*[)）]")
SIGNAL_NAMES = {sid: name for sid, name, _, _, _ in SIGNALS}
CODE_NAMES = {}   # 記号 → 日本語の名前(run_ai がその日のデータで埋める)


def strip_codes(text):
    """AIが文章に書いた記号を取り除く: 「(N10, N24)」「（XLK）」は消し、文中の記号は名前に置き換え、ニュースの番号は消す"""
    t = _CODE_PAREN.sub("", text)
    for sid, name in sorted(SIGNAL_NAMES.items(), key=lambda x: -len(x[0])):
        t = re.sub(r"(?<![A-Za-z_])" + re.escape(sid) + r"(?![A-Za-z_])", f"「{name}」", t)
    for code, name in sorted(CODE_NAMES.items(), key=lambda x: -len(x[0])):
        t = re.sub(r"(?<![A-Za-z0-9_^.])" + re.escape(code) + r"(?![A-Za-z0-9_])", name, t)
    t = re.sub(r"(?:N\d{1,2}\s*[,、]\s*)*N\d{1,2}(?![0-9])\s*[,、]?\s*", "", t)   # 文中に残ったニュースの番号
    return re.sub(r"[（(]\s*[)）]", "", t)


def scrub(text, allowed, dropped):
    """記号を取り除き、確かめられない数字を含む文を捨てる"""
    if not isinstance(text, str):
        return ""
    text = strip_codes(text)
    keep = []
    for s in re.split(r"(?<=。)", text):
        if not s.strip():
            continue
        bad = bad_numbers(s, allowed)
        if bad:
            dropped.append(f"{'・'.join(bad)}: {s.strip()[:40]}")
            continue
        keep.append(s)
    return "".join(keep).strip()


def _evid(ev, known):
    return [e for e in (ev or []) if isinstance(e, str) and (e in known or re.fullmatch(r"N\d{1,2}", e))]


def clean_items(items, allowed, known, dropped, limit=6):
    out = []
    for it in (items or [])[:limit]:
        if not isinstance(it, dict):
            continue
        title, explain = scrub(it.get("title"), allowed, dropped), scrub(it.get("explain"), allowed, dropped)
        if not title or not explain:
            continue
        x = {"title": title, "explain": explain, "evidence": _evid(it.get("evidence"), known)}
        for k in ("impact", "confidence"):
            if it.get(k):
                x[k] = it[k]
        out.append(x)
    return out


def clean_chief(c, allowed, known, dropped):
    def mkt(m):
        m = m if isinstance(m, dict) else {}
        causes = []
        for x in (m.get("causes") or [])[:5]:
            if not isinstance(x, dict):
                continue
            t, e = scrub(x.get("title"), allowed, dropped), scrub(x.get("explain"), allowed, dropped)
            if t and e:
                w = x.get("weight")
                causes.append({"title": t, "explain": e, "weight": int(w) if isinstance(w, (int, float)) and 0 < w <= 100 else 0,
                               "evidence": _evid(x.get("evidence"), known)})
        tot = sum(x["weight"] for x in causes)
        for x in causes:   # 捨てた主因があっても、残りの合計が100になるよう直す
            x["weight"] = round(x["weight"] * 100 / tot) if tot else round(100 / len(causes))
        d = m.get("direction")
        return {"direction": d if d in ("上昇", "下落", "もみ合い") else "もみ合い",
                "summary": scrub(m.get("summary"), allowed, dropped), "causes": causes}
    s = lambda k: scrub(c.get(k), allowed, dropped)   # noqa: E731
    return {
        "headline": s("headline"), "us": mkt(c.get("us")), "jp": mkt(c.get("jp")),
        "sectors": [{"name": str(x.get("name", ""))[:30], "why": scrub(x.get("why"), allowed, dropped)}
                    for x in (c.get("sectors") or [])[:8] if isinstance(x, dict) and x.get("name")],
        "debate": s("debate"), "outlook_short": s("outlook_short"), "outlook_mid": s("outlook_mid"),
        "watch": [{"what": scrub(x.get("what"), allowed, dropped), "why": scrub(x.get("why"), allowed, dropped)}
                  for x in (c.get("watch") or [])[:5] if isinstance(x, dict)],
        "change": [t for t in (scrub(x, allowed, dropped) for x in (c.get("change") or [])[:5]) if t],
        "confidence": c.get("confidence") if c.get("confidence") in ("高", "中", "低") else "中",
        "lesson": s("lesson"),
    }


def run_ai(feat, sigs, rules, macro, out, contrib=None, movers=None, saved_news=None):
    """役割の違うアナリストを順に重ね、チーフが統合、査読、必要なら改訂。失敗した段は飛ばして続ける"""
    eb = _eb()
    eb._gemini_reset(DEEP_BUDGET)
    labels = {k: v.split(":")[0] for k, v in (macro or {}).items()}
    labels.update({s: n for s, n in HEAVY_US + HEAVY_JP})
    labels.update({m["sym"]: m["name"] for m in movers or []})
    labels.update({k: f["name"] for k, f in feat.items()})
    CODE_NAMES.clear()
    CODE_NAMES.update({k: v for k, v in labels.items() if k not in ("SPY",)})   # SPYはそのままでも通じる
    data_txt = data_block(feat, sigs, macro, contrib, movers)
    news_txt, news_texts = news_block(out, saved_news)
    allowed = allowed_numbers(feat, sigs, macro, news_texts, contrib, movers)
    known = set(feat) | {s["id"] for s in sigs} | {s for s, _ in HEAVY_US + HEAVY_JP} | {m["sym"] for m in movers or []} | set(macro or {})
    dropped, errors, steps = [], [], []
    passes = {}
    for role in ROLES + [BEAR, BULL]:
        key, name, _ = role
        if len(passes) >= 3 and eb._gemini_left() < CHIEF_RESERVE:
            print(f"  深掘り分析: 残り時間が少ないため「{name}」以降を飛ばし、統合へ進む")
            break
        try:
            d = _ask(_analyst_prompt(role, data_txt, news_txt, _prior_txt(passes)), ANALYST_SCHEMA, f"深掘り:{name}")
            passes[key] = {"role": name, "view": scrub(d.get("view"), allowed, dropped),
                           "items": clean_items(d.get("items"), allowed, known, dropped),
                           "watch": [scrub(w, allowed, dropped) for w in (d.get("watch") or [])[:4] if isinstance(w, str)]}
            steps.append(name)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            print(f"  [WARN] 深掘り分析の「{name}」に失敗: {e}")
            if "時間の上限" in str(e):
                break
    if len(passes) < 3:
        return {"ok": False, "passes": passes, "errors": errors, "steps": steps, "dropped": dropped}
    chief = None
    try:
        draft = _ask(_chief_prompt(data_txt, news_txt, passes, rules), CHIEF_SCHEMA, "深掘り:チーフ")
        steps.append("チーフアナリスト")
        chief = draft
        try:
            if eb._gemini_left() < REVIEW_MIN:
                raise RuntimeError("残り時間が少ないため査読を飛ばした")
            rv = _ask(_review_prompt(data_txt, news_txt, draft), REVIEW_SCHEMA, "深掘り:査読")
            steps.append("査読")
            issues = [i for i in (rv.get("issues") or []) if isinstance(i, dict) and i.get("problem")]
            if issues and not rv.get("ok"):
                print(f"  査読の指摘 {len(issues)}件 → チーフが改訂")
                chief = _ask(_chief_prompt(data_txt, news_txt, passes, rules, issues[:8], draft), CHIEF_SCHEMA, "深掘り:改訂")
                steps.append(f"改訂(指摘{len(issues)}件)")
        except Exception as e:   # 査読・改訂の失敗は、チーフの案をそのまま使う
            errors.append(f"査読・改訂: {type(e).__name__}: {e}")
    except Exception as e:
        errors.append(f"チーフ: {type(e).__name__}: {e}")
    result = {"ok": chief is not None, "passes": passes, "errors": errors, "steps": steps, "labels": labels,
              "news": news_txt.split("\n")[:60]}
    if chief is not None:
        result["chief"] = clean_chief(chief, allowed, known, dropped)
    result["dropped"] = dropped
    return result


# ---------- 6. まとめと履歴 ----------
def build_analysis(fetched, market=None, out=None, ai=True, now=None, saved_news=None):
    now = now or datetime.now(_eb().JST)
    rows, q = fetched["rows"], fetched["quality"]
    feat = features(rows, fetched.get("close"), q.get("stale"))
    if sum(1 for f in feat.values() if f["group"] == "us") < MIN_US:
        return None
    sigs = signals(rows)
    contrib = {"us": contributions(rows, "SPY", "RSP", HEAVY_US, q.get("stale")),
               "jp": contributions(rows, "^N225", "1306.T", HEAVY_JP, q.get("stale"))}
    movers = fetched.get("movers") or []
    rules = {"d1": rule_drivers(feat, sigs, 1, contrib), "d5": rule_drivers(feat, sigs, 5, contrib),
             "d20": rule_drivers(feat, sigs, 20)}
    macro = macro_lines(market)
    res = {"updated": now.isoformat(timespec="minutes"), "source": "Yahoo Finance(各ETF・指数)、FRED、ニュース要約",
           "asof": {"us": _f(feat, "SPY", "date"), "jp": _f(feat, "1306.T", "date")}, "quality": q,
           "features": feat, "signals": sigs, "contrib": contrib, "movers": movers, "breadth": {"us": breadth(feat, "us"), "jp": breadth(feat, "jp")},
           "rules": rules}
    res["ai"] = run_ai(feat, sigs, rules["d5"] + rules["d1"][:2], macro, out, contrib, movers, saved_news) if ai else {"ok": False, "errors": ["AIを使わない設定"]}
    return res


def add_history(res, prev):
    """前回までの履歴に今日の見立てを足す(同じ日は置き換え)。答え合わせ用に指数の終値も残す"""
    hist = [h for h in ((prev or {}).get("history") or []) if isinstance(h, dict)]
    c = (res.get("ai") or {}).get("chief")
    entry = {"date": res["asof"]["us"], "spy": _f(res["features"], "SPY", "last"), "n225": _f(res["features"], "^N225", "last"),
             "us": c["us"]["direction"] if c else None, "jp": c["jp"]["direction"] if c else None,
             "headline": c["headline"] if c else (res["rules"]["d5"][0]["title"] if res["rules"]["d5"] else ""),
             "short": c["outlook_short"] if c else ""}
    hist = [h for h in hist if h.get("date") != entry["date"]] + [entry]
    res["history"] = sorted(hist, key=lambda h: h.get("date") or "")[-HISTORY_DAYS:]
    return res


def _read_prev():
    try:
        _, b = _eb()._gh_get_file(ANALYSIS_PATH)
        return json.loads(b.decode("utf-8")) if b else None
    except Exception as e:
        print(f"  [WARN] 前回の深掘り分析を読めない(履歴なしで続ける): {e}")
        return None


def publish_analysis(out=None, market=None, fetch=None, prev=None, saved_news=None, waits=None):
    eb = _eb()
    fetched = fetch_all(fetch, waits=waits)
    res = build_analysis(fetched, market, out, saved_news=saved_news)
    if res is None:
        print("  深掘り分析: 米国セクターのデータが足りないため更新しません")
        return False
    if prev is None:
        prev = _read_prev()
    add_history(res, prev)
    text = json.dumps(res, ensure_ascii=False, separators=(",", ":"))
    eb._gh_put_file(ANALYSIS_PATH, text.encode("utf-8"), f"🔎 学習アプリの深掘り分析: {res['updated'][:16]}")
    ai = res["ai"]
    print(f"  深掘り分析: {len(res['features'])}銘柄、AI {'成功' if ai.get('ok') else '失敗'}"
          f"({' → '.join(ai.get('steps') or [])})、照合で捨てた文 {len(ai.get('dropped') or [])}件")
    return True


def ensure_fresh(now=None):
    """投稿の後の予備の起動で呼ぶ。今朝の深掘り分析が無い・古い・データが欠けていたら作り直す
    (ニュースは前回保存した行を使う)。作り直したら True"""
    from datetime import datetime, timezone
    prev = _read_prev()
    exp = expected_us_date(now or datetime.now(timezone.utc))
    q = (prev or {}).get("quality") or {}
    fresh = prev and (prev.get("asof") or {}).get("us") == exp and q.get("complete") and (prev.get("ai") or {}).get("ok")
    if fresh:
        print(f"  深掘り分析は今朝の分({exp})がそろっているため、作り直さない")
        return False
    print(f"  深掘り分析を作り直す(前回: 日付 {(prev or {}).get('asof')}, データ{'そろい' if q.get('complete') else '欠けあり'})")
    return publish_analysis(None, None, prev=prev, saved_news=((prev or {}).get("ai") or {}).get("news"), waits=BACKUP_WAITS)


if __name__ == "__main__":   # ローカル確認: AIなしで計算だけして標準出力へ
    t = time.time()
    fe = fetch_all(waits=())
    r = build_analysis(fe, ai=False, now=datetime.now())
    print("quality:", json.dumps(r["quality"], ensure_ascii=False))
    print(json.dumps({k: r[k] for k in ("asof", "breadth", "rules")}, ensure_ascii=False, indent=1))
    print("signals:", json.dumps(r["signals"], ensure_ascii=False))
    print(f"{time.time() - t:.1f}秒")
