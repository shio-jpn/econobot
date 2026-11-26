"""深掘り分析(deep_dive.py)の試験。通信はせず、作った値動きと、決まった返事をするAIで確かめる"""
import json
import math
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import econobot as eb  # noqa: E402
import deep_dive as dd  # noqa: E402

NOW = datetime(2026, 11, 27, 8, 5, tzinfo=eb.JST)


def series(n=260, drift=0.0, wiggle=0.01, last=None, start=100.0, phase=0.0):
    """平日の終値。ゆらぎは正弦波(毎回同じ値)。last=(日数, 合計の変化率)で最後の数日を動かす"""
    d0, out, v = date(2025, 11, 3), [], start
    days = []
    d = d0
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    for i, day in enumerate(days):
        v *= 1 + drift + wiggle * math.sin(i * 1.7 + phase)
        out.append((day, v))
    if last:
        k, total = last
        step = (1 + total) ** (1 / k)
        for i in range(n - k, n):
            out[i] = (out[i][0], out[i - 1][1] * step)
    return out


def yields(n=260, level=4.5, last_bp=None):
    rows = [(d, level + 0.03 * math.sin(i * 1.3)) for i, (d, _) in enumerate(series(n))]
    if last_bp:
        k, bp = last_bp
        for j, i in enumerate(range(n - k, n), 1):
            rows[i] = (rows[i][0], rows[n - k - 1][1] + bp / 100 * j / k)
    return rows


def base_rows(**over):
    rows = {}
    for i, (sym, _, _) in enumerate(dd.all_symbols()):
        rows[sym] = yields() if sym in dd.YIELD_SYMS else series(phase=i)
    rows.update(over)
    return rows


class FeatureTest(unittest.TestCase):
    def test_features_z_rs_and_bp(self):
        rows = base_rows(**{"XLK": series(last=(1, 0.05)), "^TNX": yields(last_bp=(5, 30))})
        f = dd.features(rows)
        self.assertAlmostEqual(f["XLK"]["c1"], 5.0, places=1)
        self.assertGreater(f["XLK"]["z1"], 3)              # ふだんの値動きより大きい
        self.assertIsNotNone(f["XLK"]["rs1"])             # 対S&P 500の差
        self.assertEqual(f["^TNX"]["unit"], "bp")
        self.assertAlmostEqual(f["^TNX"]["c5"], 30, delta=1)
        self.assertEqual(f["1617.T"]["group"], "jp")
        self.assertIn("rs20", f["1617.T"])                 # 日本はTOPIXとの差

    def test_signals_and_breadth(self):
        rows = base_rows(**{"SMH": series(last=(5, -0.10))})
        s = {x["id"]: x for x in dd.signals(rows)}
        self.assertLess(s["semi"]["c5"], -5)
        self.assertLess(s["semi"]["z5"], -1)
        b = dd.breadth(dd.features(rows), "us")
        self.assertEqual(b["n"], 12)

    def test_skips_short_series(self):
        rows = base_rows(XLK=series(n=40))
        self.assertNotIn("XLK", dd.fetch_all(fetch=lambda s: rows[s]))


class RuleTest(unittest.TestCase):
    def test_rate_rise_hits_rate_sensitive(self):
        rows = base_rows(**{"^TNX": yields(last_bp=(5, 40)), "XLRE": series(last=(5, -0.08)), "XLU": series(last=(5, -0.07), phase=3)})
        f = dd.features(rows)
        rules = dd.rule_drivers(f, dd.signals(rows), 5)
        r = next(x for x in rules if "金利" in x["title"])
        self.assertEqual(r["side"], "下落要因")
        self.assertIn("上がると", r["text"])

    def test_world_selloff_and_catch_all(self):
        drop = {s: series(last=(1, -0.04), phase=i) for i, s in enumerate(("^STOXX50E", "^HSI", "^N225", "^KS11"))}
        drop["1622.T"] = series(last=(1, -0.06))
        rows = base_rows(**drop)
        titles = [x["title"] for x in dd.rule_drivers(dd.features(rows), dd.signals(rows), 1)]
        self.assertTrue(any("世界の株が同時に下落" in t for t in titles))
        self.assertTrue(any("外需株" in t for t in titles))     # 型に当てはまらない大きな資金の流れも拾う

    def test_quiet_market_has_few_rules(self):
        rows = base_rows()
        self.assertLessEqual(len(dd.rule_drivers(dd.features(rows), dd.signals(rows), 5)), 2)


