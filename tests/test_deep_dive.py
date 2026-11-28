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

dd.RETRY_WAITS = dd.BACKUP_WAITS = ()   # 試験では取り直しを待たない
LAST_DAY = None   # 作った値動きの最後の日(series() の結果から決まる)

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


def fetcher(rows):
    """fetch_all に渡す取得の関数: (騰落用, 終値) を返す"""
    return lambda s: (rows[s], rows[s])


def fetched(rows, now=None):
    """作った値動きの最後の日を「米国の最新の取引日」として取得したことにする"""
    last = rows["SPY"][-1][0]
    with mock.patch.object(dd, "expected_us_date", return_value=last):
        return dd.fetch_all(fetch=fetcher(rows), waits=())


def base_rows(**over):
    rows = {}
    for i, (sym, _, _) in enumerate(dd.all_symbols()):
        rows[sym] = yields() if sym in dd.YIELD_SYMS else series(phase=i)
    rows["^GSPC"] = rows["SPY"]   # 照合用の指数はSPYと同じ動き
    rows.update(over)
    return rows


_TR = mock.patch.object(eb, "treasury_rows", side_effect=OSError("試験では財務省のCSVを取りに行かない"))
import flows  # noqa: E402
_FL = mock.patch.object(flows, "build", return_value=({}, {}))   # 需給と戦略は test_flows.py で確かめる(ここでは通信しない)


def setUpModule():
    _TR.start()
    _FL.start()


def tearDownModule():
    _TR.stop()
    _FL.stop()


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
        f = fetched(rows)
        self.assertNotIn("XLK", f["rows"])
        self.assertIn("XLK", f["quality"]["missing"])
        self.assertFalse(f["quality"]["complete"])


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
        self.assertEqual([c.split(":")[1] for c in calls[:5]], [x[1] for x in dd.ROLES] + [dd.FLOW[1], dd.BEAR[1]])
        self.assertEqual(calls[5:7], ["深掘り:" + dd.BULL[1], "深掘り:" + dd.STRAT[1]])
        self.assertEqual(calls[7:], ["深掘り:チーフ", "深掘り:査読", "深掘り:改訂"])
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
        self.assertEqual(len(r["passes"]), 6)   # 7人のうち1人が失敗
        self.assertEqual(len(r["errors"]), 1)


class PublishTest(unittest.TestCase):
    def test_history_and_write(self):
        rows = base_rows()
        prev = {"history": [{"date": "2026-10-01", "spy": 100, "us": "上昇"}, {"date": rows["SPY"][-1][0], "spy": 1, "us": "下落"}]}
        call, _ = fake_ai(reviews_ok=True)
        with mock.patch.object(eb, "_call_gemini", call), \
             mock.patch.object(dd, "expected_us_date", return_value=rows["SPY"][-1][0]), \
             mock.patch.object(eb, "_gh_get_file", return_value=("sha", json.dumps(prev).encode())), \
             mock.patch.object(eb, "_gh_put_file") as put, \
             mock.patch.object(eb, "datetime") as dt:
            dt.now.return_value = NOW
            self.assertTrue(dd.publish_analysis({}, None, fetch=fetcher(rows)))
        path, body, msg = put.call_args[0]
        self.assertEqual(path, "learn/data/analysis.json")
        d = json.loads(body.decode())
        self.assertEqual([h["date"] for h in d["history"]], ["2026-10-01", rows["SPY"][-1][0]])   # 同じ日は置き換え
        self.assertEqual(d["history"][-1]["us"], "下落")
        self.assertEqual(d["history"][-1]["headline"], "初版")
        self.assertTrue(d["ai"]["ok"])
        self.assertIn("SPY", d["features"])
        self.assertTrue(d["quality"]["complete"])
        self.assertIsNotNone(d["contrib"]["us"])        # 主力銘柄の寄与
        self.assertEqual(d["contrib"]["jp"]["index"], "^N225")

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



