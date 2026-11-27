"""5e. 需給と戦略(学習アプリ「需給と戦略」用、2026-11追加)

需給(だれが、どれだけ、どちら向きに売買・保有しているか)と、プロのトレーダーが成績を残すための
「市場の状態に合わせた投資比率」「リスク管理」を計算する。deep_dive.py から呼ばれ、結果は analysis.json の
flow と strategy に入る。データはすべて公開の無料の情報(2026-11-26に取得できることを確認)。

  出来高          Yahoo(S&P 500・ナスダック総合・日経平均の指数の出来高)
                  → オニールの「売り抜けの日(ディストリビューション・デー)」と「フォロースルー・デー」
  オプション      CBOE の日次統計(プット・コール比率)、Yahoo(VIX9D・VIX・VIX3M・VVIX・SKEW・VXN)
  大口の持ち高    CFTC の金融先物の建玉(毎週火曜時点、金曜公表、3年分)
  日本の主体別    JPX の投資部門別売買状況(毎週)と信用取引現在高(毎週)
  需給の日程      オプションの満期(米国の第3金曜・日本のSQ)、月末・四半期末

戦略(投資比率の判定)は、オニール・ミネルヴィニ流の公開されている規則をそのまま使い、数値を当てはめで
調整していない(過去に合わせ込むと、将来に通用しないため)。その規則で過去10年を検証した結果も出す。
"""
import io
import json
import math
import re
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; EconoBot/1.0)"}
JST = timezone(timedelta(hours=9))


def _dd():
    import deep_dive
    return deep_dive


def _get(url, timeout=25, tries=3):
    """取得。429(混雑)・5xx・通信の失敗は待って取り直す"""
    err = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            err = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = e
        time.sleep(3 * (i + 1) ** 2)
    raise err


def _r(x, nd=2):
    return None if x is None else round(x, nd)


# ======================================================================
# 1. 出来高: 売り抜けの日とフォロースルー
# ======================================================================
def ohlcv(sym, rng="1y"):
    """Yahooの日足 [(日付, 始値, 高値, 安値, 終値, 出来高)]。取引中の足は除く"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
           f"?range={rng}&interval=1d")
    res = json.loads(_get(url))["chart"]["result"][0]
    meta, ts = res["meta"], res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    off = meta.get("gmtoffset") or 0
    out = {}
    today = datetime.fromtimestamp(time.time() + off, timezone.utc).date().isoformat()
    gaps = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        d = datetime.fromtimestamp(t + off, timezone.utc).date().isoformat()
        if c is None:
            if d < today:
                gaps.append(d)
            continue
        out[d] = (d, q["open"][i] or c, q["high"][i] or c, q["low"][i] or c, c, q["volume"][i] or 0)
    gaps = [d for d in gaps[-20:] if d not in out]
    if gaps:
        try:
            out.update(hourly_days(sym, gaps))
        except Exception as e:
            print(f"    [flows {sym}] 日足が空の日を1時間足で補えない: {type(e).__name__}")
    rows = [out[d] for d in sorted(out)]
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    now = time.time()
    if rows and reg.get("start") and reg["start"] <= now < reg.get("end", 0) + 1200:
        if datetime.fromtimestamp(reg["start"] + off, timezone.utc).date().isoformat() == rows[-1][0]:
            rows = rows[:-1]
    return rows


def hourly_days(sym, days, get=None):
    """日足が空の日(Yahooの^N225で2026-11-26)を1時間足から作る。出来高は分からないので None(出来高の判定では使わない)"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1mo&interval=60m"
    res = json.loads((get or _get)(url))["chart"]["result"][0]
    off = (res.get("meta") or {}).get("gmtoffset") or 0
    q = res["indicators"]["quote"][0]
    agg = {}
    for i, t in enumerate(res.get("timestamp") or []):
        c = q["close"][i]
        d = datetime.fromtimestamp(t + off, timezone.utc).date().isoformat()
        if c is None or d not in days:
            continue
        o, h, lo = q["open"][i] or c, q["high"][i] or c, q["low"][i] or c
        if d in agg:
            a = agg[d]
            agg[d] = (d, a[1], max(a[2], h), min(a[3], lo), c, None)
        else:
            agg[d] = (d, o, h, lo, c, None)
    if agg:
        print(f"    [flows {sym}] 日足が空の日を1時間足で補完: {', '.join(sorted(agg))}")
    return agg


def distribution_days(rows, window=25):
    """売り抜けの日: 0.2%以上下落し、出来高が前日より多い日(直近25日)。
    その日の終値から5%以上上昇したものは数えない(オニールの規則)。出来高が無い日は判定しない"""
    out = []
    last = rows[-1][4]
    for i in range(max(1, len(rows) - window), len(rows)):
        d, _, _, _, c, v = rows[i]
        pc, pv = rows[i - 1][4], rows[i - 1][5]
        if not v or not pv:
            continue
        if (c / pc - 1) <= -0.002 and v > pv and last < c * 1.05:
            out.append({"date": d, "chg": _r((c / pc - 1) * 100)})
    return out


