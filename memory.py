"""分析の記録(2026-11-28 Shio「日々分析した結果は蓄積し、蓄積したデータも分析し、構造的に物事を捉え正しい分析ができるように」)

毎回の深掘り分析の要点を learn/data/memory.json に1取引日1件で積み上げ(同じ日の夕方の更新は朝の分を置き換える)、
積み上げた記録を規則で分析して、次の分析(チーフ)と画面に渡す。AIは使わない(Geminiの枠を使わない)。

記録から読むもの
- 続いている構造: 動きの型の首位が何日続いているか、直近20件での型の割合、テーマ(AI・金利・インフレ…)の出現の増減
- 主導役の持続: 上位・下位に何度も入る業種(一時的な入れ替えか、続く流れか)
- 前回から変わったこと: 動きの型・規則の判定・注意の度合い・恐怖の水準・期間構造・主導役・予想
- 型ごとの予想の成績(答え合わせの記録と日付で結ぶ)
"""
import json
import re

MEM_PATH = "learn/data/memory.json"
KEEP = 750          # 約3年分
THEMES = [          # 見出し・根本の原因・主因の文に出る言葉で数える
    ("AI・半導体", r"AI|人工知能|半導体|エヌビディア|NVIDIA|生成"),
    ("金利", r"金利|利回り|国債|イールド"),
    ("インフレ", r"インフレ|物価|CPI|PCE"),
    ("中央銀行", r"FRB|FOMC|利下げ|利上げ|日銀|パウエル"),
    ("円・為替", r"円安|円高|ドル円|為替|キャリー"),
    ("原油・中東", r"原油|中東|イラン|OPEC|エネルギー価格"),
    ("関税・貿易", r"関税|貿易|輸出規制"),
    ("景気", r"景気|雇用|失業|GDP|リセッション|成長不安"),
    ("決算", r"決算|業績|ガイダンス|EPS"),
    ("需給・持ち高", r"需給|持ち高|ポジション|リバランス|SQ|裁定|巻き戻し"),
    ("過熱・バブル", r"過熱|バブル|割高|行き過ぎ"),
]


def empty():
    return {"version": 1, "records": []}


def load(get_file):
    try:
        _, body = get_file(MEM_PATH)
        d = json.loads((body or b"{}").decode("utf-8"))
        if isinstance(d, dict) and isinstance(d.get("records"), list):
            return d
    except Exception as e:
        print(f"  [WARN] 分析の記録を読めない(新しく始める): {type(e).__name__}: {e}")
    return empty()


def _r(x, d=2):
    return round(x, d) if isinstance(x, (int, float)) else None


def snapshot(res):
    """深掘り分析の結果から、記録に残す要点を取り出す"""
    ai = res.get("ai") or {}
    c = ai.get("chief") or {}
    F = res.get("features") or {}
    S = res.get("strategy") or {}
    fl = res.get("flow") or {}
    st = res.get("structure") or {}

    def sec(g):
        xs = sorted([f for f in F.values() if f.get("group") == g and f.get("c1") is not None], key=lambda f: -f["c1"])
        return {"top": [[f["name"], _r(f["c1"])] for f in xs[:3]], "bottom": [[f["name"], _r(f["c1"])] for f in xs[-3:][::-1]]}

    def idx(k):
        f = F.get(k) or {}
        return {"last": _r(f.get("last")), "c1": _r(f.get("c1")), "c5": _r(f.get("c5")), "c20": _r(f.get("c20"))}
    op = fl.get("options") or {}
    vix = (op.get("items") or {}).get("^VIX") or {}
    pc = fl.get("putcall") or {}
    inv = fl.get("investor") or {}
    vb = fl.get("volume") or {}
    rec = {
        "date": (res.get("asof") or {}).get("us"), "jp": (res.get("asof") or {}).get("jp"), "updated": res.get("updated"),
        "ai": bool(ai.get("ok")) and not ai.get("reused_from"),
        "headline": c.get("headline") or "", "confidence": c.get("confidence"),
        "root": (c.get("root_cause") or {}).get("summary") or "",
        "causes": {m: [[x.get("title"), x.get("weight")] for x in ((c.get(m) or {}).get("causes") or [])[:3]] for m in ("us", "jp")},
        "dir": {m: (c.get(m) or {}).get("direction") for m in ("us", "jp")},
        "forecast": {m: (v or {}).get("dir") for m, v in (c.get("forecast") or {}).items()},
        "types": [[t.get("type"), t.get("share")] for t in (st.get("types") or [])[:3]],
        "sectors": {"us": sec("us"), "jp": sec("jp")},
        "idx": {"spy": idx("SPY"), "n225": idx("^N225"), "tnx": idx("^TNX"), "jpy": idx("JPY=X")},
        "vix": {"last": vix.get("last"), "pct1y": vix.get("pct1y"), "term": op.get("term")},
        "putcall": pc.get("equity") if pc.get("ok") else None,
        "dist_days": {v.get("name"): v.get("dist_days") for v in vb.values()},
        "foreign": inv.get("海外投資家"),
        "rule": {k: {"pos": (v.get("rule") or {}).get("position"), "caution": (v.get("caution") or {}).get("level"),
                     "vs200": _r(v.get("now_vs_200"))} for k, v in S.items()},
    }
    return rec