class AccuracyTest(unittest.TestCase):
    """2026-11-26 に実データで見つかった問題が直っていること"""

    def chart(self, sym, bars, itype="ETF", off=-18000, reg=None):
        return {"meta": {"symbol": sym, "gmtoffset": off, "instrumentType": itype, "currentTradingPeriod": {"regular": reg or {}}},
                "timestamp": [t for t, _, _ in bars],
                "indicators": {"quote": [{"close": [c for _, c, _ in bars]}], "adjclose": [{"adjclose": [a for _, _, a in bars]}]}}

    def test_split_glitch_is_dropped(self):
        # 1306.T: 分割の調整が2日だけ二重にかかり、値が1/10になっていた
        base = int(datetime(2026, 3, 20, tzinfo=eb.JST).timestamp())
        vals = [383.6, 382.6, 382.7, 37.64, 37.14, 389.2, 383.0, 386.6]
        bars = [(base + i * 86400, v, v) for i, v in enumerate(vals)]
        ret, close = dd.parse_chart(self.chart("1306.T", bars, off=32400), "1306.T", now=datetime(2026, 4, 5, tzinfo=eb.JST))
        self.assertEqual([v for _, v in ret], [383.6, 382.6, 382.7, 389.2, 383.0, 386.6])
        self.assertEqual(len(close), 6)

    def test_dividend_adjusted_returns_but_real_close(self):
        base = int(datetime(2026, 11, 2, 14, 30, tzinfo=eb.timezone.utc).timestamp())
        bars = [(base, 77.0, 76.6), (base + 86400, 76.6, 76.6)]   # 配当落ちで0.4下がった日
        ret, close = dd.parse_chart(self.chart("HYG", bars), "HYG", now=datetime(2026, 11, 5, tzinfo=eb.timezone.utc))
        self.assertAlmostEqual(ret[-1][1] / ret[0][1] - 1, 0.0)    # 騰落は配当込みで0
        self.assertEqual(close[-1][1], 76.6)                         # 表示は実際の終値

    def test_futures_session_dates(self):
        # 原油: 11/25の取引の終値(米東部00:00の足)と、11/25夕方から始まった11/26の取引の途中の値
        t25 = int(datetime(2026, 11, 25, 5, 0, tzinfo=eb.timezone.utc).timestamp())
        t_live = int(datetime(2026, 11, 26, 4, 50, tzinfo=eb.timezone.utc).timestamp())
        ret, _ = dd.parse_chart(self.chart("CL=F", [(t25 - 86400, 82.05, 82.05), (t25, 83.68, 83.68), (t_live, 84.44, 84.44)], "FUTURE"),
                                "CL=F", now=datetime(2026, 11, 26, 5, 0, tzinfo=eb.timezone.utc))
        self.assertEqual(dict(ret)["2026-11-25"], 83.68)     # 途中の値で上書きされない
        self.assertEqual(ret[-1][0], "2026-11-26")           # 途中の値は翌日の取引として分ける(fetch_allで捨てる)

    def test_nyse_calendar(self):
        self.assertIn(date(2026, 11, 26), dd.nyse_holidays(2026))   # 感謝祭
        self.assertIn(date(2026, 4, 3), dd.nyse_holidays(2026))     # 聖金曜日
        self.assertIn(date(2026, 7, 3), dd.nyse_holidays(2026))     # 独立記念日(土曜)の振替
        utc = eb.timezone.utc
        # 感謝祭の翌朝(日本時間11/27 8時)に終値があるべき日は11/25
        self.assertEqual(dd.expected_us_date(datetime(2026, 11, 26, 23, 0, tzinfo=utc)), "2026-11-25")
        # 普通の平日の朝(日本時間火曜8時 = 米東部月曜18時/19時)は月曜
        self.assertEqual(dd.expected_us_date(datetime(2026, 11, 23, 23, 0, tzinfo=utc)), "2026-11-23")
        # 引けの前(米東部15時)は前の取引日
        self.assertEqual(dd.expected_us_date(datetime(2026, 11, 23, 20, 0, tzinfo=utc)), "2026-11-20")

    def test_late_symbol_is_retried_then_flagged(self):
        rows = base_rows()
        last = rows["SPY"][-1][0]
        late = {"XLK": rows["XLK"][:-1]}
        calls = []

        def fetch(s):
            calls.append(s)
            r = late.get(s, rows[s])
            return r, r
        sleeps = []
        with mock.patch.object(dd, "expected_us_date", return_value=last):
            f = dd.fetch_all(fetch=fetch, waits=(1, 2), sleep=sleeps.append)
        self.assertEqual(sleeps, [1, 2])                      # 遅れた銘柄を時間をおいて2回取り直した
        self.assertEqual(calls.count("XLK"), 3)
        self.assertIn("XLK", f["quality"]["stale"])
        feat = dd.features(f["rows"], f["close"], f["quality"]["stale"])
        self.assertTrue(feat["XLK"]["stale"])
        self.assertIsNone(feat["XLK"]["c1"])                  # 古い日の動きを今日の動きとして出さない

    def test_us_series_cut_at_us_trading_day(self):
        rows = base_rows()
        last = rows["SPY"][-1][0]
        rows["CL=F"] = rows["CL=F"] + [("2099-01-01", 1.0)]  # 翌日の取引の途中の値
        with mock.patch.object(dd, "expected_us_date", return_value=last):
            f = dd.fetch_all(fetch=fetcher(rows), waits=())
        self.assertEqual(f["rows"]["CL=F"][-1][0], last)

    def test_cross_check_flags_mismatch(self):
        rows = base_rows()
        close = dict(rows)
        close["^GSPC"] = rows["SPY"][:-1] + [(rows["SPY"][-1][0], rows["SPY"][-2][1] * 1.05)]
        c = dd.cross_checks(rows, close)
        self.assertFalse(c[0]["ok"])