def market_phase(rows):
    """オニールの市場の状態: 上昇トレンド / 調整中(試し上げの日数) / 上昇トレンドの確認(フォロースルー)"""
    closes = [r[4] for r in rows]
    hi = max(closes[-252:])
    dd = (closes[-1] / hi - 1) * 100
    look = rows[-60:]
    low_i = min(range(len(look)), key=lambda i: look[i][3])
    low = look[low_i][3]
    since = look[low_i:]
    ftd = None
    for k in range(4, len(since)):   # 安値の日を1日目として、4日目以降
        d, _, _, lo, c, v = since[k]
        pc, pv = since[k - 1][4], since[k - 1][5]
        if any(x[3] < low for x in since[1:k + 1]):
            break
        if (c / pc - 1) >= 0.0125 and v and pv and v > pv:
            ftd = {"date": d, "chg": _r((c / pc - 1) * 100), "day": k + 1}
            break
    s50 = sum(closes[-50:]) / 50
    if dd > -8 and closes[-1] > s50:
        phase = "上昇トレンド"
    elif ftd:
        phase = "上昇トレンドの再開を確認(フォロースルー)"
    elif dd <= -8:
        phase = f"調整局面(試し上げ{len(since)}日目)" if len(since) > 1 and closes[-1] > low else "調整局面(下げ止まり待ち)"
    else:
        phase = "上昇トレンドに圧力"
    return {"phase": phase, "drawdown": _r(dd), "high": _r(hi), "low60": _r(low), "low60_date": look[low_i][0], "ftd": ftd}


def volume_stats(rows):
    vols = [r[5] for r in rows if r[5]]
    if len(vols) < 51:
        return None
    up = sum(r[5] or 0 for a, r in zip(rows[-21:-1], rows[-20:]) if r[4] > a[4])
    dn = sum(r[5] or 0 for a, r in zip(rows[-21:-1], rows[-20:]) if r[4] < a[4])
    return {"ratio50": _r(rows[-1][5] / (sum(vols[-51:-1]) / 50)) if rows[-1][5] else None, "updown20": _r(up / dn) if dn else None}


def volume_block(symbols=(("^GSPC", "S&P 500"), ("^IXIC", "ナスダック総合"), ("^N225", "日経平均")), get=ohlcv, expected=None):
    out = {}
    for sym, name in symbols:
        try:
            rows = _cut(get(sym), (expected or {}).get(sym))
        except Exception as e:
            print(f"    [需給 出来高 {sym}] 取得失敗 {type(e).__name__}")
            continue
        if len(rows) < 120:
            continue
        has_vol = sum(1 for r in rows[-26:] if r[5]) >= 20
        x = {"name": name, "date": rows[-1][0], "close": _r(rows[-1][4]), **market_phase(rows)}
        if has_vol:
            dds = distribution_days(rows)
            x.update({"dist_days": len(dds), "dist_list": dds[-8:], **(volume_stats(rows) or {})})
        out[sym] = x
    return out


# ======================================================================
# 2. オプション: プット・コール比率とボラティリティの構造
# ======================================================================
CBOE_URL = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{d}_daily_options"
PC_KEYS = {"TOTAL PUT/CALL RATIO": "total", "EQUITY PUT/CALL RATIO": "equity",
           "INDEX PUT/CALL RATIO": "index", "SPX + SPXW + SPXO PUT/CALL RATIO": "spx"}


def putcall_day(d, get=_get):
    j = json.loads(get(CBOE_URL.format(d=d)))
    out = {}
    for r in j.get("ratios") or []:
        k = PC_KEYS.get(r.get("name"))
        if k:
            try:
                out[k] = float(r["value"])
            except (TypeError, ValueError):
                pass
    return out


def putcall_block(expected_us, hist, get=_get):
    """当日分を取り、履歴(前回までの analysis.json)に足す。履歴が少ない時は直近の営業日を取りに行く(初回の埋め合わせ)"""
    dd = _dd()
    hist = {h["date"]: h for h in (hist or []) if isinstance(h, dict) and h.get("date")}
    want = []
    d = date.fromisoformat(expected_us)
    while len(want) < (25 if len(hist) < 20 else 3):
        if dd.us_trading_day(d):
            want.append(d.isoformat())
        d -= timedelta(days=1)
    for ds in want:
        # 直近2営業日は履歴にあっても取り直す。CBOEは引け後に速報を出し、米東部の夜(21:40〜22:00ごろ)に確定版で
        # 上書きするため、朝に取った値を夕方の更新で確定値に入れ替える(取れなければ履歴の値のまま)
        if ds in hist and ds not in want[:2]:
            continue
        try:
            v = putcall_day(ds, get)
            if v:
                hist[ds] = {"date": ds, **v}
        except Exception as e:
            print(f"    [需給 CBOE {ds}] 取得失敗 {type(e).__name__}")
    rows = [hist[k] for k in sorted(hist)][-260:]
    if not rows or rows[-1]["date"] != expected_us:
        return {"ok": False, "hist": rows}
    eq = [r["equity"] for r in rows if "equity" in r]
    tot = [r["total"] for r in rows if "total" in r]
    last = rows[-1]
    return {"ok": True, "date": last["date"], "total": last.get("total"), "equity": last.get("equity"),
            "index": last.get("index"), "spx": last.get("spx"),
            "equity10": _r(sum(eq[-10:]) / len(eq[-10:])) if len(eq) >= 10 else None,
            "total10": _r(sum(tot[-10:]) / len(tot[-10:])) if len(tot) >= 10 else None,
            "equity_pct": _pct_rank(eq[-1], eq) if len(eq) >= 20 else None, "hist": rows}


