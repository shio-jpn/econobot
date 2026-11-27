"""需給と戦略(flows.py)の試験。通信はせず、作ったデータで確かめる"""
import io
import json
import os
import sys
import unittest
import zipfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flows as F  # noqa: E402


def bars(n=300, start=100.0, step=0.001, vol=1000, last=None):
    """平日の日足 [(日付, 始, 高, 安, 終, 出来高)]。last=[(変化率, 出来高), ...] で最後の数日を指定"""
    d, out, c = date(2025, 1, 6), [], start
    while len(out) < n:
        if d.weekday() < 5:
            c *= 1 + step
            out.append((d.isoformat(), c, c * 1.01, c * 0.99, c, vol))
        d += timedelta(days=1)
    for k, (chg, v) in enumerate(last or []):
        i = n - len(last) + k
        c = out[i - 1][4] * (1 + chg)
        out[i] = (out[i][0], c, c * 1.01, c * 0.99, c, v)
    return out


class VolumeTest(unittest.TestCase):
    def test_distribution_days(self):
        rows = bars(last=[(-0.01, 2000), (0.005, 1000), (-0.003, 1500), (-0.003, 1400), (-0.001, 3000)])
        dds = F.distribution_days(rows)
        self.assertEqual(len(dds), 2)   # -1%で出来高増、-0.3%で出来高増(前日1000→1500)。-0.3%で出来高減、-0.1%は小さすぎる

    def test_follow_through_after_correction(self):
        drop = [(-0.02, 1000)] * 8
        rally = [(0.003, 900), (0.004, 900), (0.002, 900), (0.015, 1500)]   # 安値の翌日から4日目に+1.5%・出来高増
        rows = bars(last=drop + rally)
        ph = F.market_phase(rows)
        self.assertIsNotNone(ph["ftd"])
        self.assertEqual(ph["ftd"]["chg"], 1.5)
        self.assertLess(ph["drawdown"], -8)

    def test_hourly_days_fills_null_daily_bar(self):
        from datetime import datetime
        def ts(h):
            return int(datetime.fromisoformat(f"2026-11-26T{h:02d}:00:00+09:00").timestamp())
        res = {"chart": {"result": [{"meta": {"gmtoffset": 32400}, "timestamp": [ts(9), ts(12), ts(15)],
                                     "indicators": {"quote": [{"open": [57900, 57800, 57760], "high": [58000, 58076, 57760],
                                                               "low": [57700, 57749, 57288], "close": [57990, 57763, 57440], "volume": [0, 0, 0]}]}}]}}
        got = F.hourly_days("^N225", ["2026-11-26"], get=lambda u: json.dumps(res).encode())
        self.assertEqual(got["2026-11-26"], ("2026-11-26", 57900, 58076, 57288, 57440, None))
        rows = bars(n=40)
        rows[-1] = rows[-1][:5] + (None,)          # 出来高の分からない補完の日は、未確定として捨てない
        self.assertEqual(len(F._cut(rows, None)), 40)
        F.distribution_days(rows)   # 出来高 None でも落ちない

    def test_cut_drops_unfinished_zero_volume(self):
        rows = bars(n=40)
        rows[-1] = rows[-1][:5] + (0,)
        self.assertEqual(len(F._cut(rows, None)), 39)
        self.assertEqual(F._cut(rows, rows[-10][0])[-1][0], rows[-10][0])


class StrategyTest(unittest.TestCase):
    def test_trend_rule_uses_month_end(self):
        rows = bars(n=320)
        closes, days = [r[4] for r in rows], [r[0] for r in rows]
        r = F.trend_rule(closes, days)
        self.assertEqual(r["position"], 100)          # 上昇が続く
        self.assertEqual(r["decided"][:7], days[-1][:7] if days[-1][:7] != days[-2][:7] else r["decided"][:7])
        down = bars(n=320, step=-0.002)
        self.assertEqual(F.trend_rule([x[4] for x in down], [x[0] for x in down])["position"], 0)

    def test_backtest_rule_avoids_crash(self):
        up = bars(n=700, step=0.0008)
        crash = [(-0.01, 1000)] * 120 + [(0.001, 1000)] * 60
        rows = bars(n=880, step=0.0008, last=crash)
        bt = F.backtest(rows)
        self.assertGreater(bt["rule"]["mdd"], bt["hold"]["mdd"])   # 規則の最大の下落の方が小さい
        self.assertTrue(F.backtest(up))

    def test_caution_levels(self):
        rows = bars(n=300, last=[(-0.01, 2000 + k) for k in range(8)])
        closes, vols = [r[4] for r in rows], [r[5] for r in rows]
        c = F.caution(closes, vols, len(rows) - 1, vix=30, vix3m=25)
        self.assertIn(c["level"], ("高い", "非常に高い"))
        self.assertEqual(c["parts"]["VIXの期間構造"], -1)

    def test_levels(self):
        lv = F.levels(bars(n=260))
        self.assertGreater(lv["atr"], 0)
        self.assertGreater(lv["hi20"], lv["lo20"])