class HeavyAndMoversTest(unittest.TestCase):
    def test_contribution_names_the_driver(self):
        rows = base_rows(**{"8035.T": series(last=(1, -0.12), phase=40), "^N225": series(last=(1, -0.03), phase=41)})
        c = dd.contributions(rows, "^N225", "1306.T", dd.HEAVY_JP)
        self.assertEqual(c["d1"]["items"][0]["sym"], "8035.T")
        self.assertTrue(all(x["weight"] >= 0 for x in c["d1"]["items"]))   # マイナスの重みは使わない

    def test_movers_filter_large_today(self):
        t = int(datetime(2026, 11, 25, 21, 0, tzinfo=eb.timezone.utc).timestamp())
        old = t - 3 * 86400
        quotes = [
            {"symbol": "MU", "marketCap": 6.8e11, "regularMarketChangePercent": -4.6, "regularMarketTime": t, "shortName": "Micron"},
            {"symbol": "TINY", "marketCap": 2e9, "regularMarketChangePercent": 30.0, "regularMarketTime": t},       # 小型株は外す
            {"symbol": "OLD", "marketCap": 9e11, "regularMarketChangePercent": -9.0, "regularMarketTime": old},     # 古い日は外す
            {"symbol": "ADI", "marketCap": 1.6e11, "regularMarketChangePercent": 6.4, "regularMarketTime": t, "earningsTimestamp": t - 3600},
            {"symbol": "FLAT", "marketCap": 9e11, "regularMarketChangePercent": 0.5, "regularMarketTime": t},      # 動きが小さい
        ]
        mv, err = dd.fetch_movers("2026-11-25", get=lambda u: {"finance": {"result": [{"quotes": quotes if "gainers" in u else []}]}})
        self.assertEqual([m["sym"] for m in mv], ["ADI", "MU"])
        self.assertTrue(mv[0]["earnings"])
        self.assertEqual(err, [])