def _pct_rank(x, xs):
    xs = [v for v in xs if v is not None]
    return round(100 * sum(1 for v in xs if v <= x) / len(xs)) if xs else None


VOL_SYMS = [("^VIX9D", "VIX(9日)"), ("^VIX", "VIX(30日)"), ("^VIX3M", "VIX(3か月)"), ("^VVIX", "VVIX(VIXの変動)"),
            ("^SKEW", "SKEW(急落への備え)"), ("^VXN", "ナスダックのVIX")]


def vol_block(expected_us, fetch=None):
    fetch = fetch or (lambda s: _dd().fetch_one(s))
    v = {}
    for sym, name in VOL_SYMS:
        try:
            r, c = fetch(sym)
        except Exception as e:
            print(f"    [需給 {sym}] 取得失敗 {type(e).__name__}")
            continue
        c = [x for x in c if x[0] <= expected_us]
        if len(c) >= 60 and c[-1][0] == expected_us:
            vals = [x[1] for x in c[-252:]]
            v[sym] = {"name": name, "last": _r(c[-1][1]), "chg1": _r(c[-1][1] - c[-2][1]), "pct1y": _pct_rank(c[-1][1], vals)}
    g = lambda s: (v.get(s) or {}).get("last")   # noqa: E731
    out = {"items": v}
    if g("^VIX") and g("^VIX3M"):
        out["term"] = _r(g("^VIX") / g("^VIX3M"), 3)      # 1超 = 逆転(目先の恐怖が強い)
    if g("^VIX9D") and g("^VIX"):
        out["term_short"] = _r(g("^VIX9D") / g("^VIX"), 3)
    if g("^VIX"):
        out["move1d"] = _r(g("^VIX") / math.sqrt(252), 2)  # オプションが織り込む1日の値動き(1標準偏差、%)
        out["move1w"] = _r(g("^VIX") / math.sqrt(52), 2)
    return out


# ======================================================================
# 3. 大口の持ち高(CFTC 金融先物の建玉、毎週)
# ======================================================================
CFTC_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
COT_MARKETS = [
    ("sp", "S&P 500先物(E-mini)", "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE"),
    ("ndx", "ナスダック100先物", "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE"),
    ("nikkei", "日経平均先物(円建て、シカゴ)", "NIKKEI STOCK AVERAGE YEN DENOM - CHICAGO MERCANTILE EXCHANGE"),
    ("jpy", "円の先物", "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE"),
    ("ust10", "米10年国債の先物", "UST 10Y NOTE - CHICAGO BOARD OF TRADE"),
]


def cot_block(get=_get):
    out = {}
    for key, name, market in COT_MARKETS:
        q = urllib.parse.urlencode({
            "$where": f"market_and_exchange_names='{market}'", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": "160",
            "$select": "report_date_as_yyyy_mm_dd,lev_money_positions_long,lev_money_positions_short,"
                       "asset_mgr_positions_long,asset_mgr_positions_short,open_interest_all"})
        try:
            rows = json.loads(get(f"{CFTC_URL}?{q}"))
        except Exception as e:
            print(f"    [需給 CFTC {key}] 取得失敗 {type(e).__name__}")
            continue
        rows = sorted(rows, key=lambda r: r["report_date_as_yyyy_mm_dd"])
        if len(rows) < 30:
            continue
        num = lambda r, k: float(r.get(k) or 0)   # noqa: E731
        lev = [num(r, "lev_money_positions_long") - num(r, "lev_money_positions_short") for r in rows]
        am = [num(r, "asset_mgr_positions_long") - num(r, "asset_mgr_positions_short") for r in rows]
        oi = num(rows[-1], "open_interest_all")

        def idx(xs):   # 過去3年の最小〜最大のどこにいるか(0=最も売り越し、100=最も買い越し)
            lo, hi = min(xs), max(xs)
            return round((xs[-1] - lo) / (hi - lo) * 100) if hi > lo else 50
        out[key] = {"name": name, "date": rows[-1]["report_date_as_yyyy_mm_dd"][:10], "weeks": len(rows),
                    "lev_net": int(lev[-1]), "lev_chg": int(lev[-1] - lev[-2]), "lev_idx": idx(lev),
                    "am_net": int(am[-1]), "am_chg": int(am[-1] - am[-2]), "am_idx": idx(am),
                    "lev_pct_oi": _r(lev[-1] / oi * 100, 1) if oi else None}
    return out


# ======================================================================
# 4. 日本の主体別の売買と信用残(JPX、毎週)
# ======================================================================
JPX = "https://www.jpx.co.jp"
# 投資部門別売買状況のシート(東証プライム・金額の行)の列 → 主体の差引(売り越しはマイナス)。単位は千円
INVESTOR_COLS = {"海外投資家": ("V", "Z"), "個人": ("N", "R"), "信託銀行": ("BB",), "事業法人": ("AL",),
                 "投資信託": ("AH",), "生保・損保": ("AT",), "都銀・地銀等": ("AX",), "証券会社(自己)": ("F", "J")}


