"""見立ての答え合わせ(2026-11-27 Shio「分析の結果を裏で保存し、実際の動きと一致したかを蓄積。理由も考察して今後の分析に活かす」)

流れ(毎回の深掘り分析の中で動く。失敗しても分析は止めない)
1. evaluate: 判定待ちの予想のうち、5営業日たったものを実際の終値(米国はS&P 500指数、日本は日経平均)で採点する。
   その5日間に何が動いたか(金利・VIX・ドル円・原油・業種の上位と下位)もデータで残す
2. reflect: 採点したものについて、なぜ当たった・外れたかをAIが考察し、次に活かす教訓を1文で残す(1回の実行で最大2件)
3. context: 成績・直近の結果・教訓をチーフアナリストに渡し、同じ読み違いを繰り返さないようにする
4. record: 今回のチーフの予想(次の5営業日の方向と根拠)を保存する

採点: 5営業日後の終値の騰落が、もみ合いの幅(ふだんの1日の値動き × √5 × 0.25)を超えて上なら「上昇」、下なら「下落」、
その内側なら「もみ合い」。予想の方向と同じなら的中。保存先は learn/data/track.json(アプリの「答え合わせ」画面が読む)
"""
import json
import math

TRACK_PATH = "learn/data/track.json"
HORIZON = 5            # 何営業日後で採点するか
FLAT_K = 0.25          # もみ合いの幅の係数
MAX_REFLECT = 2        # 1回の実行で考察をAIに頼む数(Geminiの1日の枠のため)
KEEP = 600             # 残す件数(米日で約1年分)
MKTS = {"us": ("^GSPC", "S&P 500"), "jp": ("^N225", "日経平均")}
DIRS = ("上昇", "下落", "もみ合い")

REFLECT_SCHEMA = {"type": "OBJECT", "properties": {
    "kind": {"type": "STRING", "enum": ["根拠どおりに的中", "別の理由で的中", "方向の読み違い", "動きの大きさの読み違い", "想定外の出来事"]},
    "why": {"type": "STRING"}, "missed": {"type": "ARRAY", "items": {"type": "STRING"}}, "lesson": {"type": "STRING"}},
    "required": ["kind", "why", "lesson"]}


def _r(x, nd=2):
    return None if x is None else round(x, nd)


def empty():
    return {"version": 1, "horizon": HORIZON, "items": [], "summary": {}}


def load(get_file):
    """GitHubの learn/data/track.json を読む。無ければ空"""
    try:
        _, b = get_file(TRACK_PATH)
        t = json.loads(b.decode("utf-8")) if b else None
        return t if isinstance(t, dict) and isinstance(t.get("items"), list) else empty()
    except Exception as e:
        print(f"  [WARN] 答え合わせの記録を読めない(空から始める): {type(e).__name__}")
        return empty()


def daily_sd(rows, n=60):
    """直近n日の1日の騰落率(%)のばらつき"""
    v = [x for _, x in rows[-n - 1:]]
    r = [(b / a - 1) * 100 for a, b in zip(v, v[1:]) if a]
    if len(r) < 20:
        return None
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1))


def band(sd):
    return _r(FLAT_K * sd * math.sqrt(HORIZON)) if sd else None


def bands(closes):
    return {m: band(daily_sd(closes.get(m) or [])) for m in MKTS}


def classify(ret, b):
    if ret is None or b is None:
        return None
    return "上昇" if ret > b else "下落" if ret < -b else "もみ合い"


def _at(rows, d):
    """d 以前で最も新しい値"""
    v = None
    for day, x in rows:
        if day > d:
            break
        v = x
    return v


def window_facts(rows, names, d0, d1, groups):
    """d0 → d1 の間に何が動いたか(採点の考察の材料)。rows は deep_dive の騰落用の行"""
    def chg(sym, bp=False):
        r = rows.get(sym) or []
        a, b = _at(r, d0), _at(r, d1)
        if a is None or b is None:
            return None
        return _r((b - a) * 100, 0) if bp else _r((b / a - 1) * 100) if a else None
    out = {"S&P 500(SPY)": chg("SPY"), "日経平均": chg("^N225"), "米10年債利回り(bp)": chg("^TNX", True),
           "VIX": chg("^VIX"), "ドル円": chg("JPY=X"), "WTI原油": chg("CL=F"), "ハイイールド債": chg("HYG"),
           "均等加重−時価総額加重": None}
    rsp, spy = chg("RSP"), chg("SPY")
    if rsp is not None and spy is not None:
        out["均等加重−時価総額加重"] = _r(rsp - spy)
    for g, label in (("us", "米国の業種"), ("jp", "日本の業種")):
        xs = [(names.get(s, s), chg(s)) for s in groups.get(g, [])]
        xs = sorted([x for x in xs if x[1] is not None], key=lambda x: -x[1])
        if xs:
            out[label + "(上位)"] = [f"{n} {v:+.2f}%" for n, v in xs[:2]]
            out[label + "(下位)"] = [f"{n} {v:+.2f}%" for n, v in xs[-2:]]
    return {k: v for k, v in out.items() if v is not None}