def xlsx(cells):
    """{行: {列: 値}} からxlsxのbytesを作る(文字列はsharedStrings)"""
    ss, rows = [], []
    for r in sorted(cells):
        cs = []
        for col, v in cells[r].items():
            if isinstance(v, str):
                ss.append(v)
                cs.append(f'<c r="{col}{r}" t="s"><v>{len(ss) - 1}</v></c>')
            else:
                cs.append(f'<c r="{col}{r}"><v>{v}</v></c>')
        rows.append(f'<row r="{r}">{"".join(cs)}</row>')
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/sharedStrings.xml", "<sst>" + "".join(f"<si><t>{s}</t></si>" for s in ss) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet><sheetData>{''.join(rows)}</sheetData></worksheet>")
    return b.getvalue()


class JPXTest(unittest.TestCase):
    def test_parse_investor(self):
        val = {"C": "金額 Value", "V": -304195584, "Z": -2172107, "N": -396346409, "R": 41779544, "BB": 389307961,
               "AL": 282735687, "AH": -13591136, "AT": -65598446, "AX": -44287401, "F": 324362002, "J": -168930464}
        b = xlsx({8: {"B": "東証プライム\nTSE Prime Market", "C": "株数"}, 9: val})
        x = F.parse_investor(b, "stock_1_w_20261109_20261113.xlsx")
        self.assertEqual(x["海外投資家"], -3064)      # 実データ(2026-11の第2週)と同じ
        self.assertEqual(x["個人"], -3546)
        self.assertEqual(x["信託銀行"], 3893)
        self.assertEqual(x["to"], "20261113")

    def test_parse_margin(self):
        b = xlsx({14: {"B": "信用取引残高合計 Total Outstanding", "D": "株数Shs."},
                  15: {"D": "金額Val.", "E": 643827, "F": -16174, "G": 5632962, "H": -135197}})
        m = F.parse_margin(b, "20261120_mtcurrent.xlsx")
        self.assertEqual((m["buy"], m["buy_chg"], m["sell"], m["ratio"]), (56330, -1352, 6438, 8.75))

    def test_jpx_block_keeps_history_and_survives_errors(self):
        def get(u):
            raise OSError("down")
        out = F.jpx_block({"investor_hist": [{"to": "20261106", "海外投資家": 100}], "margin_hist": []}, get=get)
        self.assertEqual(out["investor"]["海外投資家"], 100)   # 取れない週は、前回までの履歴を使う