class LearnOnlyTest(unittest.TestCase):
    def test_learn_only_does_not_post(self):
        env = {k: "x" for k in eb._REQUIRED_ENV}
        env["LEARN_ONLY"] = "true"
        calls = []
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(eb, "fetch_rss", lambda: []), \
             mock.patch.object(eb, "fetch_news", lambda rss=(): []), \
             mock.patch.object(eb, "fetch_major_news", lambda rss=(): []), \
             mock.patch.object(eb, "publish_market_json", side_effect=lambda e: calls.append("market") or {"series": {}}), \
             mock.patch.object(dd, "publish_analysis", side_effect=lambda o, m: calls.append(("deep", sorted(o))) or True), \
             mock.patch.object(eb, "publish_to_github_pages", side_effect=AssertionError("公開しない")), \
             mock.patch.object(eb, "post_to_slack", side_effect=AssertionError("投稿しない")), \
             mock.patch.object(eb, "record_posted", side_effect=AssertionError("記録しない")):
            eb.main()
        self.assertEqual(calls[0], "market")
        self.assertEqual(calls[1][0], "deep")



class StripCodesTest(unittest.TestCase):
    def test_codes_removed_from_prose(self):
        t = dd.strip_codes("懸念（N10, N24）でエヌビディア（NVDA）と半導体(SMH)が下落。スプレッド（BAMLH0A0HYM2）。銀行（1631.T）。外需株（jp_ext）。")
        self.assertEqual(t, "懸念でエヌビディアと半導体が下落。スプレッド。銀行。外需株。")

    def test_bare_codes_become_names(self):
        with mock.patch.dict(dd.CODE_NAMES, {"XLK": "テクノロジー", "SMH": "半導体", "NVDA": "エヌビディア"}, clear=True):
            t = dd.strip_codes("集中（XLK, SMHの下落、NVDAなどの寄与）と摩擦（N4, N18, 外需の劣後）")
        self.assertEqual(t, "集中（テクノロジー, 半導体の下落、エヌビディアなどの寄与）と摩擦（外需の劣後）")

    def test_signal_ids_become_names_and_words_kept(self):
        self.assertIn("「均等加重 − 時価総額加重」", dd.strip_codes("breadth が改善"))
        self.assertEqual(dd.strip_codes("PER（株価収益率）は高い。"), "PER（株価収益率）は高い。")



class AskRetryTest(unittest.TestCase):
    def test_retries_once_on_unreadable_json(self):
        replies = iter(['{"ok": true, "issues": [{"problem": "途中で切れ', '{"ok": true, "issues": []}'])
        with mock.patch.object(eb, "_call_gemini", lambda *a, **k: next(replies)):
            self.assertEqual(dd._ask("p", None, "深掘り:査読"), {"ok": True, "issues": []})

    def test_gives_up_after_two(self):
        with mock.patch.object(eb, "_call_gemini", lambda *a, **k: "読めない"):
            with self.assertRaises(ValueError):
                dd._ask("p", None, "深掘り:査読")



class FactsTest(unittest.TestCase):
    def test_direction_words(self):
        feat = {"^TNX": {"date": "2026-11-25", "c1": -6.0, "c5": -22.0, "unit": "bp"},
                "JPY=X": {"date": "2026-11-25", "c1": -0.06, "c5": 0.4, "unit": "%"},
                "SPY": {"date": "2026-11-25", "c1": -0.29, "c5": 1.2, "unit": "%"}}
        t = dd.facts(feat)
        self.assertIn("米10年債利回り(2026-11-25): 1日 -6bp(低下)、5日 -22bp(低下)", t)
        self.assertIn("1日 -0.06%(ほぼ横ばい)、5日 +0.40%(円安)", t)
        self.assertIn("1日 -0.29%(下落)", t)