def xlsx_rows(b):
    """標準ライブラリだけでxlsxの1枚目を読む。{行番号: {列: 値}}"""
    z = zipfile.ZipFile(io.BytesIO(b))
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        x = z.read("xl/sharedStrings.xml").decode("utf-8")
        ss = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<si>(.*?)</si>", x, re.S)]
    sh = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    rows = {}
    for rn, body in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', sh, re.S):
        cells = {}
        for m in re.finditer(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', body, re.S):
            col, attr, inner = m.groups()
            v = re.search(r"<v>(.*?)</v>", inner or "")
            v = v.group(1) if v else ""
            if 't="s"' in attr and v:
                v = ss[int(v)]
            if v != "":
                cells[col] = v
        rows[int(rn)] = cells
    return rows


def parse_investor(b, fname):
    rows = xlsx_rows(b)
    m = re.search(r"_(\d{8})_(\d{8})\.xlsx", fname)
    keys = sorted(rows)
    for i, k in enumerate(keys):
        if "プライム" in rows[k].get("B", "") and i + 1 < len(keys):
            val = rows[keys[i + 1]]
            if "金額" not in val.get("C", ""):
                continue
            out = {"from": m.group(1), "to": m.group(2)} if m else {}
            for name, cols in INVESTOR_COLS.items():
                try:
                    out[name] = round(sum(float(val[c]) for c in cols) / 1e5)   # 千円 → 億円
                except (KeyError, ValueError):
                    out[name] = None
            return out
    raise ValueError("東証プライムの金額の行が見つからない")


def parse_margin(b, fname):
    rows = xlsx_rows(b)
    m = re.search(r"(\d{8})_mtcurrent", fname)
    for k in sorted(rows):
        r = rows[k]
        if "信用取引残高合計" in r.get("B", "") or "Total Outstanding" in r.get("B", ""):
            val = rows.get(k + 1, {})
            if "金額" in val.get("D", "") or "Val" in val.get("D", ""):
                sell, sell_chg, buy, buy_chg = (float(val[c]) for c in ("E", "F", "G", "H"))
                return {"date": m.group(1) if m else "", "buy": round(buy / 100), "buy_chg": round(buy_chg / 100),
                        "sell": round(sell / 100), "sell_chg": round(sell_chg / 100), "ratio": _r(buy / sell)}   # 百万円 → 億円
    raise ValueError("信用取引残高合計の行が見つからない")


def jpx_block(prev=None, get=_get):
    prev = prev or {}
    inv = {x["to"]: x for x in prev.get("investor_hist") or [] if isinstance(x, dict) and x.get("to")}
    mar = {x["date"]: x for x in prev.get("margin_hist") or [] if isinstance(x, dict) and x.get("date")}
    try:
        h = get(f"{JPX}/markets/statistics-equities/investor-type/index.html").decode("utf-8", "ignore")
        for path in re.findall(r'href="([^"]+stock_1_w_\d{8}_\d{8}\.xlsx)"', h)[:6]:
            to = re.search(r"_(\d{8})\.xlsx", path).group(1)
            if to in inv:
                continue
            try:
                inv[to] = parse_investor(get(JPX + path), path)
            except Exception as e:
                print(f"    [需給 JPX 投資部門別 {to}] 読めない {type(e).__name__}: {e}")
    except Exception as e:
        print(f"    [需給 JPX 投資部門別] 取得失敗 {type(e).__name__}")
    try:
        h = get(f"{JPX}/markets/statistics-equities/margin/04.html").decode("utf-8", "ignore")
        for path in re.findall(r'href="([^"]+_mtcurrent\.xlsx)"', h)[:4]:
            d = re.search(r"(\d{8})_mtcurrent", path).group(1)
            if d in mar:
                continue
            try:
                mar[d] = parse_margin(get(JPX + path), path)
            except Exception as e:
                print(f"    [需給 JPX 信用残 {d}] 読めない {type(e).__name__}: {e}")
    except Exception as e:
        print(f"    [需給 JPX 信用残] 取得失敗 {type(e).__name__}")
    ih = [inv[k] for k in sorted(inv)][-52:]
    mh = [mar[k] for k in sorted(mar)][-104:]
    out = {"investor_hist": ih, "margin_hist": mh}
    if ih:
        out["investor"] = ih[-1]
        for name in ("海外投資家", "個人", "信託銀行", "事業法人"):
            xs = [x.get(name) for x in ih[-4:] if x.get(name) is not None]
            out.setdefault("investor_4w", {})[name] = sum(xs) if len(xs) == min(4, len(ih)) else None
    if mh:
        out["margin"] = mh[-1]
    return out


# ======================================================================
# 5. 需給の日程
# ======================================================================
def _nth_fri(y, m, n):
    d = date(y, m, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def calendar_block(today):
    """今日(日本時間の日付)から先の需給のイベント"""
    dd = _dd()
    ev = []
    for k in range(0, 3):
        y, m = today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1
        opex = _nth_fri(y, m, 3)
        while not dd.us_trading_day(opex):
            opex -= timedelta(days=1)
        q = m in (3, 6, 9, 12)
        ev.append({"date": opex.isoformat(), "what": "米国 " + ("クアドルプル・ウィッチング(四半期の先物・オプション同時満期)" if q else "月次オプションの満期"),
                   "why": "満期の前後は、オプションの売り手のヘッジの売買で値動きが抑えられたり、満期後に動きやすくなったりする" + ("。四半期末は指数の入れ替えも重なり出来高が膨らむ" if q else "")})
        sq = _nth_fri(y, m, 2)
        ev.append({"date": sq.isoformat(), "what": "日本 " + ("メジャーSQ(先物・オプションの特別清算)" if q else "ミニSQ(オプションの特別清算)"),
                   "why": "SQ値の算出に向けた裁定取引の解消・持ち越しで、前日から当日の寄り付きに売買が集中しやすい(祝日なら前営業日)"})
        last = date(y, m, 28) + timedelta(days=4)
        last = last - timedelta(days=last.day)
        while not dd.us_trading_day(last):
            last -= timedelta(days=1)
        ev.append({"date": last.isoformat(), "what": ("四半期末" if q else "月末") + "のリバランス",
                   "why": "年金などが株と債券の比率を元に戻す売買。株が大きく上がった月末は売り、下がった月末は買いが出やすい"})
    ev = sorted([e for e in ev if e["date"] >= today.isoformat()], key=lambda e: e["date"])[:6]
    for e in ev:
        e["days"] = (date.fromisoformat(e["date"]) - today).days
    return ev


# ======================================================================
# 6. 戦略: 投資比率の規則と、その過去20年の検証
# ======================================================================
# 2026-11-26 の検証(S&P 500・日経平均、2007〜2026、前半・後半に分けて確認):
#   トレンド・売り抜けの日・VIXの期間構造などを組み合わせた毎日の規則は、判定の変更が年18〜46回と多く、
#   米国では前半・後半とも持ち続けに負けた(シャープ 0.10〜0.68)。
#   「月末の終値が200日平均の上なら投資、下なら待機」(M.フェイバー、2007年に公表された規則のまま)は、
#   全体で S&P 500 年率7.8%(持ち続け8.6%)・最大下落−24.8%(−55.4%)・シャープ0.67(0.51)、
#   日経平均 年率6.0%(7.4%)・最大下落−32.8%(−54.9%)・シャープ0.42(0.42)で、両市場・両期間で
#   最大の下落を大きく減らした。判定の変更は年1〜2回。数値は当てはめで調整していない。
#   売り抜けの日・VIXなどは投資比率の切り替えには向かなかったため、「注意の度合い」として別に出す。
def _month_end_idx(days):
    """各月の最後の取引日の位置"""
    out = []
    for i in range(len(days) - 1):
        if days[i][:7] != days[i + 1][:7]:
            out.append(i)
    return out


def trend_rule(closes, days, i_last=None):
    """月末の判定: 直近の月末の終値が200日平均の上なら100(投資)、下なら0(待機)"""
    i_last = len(closes) - 1 if i_last is None else i_last
    ends = [i for i in _month_end_idx(days[:i_last + 1]) if i >= 199]
    if not ends:
        return None
    i = ends[-1]
    s200 = sum(closes[i - 199:i + 1]) / 200
    return {"position": 100 if closes[i] > s200 else 0, "decided": days[i], "close_me": _r(closes[i]), "sma200_me": _r(s200)}


def backtest(rows, irx=None, start=None, end=None):
    """月末の200日平均の規則で運用した場合と、持ち続けた場合の比較。月末の終値で決め、翌営業日からの値動きに適用。
    待機資金は3か月国債の利回り(あれば)、売買コストは切り替えのたび0.1%"""
    days = [r[0] for r in rows]
    closes = [r[4] for r in rows]
    ends = set(_month_end_idx(days))
    ir = dict(irx or [])
    eq_s = eq_b = peak_s = peak_b = 1.0
    mdd_s = mdd_b = 0.0
    rs, rb = [], []
    pos, last_ir, changes, first, last_day = None, 0.0, 0, None, None
    for i in range(200, len(rows) - 1):
        if (start and days[i] < start) or (end and days[i] >= end):
            continue
        if pos is None or i in ends:
            new = 100 if closes[i] > sum(closes[i - 199:i + 1]) / 200 else 0
            if pos is not None and new != pos:
                changes += 1
            cost = 0.001 if (pos is not None and new != pos) else 0.0
            pos = new
        else:
            cost = 0.0
        first = first or days[i]
        last_day = days[i]
        last_ir = ir.get(days[i], last_ir)
        ret = closes[i + 1] / closes[i] - 1
        r_s = pos / 100 * ret + (1 - pos / 100) * (last_ir / 100 / 252) - cost
        eq_s *= 1 + r_s
        eq_b *= 1 + ret
        peak_s, peak_b = max(peak_s, eq_s), max(peak_b, eq_b)
        mdd_s, mdd_b = min(mdd_s, eq_s / peak_s - 1), min(mdd_b, eq_b / peak_b - 1)
        rs.append(r_s)
        rb.append(ret)
    n = len(rs)
    if n < 250:
        return None
    yrs = n / 252

    def stats(eq, r, mdd):
        m = sum(r) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1))
        return {"cagr": _r((eq ** (1 / yrs) - 1) * 100, 1), "mdd": _r(mdd * 100, 1),
                "sharpe": _r(m / sd * math.sqrt(252), 2) if sd else None, "vol": _r(sd * math.sqrt(252) * 100, 1)}
    return {"from": first, "to": last_day, "years": _r(yrs, 1), "rule": stats(eq_s, rs, mdd_s),
            "hold": stats(eq_b, rb, mdd_b), "changes_per_year": _r(changes / yrs, 1)}