def evaluate(track, closes, rows, names, groups):
    """判定待ちのうち、HORIZON営業日たったものを採点する。返り値は採点した件数"""
    n = 0
    for it in track["items"]:
        if it.get("status") != "pending":
            continue
        r = closes.get(it["market"]) or []
        days = [d for d, _ in r]
        if it["base_date"] not in days:
            continue
        i = days.index(it["base_date"])
        if len(r) - 1 < i + HORIZON:
            it["remaining"] = i + HORIZON - (len(r) - 1)
            continue
        base, end = r[i][1], r[i + HORIZON][1]
        ret5 = (end / base - 1) * 100
        it.update({"status": "evaluated", "eval_date": r[i + HORIZON][0], "ret1": _r((r[i + 1][1] / base - 1) * 100),
                   "ret5": _r(ret5), "end_close": _r(end), "actual": classify(ret5, it.get("band"))})
        it["hit"] = it["actual"] == it["dir"]
        it["facts"] = window_facts(rows, names, it["base_date"], it["eval_date"], groups)
        it.pop("remaining", None)
        n += 1
    return n


def _reflect_prompt(it):
    nm = MKTS[it["market"]][1]
    return f"""あなたは株式アナリストのチームの振り返り担当。過去の見立てを、実際の値動きのデータと照らして振り返る。
推測で数字を作らない。数字は下の『その5営業日に動いたもの』と『結果』にあるものだけを使う。日本語で簡潔に。

■見立て({it['made'][:10]}、{nm}、{it['base_date']}の終値から{HORIZON}営業日)
予想: {it['dir']}(もみ合いの幅 ±{it.get('band')}%) 確信度: {it.get('confidence', '')}
根拠: {it.get('reason', '')}
その日の見出し: {it.get('headline', '')}
その日の根本の原因: {it.get('root', '')}

■結果
{it['eval_date']}の終値まで {it['ret5']:+.2f}%(翌日 {it.get('ret1', 0):+.2f}%) → 実際は「{it['actual']}」、判定: {'的中' if it['hit'] else '外れ'}

■その5営業日に動いたもの(%、利回りはbp)
{json.dumps(it.get('facts', {}), ensure_ascii=False)}

出力(JSON):
- kind: 根拠どおりに的中 / 別の理由で的中 / 方向の読み違い / 動きの大きさの読み違い(方向は合っていたが幅を読み違えた・もみ合いと読んだが動いた等) / 想定外の出来事
- why: なぜその結果になったか(2〜3文)。根拠に挙げた要因が実際に効いたか、効かなかったなら何が値動きを決めたかをデータで示す
- missed: 見落としていた点(0〜3個、各30字以内。的中なら空でよい)
- lesson: 次の分析で使う教訓を1文(60字以内)。「〜の時は〜を重く見る」のように、次に同じ状況が来た時に使える形で。一般論で終わらせない"""


def fallback_reason(it):
    """AIが使えない時の、データだけの振り返り"""
    f = it.get("facts", {})
    parts = [f"{k} {v:+}" for k, v in f.items() if isinstance(v, (int, float))][:5]
    return ("その5営業日の動き: " + "、".join(parts) + "。") if parts else ""


def reflect(track, ask, limit=MAX_REFLECT):
    """採点済みで考察の無いものを、新しい順に最大 limit 件考察する。AIが失敗したら次の実行に回す"""
    todo = [it for it in track["items"] if it.get("status") == "evaluated" and not it.get("reflection")]
    done = 0
    for it in sorted(todo, key=lambda x: x["eval_date"], reverse=True)[:limit]:
        try:
            r = ask(_reflect_prompt(it), REFLECT_SCHEMA, f"答え合わせの考察 {it['market']} {it['base_date']}")
        except Exception as e:
            print(f"  [WARN] 答え合わせの考察に失敗({type(e).__name__})。次の実行でやり直す")
            it["reflection_fallback"] = fallback_reason(it)
            break   # 枠が尽きている可能性が高いので、残りも次に回す
        it["reflection"] = {"kind": str(r.get("kind", ""))[:20], "why": str(r.get("why", ""))[:400],
                            "missed": [str(x)[:60] for x in (r.get("missed") or [])[:3]], "lesson": str(r.get("lesson", ""))[:120]}
        it.pop("reflection_fallback", None)
        done += 1
    return done