class StructureTest(unittest.TestCase):
    def test_clean_chain_downgrades_unsupported_status(self):
        dropped = []
        ch = dd.clean_chain([
            {"kind": "現象", "text": "半導体株が急落した。", "evidence": ["SMH"], "status": "データで確認"},
            {"kind": "きっかけ", "text": "AI投資の採算への疑問が報じられた。", "evidence": [], "status": "ニュースで確認"},
            {"kind": "下地", "text": "先導役は高値まで98%上げていた。", "evidence": ["SMH"], "status": "データで確認"},
            {"kind": "謎", "text": "持ち高が偏っていた。", "evidence": ["N3"], "status": "データで確認"},
        ], [98.0], {"SMH"}, dropped)
        self.assertEqual([c["status"] for c in ch], ["データで確認", "推測", "データで確認", "推測"])
        self.assertEqual(ch[3]["kind"], "下地")          # 知らない段の種類は「下地」に

    def test_move_types_unwind_and_risk_off(self):
        rows = base_rows(**{"SPY": series(last=(5, -0.04)), "SMH": series(last=(5, -0.15)), "TLT": series(last=(5, 0.03)),
                            "^TNX": yields(last_bp=(5, -25)), "HYG": series(last=(5, -0.03))})
        feat = dd.features(rows)
        sigs = dd.signals(rows)
        st = dd.structure(rows, feat, sigs)
        types = {t["type"]: t for t in st["types"]}
        self.assertIn("成長不安・リスク回避", types)
        self.assertIn("過熱の巻き戻し(ポジション解消)", types)
        self.assertEqual(sum(t["share"] for t in st["types"]), 100)
        txt = dd.structure_text(st)
        self.assertIn("動きの型", txt)
        self.assertIn("セクターどうしの相関", txt)



class DepthGuardTest(unittest.TestCase):
    def test_vague_steps_become_guess(self):
        ch = dd.clean_chain([{"kind": "下地", "text": "AIブームへの過度な期待があった。", "evidence": ["SMH"], "status": "データで確認"},
                             {"kind": "下地", "text": "半導体は高値まで98%上げていた。", "evidence": ["SMH"], "status": "データで確認"}],
                            [98.0], {"SMH"}, [])
        self.assertEqual([c["status"] for c in ch], ["推測", "データで確認"])

    def test_rule_conflict_sentence_dropped(self):
        with mock.patch.dict(dd.RULE_POS, {"S&P 500": 100, "日経平均": 100}, clear=True):
            dropped = []
            t = dd.scrub("S&P 500は200日線を下回り、待機シグナルが点灯しています。月末に待機に変わる可能性があります。", [200.0], dropped)
            self.assertEqual(t, "月末に待機に変わる可能性があります。")
            self.assertTrue(dropped[0].startswith("規則の判定と食い違う"))

    def test_chain_material_uses_numbers(self):
        st = {"leaders": [{"sym": "SMH", "name": "半導体", "run_to_high": 97.8, "from_high": -36.8}],
              "corr": {"us_20": 0.51, "us_prev": 0.15, "jp_20": 0.54, "jp_prev": 0.29},
              "vol": {"spy_rv20": 31.6, "spy_rv120": 16.8}, "crosses": {"SPY": [{"ma": 200, "dir": "下抜け", "date": "2026-11-19"}]},
              "havens": {"GC=F": {"c20": -12.73}, "TLT": {"c5": 2.52}}}
        cm = dd.chain_material(st)
        txt = " ".join(t for _, t, _ in cm)
        for want in ("+98%", "0.15→0.51", "16.8%→31.6%", "200日線", "-12.73%", "+2.52%"):
            self.assertIn(want, txt)