def caution(closes, vols, i, vix=None, vix3m=None):
    """注意の度合い(投資比率の切り替えではなく、1回の売買の大きさと損切りの近さの目安)。
    50日線、売り抜けの日、恐怖(VIXの期間構造か実際の変動率)を見る。点数が低いほど注意"""
    c = closes[i]
    s50 = sum(closes[i - 49:i + 1]) / 50
    parts = {"50日線の上か": 1 if c > s50 else -1}
    n_dd = None
    if vols is not None:
        n_dd = 0
        for k in range(i - 24, i + 1):
            if vols[k] and vols[k - 1] and closes[k] / closes[k - 1] - 1 <= -0.002 and vols[k] > vols[k - 1] and c < closes[k] * 1.05:
                n_dd += 1
        parts["売り抜けの日(25日)"] = -1 if n_dd >= 6 else -0.5 if n_dd >= 4 else 0
    if vix is not None and vix3m:
        parts["VIXの期間構造"] = -1 if vix / vix3m > 1 else 0.5 if vix < 16 else 0
    else:
        r = [math.log(closes[k] / closes[k - 1]) for k in range(i - 19, i + 1)]
        m = sum(r) / len(r)
        vol = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1) * 252) * 100
        parts["実際の変動率(20日)"] = -1 if vol > 30 else 0.5 if vol < 15 else 0
    sc = sum(parts.values())
    level = "低い" if sc >= 1 else "ふつう" if sc >= 0 else "高い" if sc >= -1.5 else "非常に高い"
    size = {"低い": "通常の大きさ", "ふつう": "通常の大きさ", "高い": "通常の半分程度", "非常に高い": "新規は見送るか、ごく小さく"}[level]
    return {"score": _r(sc), "level": level, "size": size, "parts": parts, "dist_days": n_dd}


