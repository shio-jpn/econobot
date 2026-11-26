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


if __name__ == "__main__":
    unittest.main()