class NumberCheckTest(unittest.TestCase):
    def test_scrub_drops_unknown_numbers(self):
        allowed = [1.23, 30.0, 4.85]
        dropped = []
        t = dd.scrub("テクノロジーは+1.23%上昇。PERは35倍で割高。10年債は30bp上昇。目標は7,500ドル。", allowed, dropped)
        self.assertIn("1.23%", t)
        self.assertIn("30bp", t)
        self.assertNotIn("35倍", t)           # データに無いPERは捨てる
        self.assertNotIn("7,500ドル", t)      # データに無い価格は捨てる
        self.assertEqual(len(dropped), 2)
        self.assertEqual(dd.bad_numbers("ふだんの1.2倍の動き", [1.23]), [])   # z値の倍率はデータにある

    def test_bp_matches_percent_points(self):
        self.assertEqual(dd.bad_numbers("利回りは4.85%", [4.85]), [])
        self.assertEqual(dd.bad_numbers("22bp低下", [22.0]), [])
        self.assertEqual(dd.bad_numbers("5ポイント", []), [])   # 小さな整数はよい
        self.assertEqual(dd.bad_numbers("18.9%下落", [1.0]), ["18.9%"])


def fake_ai(reviews_ok=False, fail=()):
    """役割ごとに決まった返事をするGemini。呼ばれた順を記録する"""
    calls = []

    def call(prompt, schema, label, models=None):
        calls.append(label)
        if any(f in label for f in fail):
            raise RuntimeError("Geminiの時間の上限(420秒)に達しました" if "上限" in fail else "HTTP 503")
        if "査読" in label:
            return json.dumps({"ok": reviews_ok, "issues": [] if reviews_ok else [{"where": "us", "problem": "逆の記述", "fix": "直す"}]})
        if "チーフ" in label or "改訂" in label:
            mk = {"direction": "下落", "summary": "金利の上昇で成長株が売られた。PERは99倍。", "causes": [
                {"title": "金利の上昇", "weight": 60, "explain": "10年債が30bp上昇し、不動産が売られた。", "evidence": ["^TNX", "XLRE", "bogus"]},
                {"title": "根拠の無い主因", "weight": 40, "explain": "株価は12,345ドルまで下がる。", "evidence": []}]}
            return json.dumps({"headline": "改訂版" if "改訂" in label else "初版", "us": mk, "jp": dict(mk, direction="上昇"),
                               "sectors": [{"name": "不動産", "why": "金利に敏感。"}], "debate": "弱気が優勢。",
                               "outlook_short": "条件つきで弱含み。", "outlook_mid": "金利しだい。",
                               "watch": [{"what": "CPI", "why": "金利の行方を決める。"}], "change": ["金利が下がれば見直す。"],
                               "confidence": "中", "lesson": "金利と成長株の関係を見る。"})
        return json.dumps({"view": f"{label}の結論。", "items": [
            {"title": "金利", "explain": "10年債が30bp上昇した。", "impact": "下落要因", "confidence": "高", "evidence": ["^TNX", "N1"]},
            {"title": "作り話", "explain": "売上が77.7%減った。", "impact": "下落要因", "evidence": []}], "watch": ["CPI"]})
    return call, calls