def levels(rows):
    """ATR(14)、移動平均、直近の高値・安値(重要な価格帯)"""
    trs = [max(h - lo, abs(h - rows[k - 1][4]), abs(lo - rows[k - 1][4])) for k, (_, _, h, lo, _, _) in enumerate(rows) if k > 0]
    atr = sum(trs[-14:]) / 14
    closes = [r[4] for r in rows]
    c = closes[-1]
    sma = {n: sum(closes[-n:]) / n for n in (20, 50, 200) if len(closes) >= n}
    return {"close": _r(c), "prev": _r(closes[-2]) if len(closes) > 1 else None, "atr": _r(atr), "atr_pct": _r(atr / c * 100), "sma20": _r(sma.get(20)), "sma50": _r(sma.get(50)),
            "sma200": _r(sma.get(200)), "hi20": _r(max(r[2] for r in rows[-20:])), "lo20": _r(min(r[3] for r in rows[-20:])),
            "hi60": _r(max(r[2] for r in rows[-60:])), "lo60": _r(min(r[3] for r in rows[-60:]))}


def _cut(rows, upto):
    """その市場の確定した取引日まで。出来高0の最後の足(まだ確定していない)も除く"""
    rows = [r for r in rows if not upto or r[0] <= upto]
    while rows and rows[-1][5] == 0 and any(r[5] for r in rows[-30:-1]):
        rows = rows[:-1]
    return rows


def strategy_block(expected, get=ohlcv):
    """米国(S&P 500)と日本(日経平均)の、規則の判定・過去20年の検証・注意の度合い・リスク管理の数値"""
    out = {}
    try:
        vix = dict((r[0], r[4]) for r in get("^VIX", "20y"))
        vix3m = dict((r[0], r[4]) for r in get("^VIX3M", "20y"))
        irx = [(r[0], r[4]) for r in get("^IRX", "20y")]
    except Exception as e:
        print(f"    [戦略 VIX] 取得失敗 {type(e).__name__}")
        vix, vix3m, irx = {}, {}, None
    for key, sym, name, use_vix in (("us", "^GSPC", "S&P 500", True), ("jp", "^N225", "日経平均", False)):
        try:
            rows = _cut(get(sym, "20y"), expected.get(key))
        except Exception as e:
            print(f"    [戦略 {sym}] 取得失敗 {type(e).__name__}")
            continue
        if len(rows) < 600:
            continue
        days = [r[0] for r in rows]
        closes = [r[4] for r in rows]
        vol_ok = sum(1 for r in rows[-260:] if r[5]) >= 240
        i = len(rows) - 1
        rule = trend_rule(closes, days)
        s200 = sum(closes[-200:]) / 200
        now_pos = 100 if closes[-1] > s200 else 0
        bts = {"all": backtest(rows, irx), "first": backtest(rows, irx, end="2017-01-01"), "second": backtest(rows, irx, start="2017-01-01")}
        out[key] = {"name": name, "date": days[-1], "rule": rule, "now_vs_200": _r((closes[-1] / s200 - 1) * 100),
                    "flip_watch": bool(rule and now_pos != rule["position"]),
                    "caution": caution(closes, [r[5] for r in rows] if vol_ok else None, i,
                                       vix.get(days[-1]) if use_vix else None, vix3m.get(days[-1]) if use_vix else None),
                    "backtest": bts, "levels": levels(rows[-260:])}
    return out


