"""見立ての答え合わせ(track.py)の試験。通信はせず、作ったデータで確かめる"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import track as T  # noqa: E402


def days(n, start=date(2026, 11, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def series(vals, start=date(2026, 11, 2)):
    return list(zip(days(len(vals), start), vals))


class TrackTest(unittest.TestCase):
    def test_classify_and_band(self):
        self.assertEqual(T.band(1.2), round(0.25 * 1.2 * 5 ** 0.5, 2))
        self.assertEqual(T.classify(1.0, 0.67), "上昇")
        self.assertEqual(T.classify(-1.0, 0.67), "下落")
        self.assertEqual(T.classify(0.5, 0.67), "もみ合い")
        self.assertIsNone(T.classify(None, 0.67))

    def _res(self, d_us, d_jp, us="下落", jp="上昇", ok=True, reused=None):
        ai = {"ok": ok, "chief": {"headline": "見出し", "confidence": "中", "root_cause": {"summary": "根本"},
                                  "forecast": {"us": {"dir": us, "reason": "理由US"}, "jp": {"dir": jp, "reason": "理由JP"}}}}
        if reused:
            ai["reused_from"] = reused
        return {"updated": f"{d_us}T08:00+09:00", "asof": {"us": d_us, "jp": d_jp}, "ai": ai}

    def test_record_evaluate_and_summary(self):
        us = series([100, 101, 102, 103, 104, 105, 106, 107])          # 5営業日で+5%近く上昇
        jp = series([200, 199, 198, 199, 200, 200.5, 200.2, 200])      # ほぼ横ばい
        tr = T.empty()
        closes = {"us": us[:3], "jp": jp[:3]}
        n = T.record(tr, self._res(us[2][0], jp[2][0]), closes, {"us": 0.7, "jp": 1.5})
        self.assertEqual(n, 2)
        self.assertEqual(tr["items"][0]["status"], "pending")
        # まだ5営業日たっていない
        self.assertEqual(T.evaluate(tr, {"us": us[:5], "jp": jp[:5]}, {}, {}, {}), 0)
        self.assertEqual(tr["items"][0]["remaining"], 3)
        rows = {"SPY": us, "^N225": jp}
        self.assertEqual(T.evaluate(tr, {"us": us, "jp": jp}, rows, {}, {}), 2)
        it_us = next(x for x in tr["items"] if x["market"] == "us")
        it_jp = next(x for x in tr["items"] if x["market"] == "jp")
        self.assertEqual((it_us["actual"], it_us["hit"]), ("上昇", False))     # 下落と予想して外れ
        self.assertEqual(it_us["ret5"], round((107 / 102 - 1) * 100, 2))
        self.assertEqual(it_us["eval_date"], us[7][0])
        self.assertEqual((it_jp["actual"], it_jp["hit"]), ("もみ合い", False))
        self.assertIn("S&P 500(SPY)", it_us["facts"])
        s = T.summary(tr)
        self.assertEqual((s["all"]["n"], s["all"]["hit"]), (2, 0))
        self.assertEqual(s["by_market"]["us"]["n"], 1)

    def test_record_replaces_pending_and_skips_reused(self):
        us = series([100, 101, 102])
        tr = T.empty()
        T.record(tr, self._res(us[2][0], us[2][0], us="下落"), {"us": us, "jp": []}, {"us": 0.7})
        T.record(tr, self._res(us[2][0], us[2][0], us="上昇"), {"us": us, "jp": []}, {"us": 0.7})   # 夕方の更新
        self.assertEqual([x["dir"] for x in tr["items"]], ["上昇"])
        self.assertEqual(T.record(tr, self._res(us[2][0], us[2][0], reused="2026-11-26T21:29"), {"us": us}, {}), 0)
        self.assertEqual(T.record(tr, self._res(us[2][0], us[2][0], ok=False), {"us": us}, {}), 0)
        # 終値の最新日が基準日と違う(データ遅れ)なら保存しない
        self.assertEqual(T.record(tr, self._res("2026-12-31", "2026-12-31"), {"us": us, "jp": us}, {}), 0)

    def test_reflect_and_context(self):
        us = series([100, 101, 102, 103, 104, 105, 106, 107])
        tr = T.empty()
        T.record(tr, self._res(us[2][0], us[2][0]), {"us": us[:3], "jp": []}, {"us": 0.7, "jp": 1.0})
        T.evaluate(tr, {"us": us}, {"SPY": us}, {}, {})
        prompts = []

        def ask(p, schema, label):
            prompts.append(p)
            return {"kind": "方向の読み違い", "why": "金利低下で買い戻された。", "missed": ["売られ過ぎ"], "lesson": "VIXが高い時は下落の予想を控えめにする"}
        self.assertEqual(T.reflect(tr, ask), 1)
        self.assertIn("予想: 下落", prompts[0])
        self.assertIn("外れ", prompts[0])
        self.assertEqual(T.reflect(tr, ask), 0)             # 考察済みは聞き直さない
        T.summary(tr)
        ctx = T.context(tr, {"us": 0.7, "jp": 1.0})
        self.assertIn("もみ合いの幅は米国 ±0.7%", ctx)
        self.assertIn("VIXが高い時は下落の予想を控えめにする", ctx)
        self.assertIn("予想「下落」→ 実際「上昇」(外れ)", ctx)

    def test_reflect_failure_keeps_for_next_run(self):
        us = series([100, 101, 102, 103, 104, 105, 106, 107])
        tr = T.empty()
        T.record(tr, self._res(us[2][0], us[2][0]), {"us": us[:3], "jp": []}, {"us": 0.7})
        T.evaluate(tr, {"us": us}, {"SPY": us}, {}, {})

        def ask(p, schema, label):
            raise RuntimeError("1日の上限")
        self.assertEqual(T.reflect(tr, ask), 0)
        it = tr["items"][0]
        self.assertNotIn("reflection", it)
        self.assertTrue(it["reflection_fallback"].startswith("その5営業日の動き"))

    def test_empty_context_has_band_only(self):
        ctx = T.context(T.empty(), {"us": 0.7, "jp": 1.0})
        self.assertIn("採点のしかた", ctx)
        self.assertNotIn("これまでの成績", ctx)


if __name__ == "__main__":
    unittest.main()