class RateLimitTest(unittest.TestCase):
    def test_retry_delay_parsed(self):
        import io
        import urllib.error
        body = b'{"error": {"code": 429, "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "41s"}]}}'
        e = urllib.error.HTTPError("u", 429, "Too Many", {}, io.BytesIO(body))
        self.assertEqual(eb._retry_delay(e), 43)
        self.assertEqual(eb._retry_delay(urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b"{}"))), 0)

    def test_429_skips_rest_and_goes_to_chief(self):
        rows = base_rows()
        feat, sigs = dd.features(rows), dd.signals(rows)
        call, calls = fake_ai(reviews_ok=True, fail=(dd.FLOW[1],))
        def call429(prompt, schema, label, models=None):
            if dd.FLOW[1] in label:
                calls.append(label)
                raise RuntimeError("全モデルで失敗しました(gemini-2.5-flash: HTTP 429 / gemini-2.5-flash-lite: HTTP 429)")
            return call(prompt, schema, label, models)
        with mock.patch.object(eb, "_call_gemini", call429), mock.patch.object(dd.time, "sleep") as sl:
            r = dd.run_ai(feat, sigs, [], {}, {})
        self.assertTrue(r["ok"])                          # チーフの統合はできた
        self.assertNotIn("深掘り:" + dd.BEAR[1], calls)   # 残りの役割は飛ばした
        self.assertIn("深掘り:チーフ", calls)
        sl.assert_called_with(60)



class DailyQuotaTest(unittest.TestCase):
    def test_per_day_quota_skips_model_without_waiting(self):
        import io
        import urllib.error
        calls, sleeps = [], []
        body = b'{"error": {"code": 429, "details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}, {"retryDelay": "3600s"}]}}'

        def fake_urlopen(req, timeout=None):
            model = req.full_url.split("/models/")[1].split(":")[0]
            calls.append(model)
            if model == "gemini-2.5-flash":
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(body))
            return io.BytesIO(json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}).encode())
        eb._EXHAUSTED.clear()
        eb._gemini_reset(600)
        try:
            with mock.patch.object(eb.urllib.request, "urlopen", side_effect=lambda r, timeout=None: _Ctx(fake_urlopen(r))), \
                 mock.patch.object(eb.time, "sleep", side_effect=sleeps.append):
                eb._call_gemini("p", None, "t", models=["gemini-2.5-flash", "gemini-2.5-flash-lite"])
                eb._call_gemini("p", None, "t", models=["gemini-2.5-flash", "gemini-2.5-flash-lite"])
        finally:
            eb._EXHAUSTED.clear()
        self.assertEqual(sleeps, [])                                   # 1日の上限では待たない
        self.assertEqual(calls.count("gemini-2.5-flash"), 1)          # 2回目は上限のモデルを使わない
        self.assertEqual(calls.count("gemini-2.5-flash-lite"), 2)