def record(track, res, closes, bnds):
    """今回のチーフの予想を保存する。同じ市場・同じ基準日の判定待ちは新しい方で置き換える。
    AIの見解を前回から使い回した時(reused_from)は、その日に保存済みなので保存しない"""
    ai = res.get("ai") or {}
    c = ai.get("chief") or {}
    fc = c.get("forecast") or {}
    if not ai.get("ok") or ai.get("reused_from") or not fc:
        return 0
    n = 0
    for m in MKTS:
        f = fc.get(m) or {}
        d = (res.get("asof") or {}).get(m)
        r = closes.get(m) or []
        if f.get("dir") not in DIRS or not d or not r or r[-1][0] != d:
            continue
        key = f"{m}:{d}"
        old = next((x for x in track["items"] if x.get("id") == key), None)
        if old and old.get("status") != "pending":
            continue
        it = {"id": key, "market": m, "base_date": d, "base_close": _r(r[-1][1]), "made": res.get("updated", ""),
              "dir": f["dir"], "reason": f.get("reason", ""), "confidence": c.get("confidence", ""), "band": bnds.get(m),
              "headline": c.get("headline", ""), "root": (c.get("root_cause") or {}).get("summary", ""), "status": "pending"}
        if old:
            old.clear()
            old.update(it)
        else:
            track["items"].append(it)
        n += 1
    track["items"] = sorted(track["items"], key=lambda x: (x["base_date"], x["market"]))[-KEEP:]
    return n


def summary(track):
    ev = [x for x in track["items"] if x.get("status") == "evaluated"]

    def rate(xs):
        return {"n": len(xs), "hit": sum(1 for x in xs if x.get("hit")),
                "pct": round(100 * sum(1 for x in xs if x.get("hit")) / len(xs)) if xs else None}
    out = {"all": rate(ev), "recent20": rate(ev[-20:]),
           "by_market": {m: rate([x for x in ev if x["market"] == m]) for m in MKTS},
           "by_conf": {k: rate([x for x in ev if x.get("confidence") == k]) for k in ("高", "中", "低")},
           "by_dir": {k: rate([x for x in ev if x.get("dir") == k]) for k in DIRS},
           "pending": sum(1 for x in track["items"] if x.get("status") == "pending")}
    kinds = {}
    for x in ev:
        k = (x.get("reflection") or {}).get("kind")
        if k:
            kinds[k] = kinds.get(k, 0) + 1
    out["kinds"] = kinds
    seen, lessons = set(), []
    for x in sorted(ev, key=lambda x: x["eval_date"], reverse=True):
        ls = (x.get("reflection") or {}).get("lesson")
        if ls and ls not in seen:
            seen.add(ls)
            lessons.append({"lesson": ls, "date": x["base_date"], "market": x["market"], "hit": x.get("hit"),
                            "kind": x["reflection"].get("kind")})
        if len(lessons) >= 8:
            break
    out["lessons"] = lessons
    track["summary"] = out
    return out


def context(track, bnds):
    """チーフアナリストに渡す文。成績・直近の結果・教訓と、今回のもみ合いの幅"""
    s = track.get("summary") or summary(track)
    lines = [f"■予想の採点のしかた: {HORIZON}営業日後の終値(米国はS&P 500、日本は日経平均)で採点する。"
             f"もみ合いの幅は米国 ±{bnds.get('us')}%、日本 ±{bnds.get('jp')}%(この範囲内なら「もみ合い」が正解)"]
    a = s.get("all") or {}
    if a.get("n"):
        bm, bc = s["by_market"], s["by_conf"]
        lines.append("■過去の見立ての答え合わせ(これまでの成績)")
        lines.append(f"全体 {a['hit']}/{a['n']}(米国 {bm['us']['hit']}/{bm['us']['n']}、日本 {bm['jp']['hit']}/{bm['jp']['n']})。"
                     + "確信度別: " + "、".join(f"{k} {v['hit']}/{v['n']}" for k, v in bc.items() if v["n"])
                     + "。予想の方向別: " + "、".join(f"{k} {v['hit']}/{v['n']}" for k, v in s["by_dir"].items() if v["n"]))
        ev = [x for x in track["items"] if x.get("status") == "evaluated"][-6:]
        lines.append("直近の結果:")
        for x in reversed(ev):
            rf = x.get("reflection") or {}
            lines.append(f"- {x['base_date']} {MKTS[x['market']][1]}: 予想「{x['dir']}」→ 実際「{x['actual']}」"
                         f"({'的中' if x['hit'] else '外れ'})。{rf.get('why') or x.get('reflection_fallback', '')}")
        if s.get("lessons"):
            lines.append("これまでの教訓(新しい順。今回の状況に当てはまるものは必ず考慮する):")
            lines += [f"- {l['lesson']}" for l in s["lessons"]]
        lines.append("同じ読み違いを繰り返さないこと。forecast の reason では、関係する教訓をどう考慮したかを1文入れる。"
                     "過去の成績の数字は本文に書かない。")
    return "\n".join(lines)


def numbers(bnds):
    """チーフの文中で使ってよい数字(もみ合いの幅)"""
    return {abs(v) for v in bnds.values() if isinstance(v, (int, float))}