# ======================================================================
# まとめ
# ======================================================================
def build(expected_us, today_jst, prev=None, expected_jp=None):
    """需給と戦略をまとめて計算。どれかが取れなくても、取れたものだけで返す"""
    prev = prev or {}
    pf = prev.get("flow") or {}
    t = time.time()
    flow = {"volume": volume_block(expected={"^GSPC": expected_us, "^IXIC": expected_us, "^N225": expected_jp}),
            "options": vol_block(expected_us)}
    pc = putcall_block(expected_us, pf.get("putcall_hist"))
    flow["putcall"] = {k: v for k, v in pc.items() if k != "hist"}
    flow["putcall_hist"] = pc.get("hist", [])[-260:]
    flow["cot"] = cot_block()
    flow.update(jpx_block(pf))
    flow["calendar"] = calendar_block(today_jst)
    strat = strategy_block({"us": expected_us, "jp": expected_jp})
    print(f"  需給と戦略: 出来高{len(flow['volume'])}指数、オプション{len(flow['options'].get('items', {}))}、"
          f"プット・コール{'OK' if pc.get('ok') else '無し'}、建玉{len(flow['cot'])}、"
          f"投資部門別{len(flow.get('investor_hist') or [])}週、信用残{len(flow.get('margin_hist') or [])}週、"
          f"戦略{len(strat)}市場({time.time() - t:.0f}秒)")
    return flow, strat


# ======================================================================
# AIに渡す文章
# ======================================================================
def _f(x, unit="%", sign=True):
    if x is None:
        return "—"
    return (f"{x:+,.2f}" if sign else f"{x:,.2f}") + unit


def position_words(net, chg, idx):
    """持ち高の向きと変化を、読み違えようのない言葉にする(数字の符号だけだとAIが逆に読むことがある)"""
    side = "買い越し" if net > 0 else "売り越し" if net < 0 else "ほぼゼロ"
    if net < 0:
        move = f"売り越しが{abs(chg):,}枚{'拡大(新たな売り)' if chg < 0 else '縮小(買い戻し)'}" if chg else "前週と同じ"
    else:
        move = f"買い越しが{abs(chg):,}枚{'拡大(新たな買い)' if chg > 0 else '縮小(売り)'}" if chg else "前週と同じ"
    where = ("過去3年で最も買い寄りの水準" if idx >= 90 else "過去3年では買い寄り" if idx >= 70 else
             "過去3年で最も売り寄りの水準" if idx <= 10 else "過去3年では売り寄り" if idx <= 30 else "過去3年の中ほど")
    return f"{side} {abs(net):,}枚、前週比で{move}、偏り{idx}({where})"


def rule_sentence(v):
    """規則の判定を、プログラムが決めた文章で(AIに言い換えさせない)"""
    r = v.get("rule") or {}
    inv = r.get("position") == 100
    d = (r.get("decided") or "")[5:].replace("-", "/")
    t = f"{v['name']}: 規則の判定は「{'投資' if inv else '待機'}」({d}の月末に判定)。"
    if v.get("flip_watch"):
        t += f"今は200日平均を{abs(v.get('now_vs_200') or 0):.2f}%{'下回って' if inv else '上回って'}いて、このまま月末を迎えると「{'待機' if inv else '投資'}」に変わる。"
    else:
        t += f"今も200日平均の{'上' if inv else '下'}にあり、判定は変わらない見込み。"
    return t + f"注意の度合いは「{(v.get('caution') or {}).get('level')}」。"