class ReuseAndGapTest(unittest.TestCase):
    def test_reuse_only_same_trading_day(self):
        prev = {"updated": "2026-11-26T21:29+09:00", "asof": {"us": "2026-11-25", "jp": "2026-11-26"},
                "ai": {"ok": True, "chief": {"headline": "x"}}}
        res = {"asof": {"us": "2026-11-25", "jp": "2026-11-26"}, "ai": {"ok": False, "errors": ["1日の上限"]}}
        self.assertTrue(dd.reuse_ai(res, prev))
        self.assertEqual(res["ai"]["chief"]["headline"], "x")
        self.assertEqual(res["ai"]["reused_from"], "2026-11-26T21:29+09:00")
        again = {"asof": dict(res["asof"]), "ai": {"ok": False}}
        dd.reuse_ai(again, dict(res, updated="2026-11-27T10:08+09:00"))
        self.assertEqual(again["ai"]["reused_from"], "2026-11-26T21:29+09:00")   # 最初の時刻を保つ
        other = {"asof": {"us": "2026-11-27", "jp": "2026-11-27"}, "ai": {"ok": False}}
        self.assertFalse(dd.reuse_ai(other, prev))      # 米国の取引日が違えば使わない
        evening = {"asof": {"us": "2026-11-25", "jp": "2026-11-27"}, "ai": {"ok": False}}
        self.assertTrue(dd.reuse_ai(evening, prev))     # 夕方(日本だけ新しい)は朝の見解を残す
        self.assertEqual(evening["ai"]["reused_asof"]["jp"], "2026-11-26")
        ok = {"asof": dict(prev["asof"]), "ai": {"ok": True, "chief": {"headline": "new"}}}
        self.assertFalse(dd.reuse_ai(ok, prev))

    def test_fill_null_daily_bar_from_hourly(self):
        from datetime import datetime, timezone
        off = 9 * 3600
        def ts(d, h):
            return int(datetime.fromisoformat(f"{d}T{h:02d}:00:00+09:00").timestamp())
        daily = {"meta": {"gmtoffset": off}, "timestamp": [ts("2026-11-25", 9), ts("2026-11-26", 9), ts("2026-11-27", 9)],
                 "indicators": {"quote": [{"close": [57011.6, None, 57493.6]}]}}
        now = datetime(2026, 11, 27, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(dd.null_days(daily, now), ["2026-11-26"])
        hourly = {"meta": {"gmtoffset": off}, "timestamp": [ts("2026-11-26", 9), ts("2026-11-26", 15)],
                  "indicators": {"quote": [{"close": [57990.5, 57440.4]}]}}
        rows, close = dd.fill_gaps([("2026-11-25", 28505.8)], [("2026-11-25", 57011.6)], ["2026-11-26"], hourly)
        self.assertEqual(close[-1], ("2026-11-26", 57440.4))   # その日の最後の1時間足
        self.assertAlmostEqual(rows[-1][1], 57440.4 * 0.5, places=3)


class _Ctx:
    def __init__(self, f):
        self.f = f

    def __enter__(self):
        return self.f

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    unittest.main()


class KeepDraftTest(unittest.TestCase):
    """2026-11-28: 改訂が主因と因果の段を空で返した。空になった所はチーフの案から戻す"""

    def test_keep_draft_fills_empty_parts(self):
        draft = {"us": {"summary": "米", "causes": [{"title": "A"}]}, "jp": {"causes": [{"title": "B"}]},
                 "root_cause": {"summary": "根本", "chain": [{"kind": "現象"}]}, "sectors": [{"name": "X"}]}
        rev = {"us": {"summary": "米2", "causes": []}, "jp": {"causes": [{"title": "B2"}]},
               "root_cause": {"summary": "根本2", "chain": []}, "sectors": []}
        out = dd.keep_draft(rev, draft)
        self.assertEqual(out["us"], {"summary": "米2", "causes": [{"title": "A"}]})
        self.assertEqual(out["jp"]["causes"], [{"title": "B2"}])               # 改訂の中身があればそちら
        self.assertEqual(out["root_cause"], {"summary": "根本2", "chain": [{"kind": "現象"}]})
        self.assertEqual(out["sectors"], [{"name": "X"}])
        self.assertEqual(dd.empty_parts(out), [])
        self.assertEqual(dd.empty_parts(rev), ["us", "root_cause"])

    def test_schema_requires_items(self):
        self.assertEqual(dd.CHIEF_SCHEMA["properties"]["us"]["properties"]["causes"]["minItems"], 1)
        self.assertEqual(dd.CHIEF_SCHEMA["properties"]["root_cause"]["properties"]["chain"]["minItems"], 2)


class FlowViewsTest(unittest.TestCase):
    """需給のデータごとの読み方と3つの立場の意見"""

    def test_clean_flow_views_scrubs_and_keeps_blocks(self):
        dropped = []
        v = {"options": {"read": "VIXは高い。", "analyst": "A", "trader": "T", "investor": "I"}, "cot": "壊れた値", "bad": {"read": "x"}}
        out = dd.clean_flow_views(v, {"pct": [], "num": []}, dropped)
        self.assertEqual(set(out), {"options"})
        self.assertEqual(out["options"]["trader"], "T")
        self.assertEqual(set(dd.FLOW_VIEW_SCHEMA["required"]), set(dd.FLOW_BLOCKS))
        self.assertIn("プロのトレーダー", dd._flow_view_prompt("■オプション市場\nVIX 23.81", {"headline": "見出し"}))
