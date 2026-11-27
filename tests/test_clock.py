"""時計(clock.py)の試験。通信はせず、時刻の計算と引き継ぎの判断を確かめる"""
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import clock as C  # noqa: E402


def jst(h, m, d=27):
    return datetime(2026, 11, d, h, m, tzinfo=C.JST)


class ClockPlanTest(unittest.TestCase):
    def test_next_fire(self):
        self.assertEqual(C.next_fire(jst(6, 0)), (jst(7, 0), "morning"))
        self.assertEqual(C.next_fire(jst(7, 0)), (jst(17, 15), "evening"))
        self.assertEqual(C.next_fire(jst(21, 50)), (jst(7, 0, 28), "morning"))

    def test_plan_waits_or_relays(self):
        self.assertEqual(C.plan(jst(3, 0)), ([], jst(7, 0), "morning"))          # 4時間後 → 待って起動
        self.assertEqual(C.plan(jst(8, 0)), (["morning"], jst(13, 40), None))      # 取り戻しの窓の中。夕方は9時間後 → 5時間40分で引き継ぎ
        self.assertEqual(C.plan(jst(13, 40)), ([], jst(17, 15), "evening"))

    def test_catch_up_window(self):
        self.assertEqual(C.plan(jst(21, 50))[0], ["evening"])
        self.assertEqual(C.plan(jst(10, 0))[0], ["morning"])
        self.assertEqual(C.plan(jst(23, 45))[0], [])
        self.assertEqual(C.plan(jst(12, 30))[0], [])

    def _run(self, start, relay, others=(), newer=()):
        t = {"now": start}
        fired = []

        def sleep(sec):
            t["now"] = t["now"] + C.timedelta(seconds=sec)
        calls = {"n": 0}

        def oc(own):
            calls["n"] += 1
            return list(others) if calls["n"] == 1 and not relay else list(newer)
        env = {"GITHUB_RUN_ID": "100", "RELAY": "true" if relay else ""}
        with mock.patch.dict(os.environ, env), mock.patch.object(C, "now_jst", lambda: t["now"]), \
                mock.patch.object(C.time, "sleep", sleep), mock.patch.object(C, "other_clocks", oc), \
                mock.patch.object(C, "dispatch", lambda wf, inp: fired.append((wf, inp)) or True):
            rc = C.main()
        return rc, fired, t["now"]

    def test_main_catch_up_then_wait_and_relay(self):
        rc, fired, end = self._run(jst(21, 50), relay=False)
        self.assertEqual(rc, 0)
        self.assertEqual(fired[0], ("econobot.yml", {"slot": "evening"}))
        self.assertEqual(fired[-1], ("clock.yml", {"relay": "true"}))
        self.assertEqual(end, jst(3, 30, 28))                                    # 21:50 + 5:40

    def test_relay_fires_slot_without_catch_up(self):
        rc, fired, end = self._run(jst(3, 30), relay=True)
        self.assertEqual(fired, [("econobot.yml", {"slot": "morning"}), ("clock.yml", {"relay": "true"})])
        self.assertEqual(end, jst(7, 0))

    def test_second_clock_exits_and_newer_stops_relay(self):
        rc, fired, _ = self._run(jst(21, 50), relay=False, others=[{"id": 99}])
        self.assertEqual(fired, [])
        rc, fired, _ = self._run(jst(3, 30), relay=True, newer=[{"id": 101}])
        self.assertEqual(fired, [("econobot.yml", {"slot": "morning"})])


if __name__ == "__main__":
    unittest.main()