def describe(flow, strat):
    """需給と戦略のデータを、AIに渡す表の文章にする"""
    L = []
    vb = (flow or {}).get("volume") or {}
    if vb:
        L.append("■出来高と市場の状態(オニール流)")
        for s, v in vb.items():
            L.append(f"{v['name']}: {v['phase']}、高値から{_f(v.get('drawdown'))}、直近60日の安値 {v.get('low60')}({v.get('low60_date')})"
                     + (f"、売り抜けの日(25日){v['dist_days']}日" if v.get("dist_days") is not None else "")
                     + (f"、当日の出来高は50日平均の{v['ratio50']}倍" if v.get("ratio50") else "")
                     + (f"、20日の上昇日/下落日の出来高比 {v['updown20']}" if v.get("updown20") else "")
                     + (f"、フォロースルー {v['ftd']['date']} {_f(v['ftd']['chg'])}" if v.get("ftd") else "、フォロースルーはまだ無い"))
    op = (flow or {}).get("options") or {}
    if op.get("items"):
        L.append("■オプション市場")
        L.append("、".join(f"{x['name']} {x['last']}(前日比{_f(x['chg1'], '')}、1年での位置 {x['pct1y']}%)" for x in op["items"].values()))
        if op.get("term"):
            L.append(f"VIX÷VIX3か月 = {op['term']}(1を超えると逆転、目先の恐怖が強い)、VIX9日÷VIX = {op.get('term_short')}")
        if op.get("move1d"):
            L.append(f"オプションが織り込むS&P 500の値動き: 1日 ±{op['move1d']}%、1週間 ±{op['move1w']}%(約68%の確率でこの範囲)")
    pc = (flow or {}).get("putcall") or {}
    if pc.get("ok"):
        L.append(f"■プット・コール比率(CBOE {pc['date']}): 全体 {pc['total']}(10日平均 {pc.get('total10')})、個別株 {pc['equity']}"
                 f"(10日平均 {pc.get('equity10')}、直近の範囲での位置 {pc.get('equity_pct')}%)、指数 {pc['index']}、S&P 500 {pc.get('spx')}")
    cot = (flow or {}).get("cot") or {}
    if cot:
        L.append("■大口の持ち高(CFTC、毎週火曜時点)。偏り=過去3年の最小0〜最大100のどこにいるか。"
                 "注意: 米国債先物のヘッジファンドの売り越しの大半は、現物の国債を買って先物を売る裁定取引(ベーシス取引)で、金利の方向への賭けではない。"
                 "株価指数の先物のヘッジファンドの売り越しも、資産運用会社の買いの相手側やヘッジの売りを含む。方向の判断には前週比と偏りの変化を重視する")
        for k, v in cot.items():
            if k == "ust10":
                continue   # 米国債先物の持ち高は裁定取引が大半で、AIが方向の賭けと読み違えるため渡さない(画面には注記つきで出す)
            L.append(f"{v['name']}({v['date']}): ヘッジファンド等は{position_words(v['lev_net'], v['lev_chg'], v['lev_idx'])}。"
                     f"資産運用会社は{position_words(v['am_net'], v['am_chg'], v['am_idx'])}")
    inv = (flow or {}).get("investor")
    if inv:
        L.append(f"■日本の投資部門別売買(東証プライム、{inv.get('from')}〜{inv.get('to')}、差引、億円): "
                 + "、".join(f"{k} {v:+,}" for k, v in inv.items() if k not in ("from", "to") and v is not None))
        w4 = flow.get("investor_4w") or {}
        L.append("直近4週の合計(億円): " + "、".join(f"{k} {v:+,}" for k, v in w4.items() if v is not None))
    mh = (flow or {}).get("margin_hist") or []
    if mh:
        L.append("■信用取引の残高(二市場、億円): " + " → ".join(f"{m['date']} 買い残{m['buy']:,}・売り残{m['sell']:,}・信用倍率{m['ratio']}" for m in mh[-4:]))
    cal = (flow or {}).get("calendar") or []
    if cal:
        L.append("■需給の日程: " + "、".join(f"{e['date']}(あと{e['days']}日) {e['what']}" for e in cal))
    for key, v in (strat or {}).items():
        r, c, lv, bt = v.get("rule") or {}, v.get("caution") or {}, v.get("levels") or {}, (v.get("backtest") or {}).get("all") or {}
        L.append(f"■戦略({v['name']}): 規則=月末の終値が200日平均の上なら投資、下なら待機。直近の判定({r.get('decided')}) "
                 f"{'投資(100%)' if r.get('position') == 100 else '待機(0%)'}。今の200日平均からの位置 {_f(v.get('now_vs_200'))}"
                 + (f"(このまま月末を迎えると「{'待機' if r.get('position') == 100 else '投資'}」に変わる)" if v.get("flip_watch") else ""))
        L.append(f"  注意の度合い {c.get('level')}(1回の売買の大きさの目安: {c.get('size')})、内訳 {c.get('parts')}")
        L.append(f"  価格帯: 終値 {lv.get('close')}、ATR(14) {lv.get('atr')}({lv.get('atr_pct')}%)、20日線 {lv.get('sma20')}、50日線 {lv.get('sma50')}、"
                 f"200日線 {lv.get('sma200')}、20日の高値 {lv.get('hi20')}・安値 {lv.get('lo20')}、60日の高値 {lv.get('hi60')}・安値 {lv.get('lo60')}")
        if bt:
            h = (v.get("backtest") or {}).get("all", {}).get("hold") or {}
            L.append(f"  規則の過去の成績({bt.get('from')}〜): 年率{bt['rule']['cagr']}%・最大下落{bt['rule']['mdd']}%・シャープ{bt['rule']['sharpe']}"
                     f"(持ち続け 年率{h.get('cagr')}%・最大下落{h.get('mdd')}%・シャープ{h.get('sharpe')})")
    return "\n".join(L)


def numbers(flow, strat):
    """数字の照合に使う、需給と戦略のすべての数値(億円は兆円にも直す)"""
    out = []

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            out.append(float(x))
            if abs(x) >= 1000:
                out.append(float(x) / 10000)   # 億円 → 兆円、枚 → 万枚
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk({k: v for k, v in (flow or {}).items() if k not in ("putcall_hist",)})
    walk(strat)
    # 損切りの目安としてAIが使う、ATRの倍数とその価格(画面の計算と同じ考え方)
    move1d = ((flow or {}).get("options") or {}).get("move1d")
    for v in (strat or {}).values():
        lv = v.get("levels") or {}
        c, atr = lv.get("close"), lv.get("atr")
        if c and atr:
            for k in (1, 1.5, 2, 2.5, 3):
                out += [atr * k, c - atr * k, c + atr * k, lv.get("atr_pct", 0) * k]
        if c and move1d:
            out += [c * move1d / 100, c * (1 - move1d / 100), c * (1 + move1d / 100)]
    return out