def upsert(mem, rec):
    """1取引日1件。同じ米国の取引日の記録は新しい方(夕方の更新など)で置き換える。AIが失敗した回は、前の記録の文を残す"""
    if not rec.get("date"):
        return False
    rs = [r for r in mem["records"] if r.get("date") != rec["date"]]
    old = next((r for r in mem["records"] if r.get("date") == rec["date"]), None)
    if old and not rec.get("ai") and old.get("ai"):
        for k in ("headline", "root", "causes", "dir", "forecast", "confidence"):
            rec[k] = old.get(k)
        rec["ai"] = True
    rs.append(rec)
    mem["records"] = sorted(rs, key=lambda r: r["date"])[-KEEP:]
    return True


def _top_type(r):
    return (r.get("types") or [[None]])[0][0]


def _text(r):
    return " ".join([r.get("headline") or "", r.get("root") or ""] + [x[0] or "" for m in ("us", "jp") for x in (r.get("causes") or {}).get(m) or []])


def analyze(mem, track=None):
    """記録を分析する(AIを使わない)。画面とチーフに渡す"""
    rs = [r for r in mem.get("records") or [] if r.get("date")]
    out = {"n": len(rs), "from": rs[0]["date"] if rs else None, "to": rs[-1]["date"] if rs else None}
    if not rs:
        return out
    cur = rs[-1]
    # 1. 動きの型の首位が何日続いているか、直近20件の割合
    tt = _top_type(cur)
    streak = 0
    for r in reversed(rs):
        if _top_type(r) == tt and tt:
            streak += 1
        else:
            break
    last20 = rs[-20:]
    cnt = {}
    for r in last20:
        for t, sh in r.get("types") or []:
            if t:
                cnt.setdefault(t, []).append(sh or 0)
    out["type_now"] = {"type": tt, "streak": streak}
    out["types20"] = sorted([{"type": t, "days": len(v), "avg": round(sum(v) / len(last20))} for t, v in cnt.items()],
                            key=lambda x: -x["avg"])[:5]
    # 2. テーマの出現: 直近10件と、その前の10件
    def theme_count(xs):
        return {name: sum(1 for r in xs if re.search(pat, _text(r))) for name, pat in THEMES}
    a, b = theme_count(rs[-10:]), theme_count(rs[-20:-10])
    nb = len(rs[-20:-10])
    th = []
    for name, _ in THEMES:
        if a[name] or b[name]:
            trend = "新しく出た" if nb and not b[name] and a[name] else "増えている" if nb and a[name] > b[name] else \
                "減っている" if nb and a[name] < b[name] else "続いている" if a[name] else "消えた"
            th.append({"theme": name, "recent": a[name], "before": b[name], "n_recent": len(rs[-10:]), "trend": trend if nb else "記録が少ない"})
    out["themes"] = sorted(th, key=lambda x: (-x["recent"], x["theme"]))
    # 3. 主導役の持続: 直近10件で上位3・下位3に入った回数
    lead = {}
    for g in ("us", "jp"):
        top, bot = {}, {}
        for r in rs[-10:]:
            s = (r.get("sectors") or {}).get(g) or {}
            for n, _ in s.get("top") or []:
                top[n] = top.get(n, 0) + 1
            for n, _ in s.get("bottom") or []:
                bot[n] = bot.get(n, 0) + 1
        lead[g] = {"top": sorted(top.items(), key=lambda x: -x[1])[:3], "bottom": sorted(bot.items(), key=lambda x: -x[1])[:3]}
    out["leaders"] = lead
    # 4. 前回から変わったこと
    ch = []
    if len(rs) >= 2:
        p = rs[-2]
        if _top_type(p) != tt:
            ch.append(f"動きの型の首位が「{_top_type(p) or 'なし'}」から「{tt or 'なし'}」に変わった")
        for k, v in (cur.get("rule") or {}).items():
            pv = (p.get("rule") or {}).get(k) or {}
            name = {"us": "S&P 500", "jp": "日経平均"}.get(k, k)
            if pv.get("pos") is not None and pv.get("pos") != v.get("pos"):
                ch.append(f"{name}の月末の規則が「{'投資' if pv.get('pos') == 100 else '待機'}」から「{'投資' if v.get('pos') == 100 else '待機'}」に変わった")
            if pv.get("caution") and pv.get("caution") != v.get("caution"):
                ch.append(f"{name}の注意の度合いが「{pv.get('caution')}」から「{v.get('caution')}」に変わった")
        pvx, cvx = p.get("vix") or {}, cur.get("vix") or {}
        if pvx.get("term") and cvx.get("term") and (pvx["term"] > 1) != (cvx["term"] > 1):
            ch.append("VIXの期間構造が" + ("逆転した(目先の恐怖が強まった)" if cvx["term"] > 1 else "順に戻った(目先の恐怖が和らいだ)"))
        for lo, hi in ((pvx.get("pct1y"), cvx.get("pct1y")),):
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                if lo < 80 <= hi:
                    ch.append("VIXが1年の80%の位置を超えた(恐怖が高い水準に入った)")
                elif hi < 80 <= lo:
                    ch.append("VIXが1年の80%の位置を下回った")
        for g, nm in (("us", "米国"), ("jp", "日本")):
            pt = [x[0] for x in ((p.get("sectors") or {}).get(g) or {}).get("top") or []]
            ct = [x[0] for x in ((cur.get("sectors") or {}).get(g) or {}).get("top") or []]
            if pt and ct and pt[0] != ct[0]:
                ch.append(f"{nm}の首位の業種が「{pt[0]}」から「{ct[0]}」に入れ替わった")
        for m, nm in (("us", "S&P 500"), ("jp", "日経平均")):
            pf, cf = (p.get("forecast") or {}).get(m), (cur.get("forecast") or {}).get(m)
            if pf and cf and pf != cf:
                ch.append(f"{nm}の5営業日の予想が「{pf}」から「{cf}」に変わった")
    out["changes"] = ch
    out["prev_date"] = rs[-2]["date"] if len(rs) >= 2 else None
    # 5. 規則・注意の度合いが今の状態になってから何件続いているか
    reg = {}
    for k in (cur.get("rule") or {}):
        n = 0
        for r in reversed(rs):
            v = (r.get("rule") or {}).get(k) or {}
            if v.get("pos") == cur["rule"][k].get("pos") and v.get("caution") == cur["rule"][k].get("caution"):
                n += 1
            else:
                break
        reg[k] = n
    out["regime_days"] = reg
    # 6. 型ごとの予想の成績(答え合わせの記録と、予想を出した日で結ぶ)
    if track:
        by_date = {r["date"]: _top_type(r) for r in rs}
        acc = {}
        for it in track.get("items") or []:
            if it.get("status") != "evaluated":
                continue
            t = by_date.get(it.get("base_date"))
            if not t:
                continue
            a2 = acc.setdefault(t, {"n": 0, "hit": 0})
            a2["n"] += 1
            a2["hit"] += 1 if it.get("hit") else 0
        out["by_type"] = [{"type": t, "n": v["n"], "hit": v["hit"], "pct": round(v["hit"] * 100 / v["n"])} for t, v in acc.items()]
    # 7. 時系列(画面の一覧とチーフ用。新しい順に14件)
    out["timeline"] = [{"date": r["date"], "headline": r.get("headline"), "type": _top_type(r), "dir": r.get("dir"),
                        "forecast": r.get("forecast"), "spy_c1": ((r.get("idx") or {}).get("spy") or {}).get("c1"),
                        "n225_c1": ((r.get("idx") or {}).get("n225") or {}).get("c1"), "vix": (r.get("vix") or {}).get("last")}
                       for r in rs[-14:][::-1]]
    return out


