"""分析の記録(memory.py)の試験。通信はせず、作った分析の結果で確かめる"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory as M  # noqa: E402


def res(d, typ="過熱の巻き戻し", head="AI株が下落", root="AIの過熱が解消", ai=True, top="半導体", pos=100, caution="高い", term=0.95, fc="もみ合い"):
    return {"asof": {"us": d, "jp": d}, "updated": d + "T08:00+09:00",
            "ai": {"ok": ai, "chief": {"headline": head, "root_cause": {"summary": root}, "confidence": "中",
                                       "us": {"direction": "下落", "causes": [{"title": "金利上昇", "weight": 60}]}, "jp": {"direction": "上昇", "causes": []},
                                       "forecast": {"us": {"dir": fc}, "jp": {"dir": "上昇"}}}},
            "features": {"a": {"group": "us", "name": top, "c1": 2.0}, "b": {"group": "us", "name": "公益", "c1": -1.0},
                         "SPY": {"group": "style", "name": "SPY", "last": 700, "c1": 1.0, "c5": 2.0}},
            "structure": {"types": [{"type": typ, "share": 60}, {"type": "内部の入れ替え", "share": 40}]},
            "strategy": {"us": {"rule": {"position": pos}, "caution": {"level": caution}, "now_vs_200": -0.5}},
            "flow": {"options": {"term": term, "items": {"^VIX": {"last": 20, "pct1y": 70}}}, "putcall": {"ok": False}}}


class MemoryTest(unittest.TestCase):
    def test_upsert_one_per_day_and_keep_ai_text(self):
        mem = M.empty()
        M.upsert(mem, M.snapshot(res("2026-11-25")))
        M.upsert(mem, M.snapshot(res("2026-11-25", head="夕方の見出し")))
        self.assertEqual([r["headline"] for r in mem["records"]], ["夕方の見出し"])
        M.upsert(mem, M.snapshot(res("2026-11-25", head="", ai=False)))       # AIが失敗した回は前の文を残す
        self.assertEqual(mem["records"][0]["headline"], "夕方の見出し")

    def test_analyze_streak_themes_changes(self):
        mem = M.empty()
        for i, d in enumerate(["2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25"]):
            M.upsert(mem, M.snapshot(res(d)))
        M.upsert(mem, M.snapshot(res("2026-11-26", typ="金利ショック", head="金利急騰で株安", root="インフレ懸念で金利上昇", top="エネルギー",
                                     pos=0, caution="非常に高い", term=1.1, fc="下落")))
        a = M.analyze(mem)
        self.assertEqual(a["type_now"], {"type": "金利ショック", "streak": 1})
        self.assertEqual(a["n"], 5)
        ch = " / ".join(a["changes"])
        for w in ("「過熱の巻き戻し」から「金利ショック」", "「投資」から「待機」", "「高い」から「非常に高い」", "期間構造が逆転",
                  "「半導体」から「エネルギー」", "予想が「もみ合い」から「下落」"):
            self.assertIn(w, ch)
        th = {x["theme"]: x for x in a["themes"]}
        self.assertEqual(th["AI・半導体"]["recent"], 4)
        self.assertEqual(th["金利"]["recent"], 5)                     # 主因の「金利上昇」も数える
        self.assertIn(("半導体", 4), a["leaders"]["us"]["top"])
        self.assertEqual(a["regime_days"]["us"], 1)
        self.assertEqual(a["timeline"][0]["date"], "2026-11-26")

    def test_by_type_with_track(self):
        mem = M.empty()
        M.upsert(mem, M.snapshot(res("2026-11-20")))
        tr = {"items": [{"status": "evaluated", "base_date": "2026-11-20", "hit": True}, {"status": "evaluated", "base_date": "2026-11-20", "hit": False},
                        {"status": "pending", "base_date": "2026-11-20"}]}
        self.assertEqual(M.analyze(mem, tr)["by_type"], [{"type": "過熱の巻き戻し", "n": 2, "hit": 1, "pct": 50}])

    def test_context_excludes_today_and_guides_continuity(self):
        self.assertIn("まだ記録がありません", M.context(M.empty()))
        mem = M.empty()
        M.upsert(mem, M.snapshot(res("2026-11-24")))
        M.upsert(mem, M.snapshot(res("2026-11-25", head="今日の見出し")))
        ctx = M.context(mem, upto="2026-11-25")
        self.assertNotIn("今日の見出し", ctx)
        self.assertIn("2026-11-24", ctx)
        self.assertIn("continuity", ctx)
        self.assertIn("構造的", ctx)


if __name__ == "__main__":
    unittest.main()