class AITest(unittest.TestCase):
    def setUp(self):
        self.rows = base_rows(**{"^TNX": yields(last_bp=(5, 30))})
        self.feat = dd.features(self.rows)
        self.sigs = dd.signals(self.rows)
        self.out = {"econ": {"ok": True, "headline": "金利上昇", "key_points": [{"text": "利回り上昇", "category": "金利"}]},
                    "major": {"ok": True, "items": []}, "econ_articles": [{"title": "Yields jump", "source": "CNBC"}]}

    def test_passes_chief_review_and_revision(self):
        call, calls = fake_ai(reviews_ok=False)
        with mock.patch.object(eb, "_call_gemini", call):
            r = dd.run_ai(self.feat, self.sigs, [], {}, self.out)
        self.assertEqual([c.split(":")[1] for c in calls[:5]], [x[1] for x in dd.ROLES] + [dd.BEAR[1], dd.BULL[1]])
        self.assertEqual(calls[5:], ["深掘り:チーフ", "深掘り:査読", "深掘り:改訂"])
        self.assertTrue(r["ok"])
        c = r["chief"]
        self.assertEqual(c["headline"], "改訂版")                       # 査読の指摘で直した版を使う
        self.assertEqual(len(c["us"]["causes"]), 1)                     # 根拠の無い数字の主因は捨てる
        self.assertEqual(c["us"]["causes"][0]["weight"], 100)           # 残りで合計100に直す
        self.assertEqual(c["us"]["causes"][0]["evidence"], ["^TNX", "XLRE"])   # 知らない記号は外す
        self.assertEqual(len(r["passes"]["macro"]["items"]), 1)         # 作り話の数字は捨てる
        self.assertEqual(r["passes"]["macro"]["items"][0]["evidence"], ["^TNX", "N1"])
        self.assertGreaterEqual(len(r["dropped"]), 5)
        self.assertNotIn("99倍", c["us"]["summary"])

    def test_review_ok_skips_revision(self):
        call, calls = fake_ai(reviews_ok=True)
        with mock.patch.object(eb, "_call_gemini", call):
            r = dd.run_ai(self.feat, self.sigs, [], {}, self.out)
        self.assertNotIn("深掘り:改訂", calls)
        self.assertEqual(r["chief"]["headline"], "初版")

    def test_budget_exhausted_stops(self):
        call, calls = fake_ai(fail=("世界情勢", "上限"))
        with mock.patch.object(eb, "_call_gemini", call):
            r = dd.run_ai(self.feat, self.sigs, [], {}, self.out)
        self.assertFalse(r["ok"])                     # 2人分しかないので統合しない
        self.assertEqual(len(r["passes"]), 2)
        self.assertNotIn("深掘り:チーフ", calls)

    def test_one_failed_role_continues(self):
        call, calls = fake_ai(fail=("世界情勢",))
        with mock.patch.object(eb, "_call_gemini", call):
            r = dd.run_ai(self.feat, self.sigs, [], {}, self.out)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["passes"]), 4)
        self.assertEqual(len(r["errors"]), 1)


class PublishTest(unittest.TestCase):
    def test_history_and_write(self):
        rows = base_rows()
        prev = {"history": [{"date": "2026-10-01", "spy": 100, "us": "上昇"}, {"date": rows["SPY"][-1][0], "spy": 1, "us": "下落"}]}
        call, _ = fake_ai(reviews_ok=True)
        with mock.patch.object(eb, "_call_gemini", call), \
             mock.patch.object(eb, "_gh_get_file", return_value=("sha", json.dumps(prev).encode())), \
             mock.patch.object(eb, "_gh_put_file") as put, \
             mock.patch.object(eb, "datetime") as dt:
            dt.now.return_value = NOW
            self.assertTrue(dd.publish_analysis({}, None, fetch=lambda s: rows[s]))
        path, body, msg = put.call_args[0]
        self.assertEqual(path, "learn/data/analysis.json")
        d = json.loads(body.decode())
        self.assertEqual([h["date"] for h in d["history"]], ["2026-10-01", rows["SPY"][-1][0]])   # 同じ日は置き換え
        self.assertEqual(d["history"][-1]["us"], "下落")
        self.assertEqual(d["history"][-1]["headline"], "初版")
        self.assertTrue(d["ai"]["ok"])
        self.assertIn("SPY", d["features"])

    def test_not_enough_data(self):
        with mock.patch.object(eb, "_gh_put_file") as put:
            self.assertFalse(dd.publish_analysis({}, None, fetch=lambda s: (_ for _ in ()).throw(OSError("x"))))
            put.assert_not_called()

    def test_gemini_budget_reset(self):
        eb._GEMINI_CLOCK["start"] = 0.0
        old = eb.GEMINI_BUDGET
        try:
            eb._gemini_reset(123)
            self.assertEqual(eb.GEMINI_BUDGET, 123)
            self.assertIsNone(eb._GEMINI_CLOCK["start"])
        finally:
            eb.GEMINI_BUDGET = old


if __name__ == "__main__":
    unittest.main()