def context(mem, upto=None):
    """チーフに渡す文: これまでの分析の記録(今回の分は含めない)と、そこから読める続いている構造"""
    rs = [r for r in mem.get("records") or [] if r.get("date") and (upto is None or r["date"] < upto)]
    if not rs:
        return ("■これまでの分析の記録\nまだ記録がありません(今回から積み上げる)。continuity には「記録の始まり」と書き、"
                "今回の構造の見立てを、次回以降に確かめられる形(何が続けば構造的、何が変われば一時的か)で書く。")
    a = analyze({"records": rs})
    L = [f"■これまでの分析の記録(直近{min(len(rs), 10)}件、新しい順。記録は全{len(rs)}件 {a['from']}〜{a['to']})"]
    for t in a["timeline"][:10]:
        g = lambda d, k: (d or {}).get(k) or "なし"   # noqa: E731
        L.append(f"- {t['date']}: 「{t['headline'] or '(見出しなし)'}」 型={t['type'] or 'なし'} 方向 米{g(t['dir'], 'us')}・日{g(t['dir'], 'jp')}"
                 f" 予想 米{g(t['forecast'], 'us')}・日{g(t['forecast'], 'jp')}")
    tn = a.get("type_now") or {}
    if tn.get("type"):
        L.append(f"■続いている構造: 前回までの動きの型の首位「{tn['type']}」は{tn['streak']}件続いている。"
                 + ("直近20件の型の割合: " + "、".join(f"{x['type']} 平均{x['avg']}%({x['days']}件)" for x in a.get("types20") or []) if a.get("types20") else ""))
    th = [x for x in a.get("themes") or [] if x["recent"]]
    if th:
        L.append("■テーマの出現(直近10件の見出し・根本の原因・主因のうち何件に出たか): "
                 + "、".join(f"{x['theme']} {x['recent']}/{x['n_recent']}件({x['trend']})" for x in th[:6]))
    for g, nm in (("us", "米国"), ("jp", "日本")):
        ld = (a.get("leaders") or {}).get(g) or {}
        if ld.get("top"):
            L.append(f"■{nm}の主導役(直近10件で上位3に入った回数): " + "、".join(f"{n} {k}回" for n, k in ld["top"])
                     + " / 下位3: " + "、".join(f"{n} {k}回" for n, k in ld.get("bottom") or []))
    L.append("■記録の使い方: 今日のデータと上の記録を比べ、continuity に (1) 前回までと比べて続いていること・変わったこと、"
             "(2) 続いている流れは構造的(下地が残っている)か一時的(きっかけが消えれば戻る)かの判断と根拠、"
             "(3) 前回の見立てが外れつつあるならその理由、を3〜5文で書く。記録の数字や日付をそのまま繰り返さず、意味を書く")
    return "\n".join(L)