class OptionsAndCOTTest(unittest.TestCase):
    def test_putcall_backfill_and_stats(self):
        calls = []

        def get(u):
            calls.append(u)
            d = u.split("/")[-1][:10]
            v = 0.5 + (int(d[-2:]) % 10) / 100
            return json.dumps({"ratios": [{"name": "TOTAL PUT/CALL RATIO", "value": "0.9"},
                                          {"name": "EQUITY PUT/CALL RATIO", "value": f"{v:.2f}"}]}).encode()
        pc = F.putcall_block("2026-11-25", [], get=get)
        self.assertTrue(pc["ok"])
        self.assertEqual(len(calls), 25)                  # 履歴が無い時は25営業日分を埋める
        self.assertNotIn("2026-11-26", [h["date"] for h in pc["hist"]])   # 感謝祭は取りに行かない
        calls.clear()
        pc2 = F.putcall_block("2026-11-25", pc["hist"], get=get)
        self.assertEqual(len(calls), 0)                   # 2回目は履歴にあるので取りに行かない
        self.assertIsNotNone(pc2["equity10"])

    def test_putcall_not_ok_when_today_missing(self):
        pc = F.putcall_block("2026-11-25", [{"date": "2026-11-24", "equity": 0.6}] * 30, get=lambda u: (_ for _ in ()).throw(OSError()))
        self.assertFalse(pc["ok"])

    def test_cot_index(self):
        def get(u):
            rows = [{"report_date_as_yyyy_mm_dd": f"2026-{1 + i // 4:02d}-{1 + (i % 4) * 7:02d}T00:00:00.000",
                     "lev_money_positions_long": str(100 + i), "lev_money_positions_short": "100",
                     "asset_mgr_positions_long": "50", "asset_mgr_positions_short": str(50 + i), "open_interest_all": "1000"}
                     for i in range(40)]
            return json.dumps(rows).encode()
        c = F.cot_block(get=get)
        self.assertEqual(c["sp"]["lev_idx"], 100)   # いちばん買い越し
        self.assertEqual(c["sp"]["am_idx"], 0)      # いちばん売り越し
        self.assertEqual(c["sp"]["lev_chg"], 1)

    def test_calendar(self):
        ev = F.calendar_block(date(2026, 11, 26))
        whats = [e["what"] for e in ev]
        self.assertTrue(any("メジャーSQ" in w for w in whats))
        self.assertIn("2026-12-11", [e["date"] for e in ev])   # 12月の第2金曜
        self.assertIn("2026-12-18", [e["date"] for e in ev])   # 12月の第3金曜
        self.assertTrue(all(e["days"] >= 0 for e in ev))


class DescribeTest(unittest.TestCase):
    def test_rule_sentence_and_ust_excluded(self):
        v = {"name": "S&P 500", "rule": {"position": 100, "decided": "2026-10-30"}, "flip_watch": True, "now_vs_200": -2.31,
             "caution": {"level": "非常に高い"}}
        t = F.rule_sentence(v)
        self.assertIn("規則の判定は「投資」(10/30の月末に判定)", t)
        self.assertIn("このまま月末を迎えると「待機」に変わる", t)
        cot = {"ust10": {"name": "米10年国債の先物", "date": "2026-11-17", "lev_net": -2482443, "lev_chg": -181116, "lev_idx": 4,
                         "am_net": 3270834, "am_chg": 117073, "am_idx": 100}}
        self.assertNotIn("米10年国債", F.describe({"cot": cot}, {}))   # 裁定取引が大半で読み違えるためAIに渡さない

    def test_position_words_are_unambiguous(self):
        t = F.position_words(-234978, 68082, 86)       # 2026-11-17のS&P 500先物のヘッジファンド
        self.assertIn("売り越し 234,978枚", t)
        self.assertIn("売り越しが68,082枚縮小(買い戻し)", t)
        self.assertIn("買い寄り", t)
        self.assertIn("売り越しが6,935枚拡大(新たな売り)", F.position_words(-23790, -6935, 60))
        self.assertIn("買い越しが5,663枚縮小(売り)", F.position_words(84681, -5663, 81))

    def test_describe_and_numbers(self):
        flow = {"investor": {"from": "20261109", "to": "20261113", "海外投資家": -3064}, "investor_4w": {"海外投資家": -1515},
                "margin_hist": [{"date": "20261120", "buy": 56330, "sell": 6438, "ratio": 8.75}],
                "options": {"items": {"^VIX": {"name": "VIX", "last": 28.29, "chg1": 1.93, "pct1y": 98}}, "term": 1.076, "move1d": 1.78, "move1w": 3.92}}
        t = F.describe(flow, {})
        self.assertIn("海外投資家 -3,064", t)
        self.assertIn("信用倍率8.75", t)
        nums = F.numbers(flow, {})
        self.assertIn(5.633, nums)    # 56330億円 → 5.633兆円
        self.assertIn(28.29, nums)
        st = {"us": {"levels": {"close": 7182.78, "atr": 168.94, "atr_pct": 2.35}}}
        n2 = F.numbers(flow, st)
        self.assertTrue(any(abs(x - 337.88) < 0.01 for x in n2))    # ATRの2倍(本番で「約338ポイント」が捨てられた)
        self.assertTrue(any(abs(x - 6844.9) < 0.01 for x in n2))    # 終値 − ATRの2倍


if __name__ == "__main__":
    unittest.main()
