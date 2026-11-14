"""EconoBotの表示・検証ロジックの試験(Gemini・NewsAPI・Slackは呼ばない)

使い方:  python -m unittest tests/test_econobot.py
生成したHTMLとSlack用JSONを見たい時: 環境変数 ECONOBOT_TEST_OUT=<フォルダ> を付けて実行する

ここの記事・JSONはすべて試験用の架空データ(2026-10-08朝の見出しの傾向を真似たもの)。
"""
import io
import json
import os
import re
import sys
import unittest
import urllib.error
from datetime import datetime
from html.parser import HTMLParser
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import econobot as eb  # noqa: E402

NOW = datetime(2026, 10, 8, 6, 2, tzinfo=eb.JST)


def A(source, title, desc, url):
    return {"source": source, "title": title, "description": desc, "url": url, "publishedAt": "2026-10-07T21:00:00Z"}


ECON_RAW = [
    A("The Wall Street Journal", "Stock Market Today: S&P 500 Hits New Record High",
      "The S&P 500 rose 0.85% to 7,840, a record close. The Nasdaq Composite gained 0.88% to 27,718.",
      "https://example.com/wsj-record"),
    A("Reuters", "Dow climbs as investors cheer rate-cut bets",
      "The Dow Jones Industrial Average added 0.69% on Tuesday. The 10-year Treasury yield fell 3 basis points to 4.08%.",
      "https://example.com/reuters-dow"),
    A("CNBC", "Option Care Health shares jump 22% on report of $5 billion takeover interest",
      "Option Care Health shares jumped 22% after a report said a buyer offered about $5 billion.",
      "https://example.com/cnbc-optioncare"),
    A("Bloomberg", "Nike slides after weak outlook",
      "Nike shares fell 1.3% after the company issued a weak holiday-quarter outlook.",
      "https://example.com/bbg-nike"),
    A("AP", "Five states will raise minimum wage in 2027",
      "Five states plan to raise their minimum wage on Jan. 1, 2027, affecting millions of workers.",
      "https://example.com/ap-wage"),
    A("MarketWatch", "Oil prices and the dollar",
      "WTI crude settled at $61.20 a barrel. The dollar fell 0.5% against the yen to 147.20.",
      "https://example.com/mw-oil"),
    A("CoinDesk", "Bitcoin steady near $121,500",
      "Bitcoin traded at $121,500, a 2.1% move from Tuesday's level.",
      "https://example.com/coindesk-btc"),
    A("New York Post", "Planes collide on LAX runway", "Two planes clipped wings while taxiing.",
      "https://example.com/nypost-lax"),
    A("Fox Business", "Starbucks sued for allegedly mislabeling 'sugar-free' protein drinks",
      "A lawsuit claims the drinks contain sugar.", "https://example.com/fox-sbux"),
    A("Business Insider", "We're live tracking the best October Prime Day deals",
      "Over 113 deals worth shopping.", "https://example.com/bi-primeday"),
    A("Barron's", "Small caps edge higher", "The Russell 2000 rose 0.55% to 2,450.",
      "https://example.com/barrons-russell"),  # 使える記事の10番(Prime Dayは除外されるため)
]
ECON = eb.usable_econ_articles(ECON_RAW)  # Prime Day(セール)はここで外れる → 9本。番号は1始まり

MAJOR_RAW = [
    A("AP", "Trump approves firing squad for military execution",
      "The president approved the first military execution by firing squad since 1961.",
      "https://example.com/ap-firing"),
    A("The Verge", "Scammers pose as AI chatbots to steal verification codes",
      "Fraudsters are using fake AI chatbot ads to steal personal data and one-time codes.",
      "https://example.com/verge-scam"),
    A("TechCrunch", "Meta joins effort to set rules for AI agents that trade with each other",
      "Meta joined an industry group writing standards for transactions between AI agents.",
      "https://example.com/tc-meta"),
    A("Reuters", "TSMC September revenue up 30%", "TSMC said September revenue rose 30% from a year earlier.",
      "https://example.com/reuters-tsmc"),
]
MAJOR = eb.usable_major_articles(MAJOR_RAW)

ECON_JSON = {
    # 2026-11-14:「米株」+「最高値」の見出しは門番(仕様4-1)で既定文に差し替わるため、値動きでない見出しに変更
    "headline": "利下げ観測で買い広がる",
    "key_points": [
        {"category": "株式", "text": "S&P500とナスダックが史上最高値を更新", "sources": [1]},
        {"category": "企業", "text": "Option Careが50億ドル買収報道で22%高", "sources": [3]},
        {"category": "企業", "text": "エヌビディアが12%急騰と報じられた", "sources": [1]},  # 作り話の% → 捨てる
        {"category": "雇用・物価", "text": "5州が2027年に最低賃金を引き上げ", "sources": [5]},
    ],
    "markets": [
        {"name": "S&P 500", "value_text": "7,840", "change_value": 0.85, "change_unit": "%",
         "quote": "The S&P 500 rose 0.85% to 7,840, a record close.", "source": 1},
        {"name": "ナスダック総合", "value_text": "27,718", "change_value": 0.88, "change_unit": "%",
         "quote": "The Nasdaq Composite gained 0.88% to 27,718.", "source": 1},
        {"name": "ダウ平均", "value_text": None, "change_value": 0.69, "change_unit": "%",
         "quote": "The Dow Jones Industrial Average added 0.69% on Tuesday", "source": 2},
        # 作り話:quoteが記事に無い → 出さない
        {"name": "WTI原油", "value_text": "$64.80", "change_value": -1.2, "change_unit": "%",
         "quote": "WTI crude fell 1.2% to $64.80 a barrel.", "source": 6},
        # 向きの食い違い:quoteはfell、change_valueは+0.5 → 出さない
        {"name": "ドル円", "value_text": "147.20", "change_value": 0.5, "change_unit": "%",
         "quote": "The dollar fell 0.5% against the yen to 147.20.", "source": 6},
        # 向きの語なし → 矢印なし「向きの記載なし」で出す
        {"name": "ビットコイン", "value_text": "$121,500", "change_value": 2.1, "change_unit": "%",
         "quote": "Bitcoin traded at $121,500, a 2.1% move from Tuesday's level.", "source": 7},
        # 途切れた数値 → 出さない
        {"name": "米10年債利回り", "value_text": "4.1", "change_value": None, "change_unit": "bp",
         "quote": "Treasury yields eased to 4.1...", "source": 2},
        # 下落カード(bp単位)。上の途切れ版が落ちた後にこちらが採用される
        {"name": "米10年債利回り", "value_text": "4.08%", "change_value": -3, "change_unit": "bp",
         "quote": "The 10-year Treasury yield fell 3 basis points to 4.08%.", "source": 2},
        # 実在しない出典番号 → 出さない
        {"name": "S&P 500", "value_text": "9,999", "change_value": 5.0, "change_unit": "%",
         "quote": "S&P rose 5%", "source": 42},
    ],
    "sections": {
        "stock": [
            {"text": "S&P500は0.85%上昇し7,840で最高値を更新した", "sources": [1]},
            {"text": "ダウ平均は51...ポイント上昇した", "sources": [2]},  # 途切れ数値 → 捨てる
            {"text": "ナイキは弱い見通しを受けて1.3%下落した", "sources": [4]},
            {"text": "NONE", "sources": [1]},  # NONE → 捨てる
            {"text": "出典の無い行", "sources": []},  # 出典なし → 捨てる
        ],
        "fed": [],
        "jobs": [{"text": "5州が2027年1月1日に最低賃金を引き上げる予定", "sources": [5]}],
        "earnings": [],
    },
}

MAJOR_JSON = {
    "items": [
        # 2026-11-14:connection(読者へのつながり)が必須になったため各項目に追加
        {"category": "政治・政策", "connection": "規制・政策", "title": "トランプ氏、銃殺刑による死刑執行を承認",
         "lead": "軍で1961年以来となる銃殺刑による死刑執行を承認した。",
         "bullets": [{"text": "1961年以来初めての軍の銃殺刑となる", "sources": [1]},
                     {"text": "大統領が承認したと報じられた", "sources": [1]}],
         "sources": [1]},
        {"category": "AI・テック", "connection": "産業・企業", "title": "AIチャットボット偽装の詐欺が拡大",
         "lead": "偽のAIチャットボット広告で個人情報や認証コードを盗む手口が広がっている。",
         "bullets": [{"text": "偽広告から個人情報とワンタイムコードを盗む", "sources": [2]},
                     {"text": "被害額は前年比300%増と報じられた", "sources": [2]}],  # 作り話の% → 捨てる
         "sources": [2]},
        {"category": "AI・テック", "connection": "産業・企業", "title": "Meta、AI同士の取引ルールづくりに参加",
         "lead": "AIエージェント同士の取引に関する業界標準づくりの団体に加わった。",
         "bullets": [{"text": "MetaがAIエージェント間取引の標準化団体に参加", "sources": [3]},
                     {"text": "TSMCの9月売上高は前年比30%増", "sources": [4]}],
         "sources": [3]},
    ]
}

NONE_JSON = {
    "headline": "NONE",
    "key_points": [{"category": "株式", "text": "None", "sources": [1]},
                   {"category": "株式", "text": "S&P500が最高値を更新", "sources": [1]}],
    "markets": [{"name": "ダウ平均", "value_text": "N/A", "change_value": None, "change_unit": "%",
                 "quote": "N/A", "source": 2}],
    "sections": {"stock": "NONE", "fed": None, "jobs": ["該当なし"], "earnings": [{"text": "該当なし。", "sources": [1]}]},
}

BROKEN = '{"headline": "米株、史上最高値を更新", "key_points": [{"category": "株式", "text": "S&P500とナス'


class VisibleText(HTMLParser):
    """表示されるテキストだけを集める(style・scriptの中身は除く)"""
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def visible(html_text):
    p = VisibleText()
    p.feed(html_text)
    return " ".join(p.parts)


BANNED = ["NONE", "None", "null", "N/A", "...ポイント", "undefined"]


def render(econ_raw, major_raw):
    econ = eb.parse_summary(econ_raw, ECON)
    major = eb.parse_major_news(major_raw, MAJOR)
    return econ, major, eb.generate_html(econ, ECON, major, MAJOR, now=NOW)


class TestEconobot(unittest.TestCase):
    def test_normal_page(self):
        econ, major, page = render(json.dumps(ECON_JSON, ensure_ascii=False), json.dumps(MAJOR_JSON, ensure_ascii=False))
        names = [c["name"] for c in econ["markets"]]
        # 8: 作り話(WTI)・9: 向き食い違い(ドル円)・途切れ・出典番号なしは落ち、5枚だけ残る(並びは固定順)
        self.assertEqual(names, ["S&P 500", "ナスダック総合", "ダウ平均", "米10年債利回り", "ビットコイン"])
        self.assertNotIn("WTI原油", page)
        self.assertNotIn("ドル円", page)
        self.assertNotIn("64.80", page)
        dirs = {c["name"]: c["direction"] for c in econ["markets"]}
        self.assertEqual(dirs["ビットコイン"], 0)  # 向きの記載なし
        self.assertEqual(dirs["ダウ平均"], 1)  # added → 上昇
        self.assertEqual(dirs["米10年債利回り"], -1)
        # 2026-11-14:画面に「bp」を出さない(仕様4-4)。3bpは0.03ポイントと表示する
        self.assertIn("−0.03ポイント", page)
        self.assertNotIn("bp", visible(page))
        self.assertIn("向きの記載なし", page)
        # 要点は作り話の12%が捨てられて3つ
        self.assertEqual(len(econ["key_points"]), 3)
        self.assertNotIn("12%", page)
        self.assertNotIn("300%", page)
        # 11: fed・earnings が空なら見出しごと出ない
        self.assertNotIn("FRB・金融政策", page)
        self.assertNotIn("企業決算", page)
        self.assertIn("物価・雇用", page)   # 2026-11-14 欄の名前を変更(仕様4-8)
        # 6: #major が主要ニュースの見出しブロックにある
        self.assertIn('id="major"', page)
        # 7: 表示テキストに禁止語が無い
        vt = visible(page)
        for w in BANNED:
            self.assertNotIn(w, vt, w)
        # 14: script無し、外部はGoogle Fontsのみ
        self.assertNotIn("<script", page)
        ext = re.findall(r'(?:href|src)="(https?://[^"]+)"', page)
        for u in ext:
            if "example.com" in u:
                continue  # 元記事へのリンク(読み込みではない)
            self.assertTrue(u.startswith(("https://fonts.googleapis.com", "https://fonts.gstatic.com")), u)

    def test_none_strings(self):
        econ, major, page = render(json.dumps(NONE_JSON, ensure_ascii=False), "")
        self.assertTrue(econ["ok"])
        self.assertEqual(econ["headline"], eb.DEFAULT_HEADLINE)
        self.assertEqual(econ["markets"], [])
        self.assertEqual(len(econ["key_points"]), 1)
        self.assertFalse(major["ok"])  # 主要ニュース失敗 → 英語見出しのみ
        self.assertIn('lang="en"', page)
        vt = visible(page)
        for w in BANNED:
            self.assertNotIn(w, vt, w)
        self.assertNotIn("取得失敗", page)

    def test_broken_json(self):
        econ, major, page = render(BROKEN, "```json\n" + json.dumps(MAJOR_JSON, ensure_ascii=False) + "\n```")
        self.assertFalse(econ["ok"])
        self.assertIn("要約準備中", page)
        self.assertIn("本日はAIによる要約を作れなかったため", page)
        self.assertIn("<details class=\"block sources\" open>", page)
        self.assertNotIn("今日の要点", page)
        self.assertTrue(major["ok"])  # 囲み付きJSONは読める
        vt = visible(page)
        for w in BANNED:
            self.assertNotIn(w, vt, w)

    def test_number_boundaries(self):
        """数字は「1つの数字として」一致した時だけ通す(0.5と0.55、784と7840を区別)"""
        self.assertEqual(ECON[9]["source"], "Barron's")
        self.assertLess(eb._num_pos("0.5", "rose 0.55% to"), 0)
        self.assertLess(eb._num_pos("784", "rose to 7840"), 0)
        self.assertLess(eb._num_pos("3", "fell 3.5 points"), 0)
        self.assertGreaterEqual(eb._num_pos("0.55", "rose 0.55%."), 0)
        self.assertGreaterEqual(eb._num_pos("0.69", "down -0.69%"), 0)
        j = {
            "headline": "小型株が上昇",
            "key_points": [
                {"category": "株式", "text": "ラッセル2000が0.5%上昇", "sources": [10]},   # 記事は0.55% → 捨てる
                {"category": "株式", "text": "ラッセル2000が0.55%上昇", "sources": [10]},  # 一致 → 残す
            ],
            "markets": [
                {"name": "ダウ平均", "value_text": None, "change_value": 0.5, "change_unit": "%",
                 "quote": "The Russell 2000 rose 0.55% to 2,450.", "source": 10},           # 0.5 vs 0.55 → 捨てる
                {"name": "S&P 500", "value_text": "784", "change_value": None, "change_unit": "%",
                 "quote": "The S&P 500 rose 0.85% to 7,840, a record close.", "source": 1},  # 784 vs 7840 → 捨てる
                {"name": "ナスダック総合", "value_text": "2,450", "change_value": 0.55, "change_unit": "%",
                 "quote": "The Russell 2000 rose 0.55% to 2,450.", "source": 10},           # カンマ入りでも一致 → 残す
            ],
            "sections": {"stock": [{"text": "ラッセル2000は0.5%上昇した", "sources": [10]}],  # 捨てる
                         "fed": [], "jobs": [], "earnings": []},
        }
        econ = eb.parse_summary(json.dumps(j, ensure_ascii=False), ECON)
        self.assertEqual([k["text"] for k in econ["key_points"]], ["ラッセル2000が0.55%上昇"])
        self.assertEqual([c["name"] for c in econ["markets"]], ["ナスダック総合"])
        self.assertEqual(econ["sections"]["stock"], [])

    def test_all_dropped_goes_to_pending(self):
        """照合で全部捨てられたら、見出しだけのページにせず「要約準備中」にする"""
        j = {"headline": "米株、史上最高値を更新",
             "key_points": [{"category": "株式", "text": "S&P500が9.9%上昇", "sources": [1]}],
             "markets": [{"name": "S&P 500", "value_text": "9,999", "change_value": 9.9, "change_unit": "%",
                          "quote": "S&P rose 9.9%", "source": 1}],
             "sections": {"stock": [], "fed": [], "jobs": [], "earnings": []}}
        econ, major, page = render(json.dumps(j, ensure_ascii=False), json.dumps(MAJOR_JSON, ensure_ascii=False))
        self.assertFalse(econ["ok"])
        self.assertIn("要約準備中", page)
        self.assertIn("本日はAIによる要約を作れなかったため", page)
        self.assertNotIn("米株、史上最高値を更新", page)

    def test_source_list_econ_only(self):
        """元記事一覧は10本に満たなくても、経済と無関係な記事で埋めない"""
        _, _, page = render(json.dumps(ECON_JSON, ensure_ascii=False), json.dumps(MAJOR_JSON, ensure_ascii=False))
        for w in ["LAX runway", "Starbucks", "Prime Day"]:
            self.assertNotIn(w, page)

    def test_headline_too_long(self):
        def h(text):
            j = dict(ECON_JSON, headline=text)
            return eb.parse_summary(json.dumps(j, ensure_ascii=False), ECON)["headline"]
        self.assertEqual(h("あ" * 25), "あ" * 25)                        # 30字までは残す
        self.assertEqual(h("い" * 12 + "、" + "う" * 25), "い" * 12)      # 30字超は読点で切る
        self.assertEqual(h("え" * 40), eb.DEFAULT_HEADLINE)              # 切れなければ既定文

    def test_gemini_calls(self):
        """13: 通常は経済1回+主要1回=2回。スキーマが400で拒否されると1回だけ送り直し、2回目は最初からスキーマ無し"""
        calls = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None, reject_schema=False):
            body = json.loads(req.data.decode())
            has_schema = "responseSchema" in body["generationConfig"]
            calls.append(has_schema)
            if reject_schema and has_schema:
                raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, None)
            out = {"candidates": [{"content": {"parts": [{"text": json.dumps(ECON_JSON)}]}}]}
            return Resp(json.dumps(out).encode())

        with mock.patch.object(eb.urllib.request, "urlopen", side_effect=lambda r, timeout=None: fake_urlopen(r, timeout)):
            eb._SCHEMA_REJECTED["value"] = False
            eb.summarize_with_gemini(ECON)
            eb.summarize_major_news(MAJOR)
        self.assertEqual(calls, [True, True])

        calls.clear()
        with mock.patch.object(eb.urllib.request, "urlopen", side_effect=lambda r, timeout=None: fake_urlopen(r, timeout, True)):
            eb._SCHEMA_REJECTED["value"] = False
            raw = eb.summarize_with_gemini(ECON)
            eb.summarize_major_news(MAJOR)
        self.assertEqual(calls, [True, False, False])
        self.assertTrue(eb.parse_summary(raw, ECON)["ok"])
        eb._SCHEMA_REJECTED["value"] = False

    def test_slack_payload(self):
        econ, major, _ = render(json.dumps(ECON_JSON, ensure_ascii=False), json.dumps(MAJOR_JSON, ensure_ascii=False))
        p = eb.build_slack_payload("https://shio-jpn.github.io/econobot/", econ, major, MAJOR, now=NOW)
        # 2026-11-14:数値の取得が無い(econ["today"]が無い)時は、従来どおり「朝刊|見出し」。
        # 「主な数値の上位3つ」のcontextは1段目(昨日の米国市場)と重なるため削除した(仕様8)
        self.assertEqual(p["text"], "米国経済 朝刊|利下げ観測で買い広がる")
        s = json.dumps(p, ensure_ascii=False)
        self.assertIn("#major|主要ニュースへ", s)
        self.assertIn("[規制・政策] トランプ氏", s)
        self.assertNotIn("WTI", s)
        self.assertNotIn("bp", s)
        self.assertFalse([b for b in p["blocks"] if b["type"] == "context" and "|" in b["elements"][0]["text"]])


def write_samples(out):
    """確認用のHTMLとSlack JSONを書き出す"""
    os.makedirs(out, exist_ok=True)
    cases = {
        "normal": (json.dumps(ECON_JSON, ensure_ascii=False), json.dumps(MAJOR_JSON, ensure_ascii=False)),
        "none": (json.dumps(NONE_JSON, ensure_ascii=False), ""),
        "broken": (BROKEN, json.dumps(MAJOR_JSON, ensure_ascii=False)),
    }
    for name, (er, mr) in cases.items():
        econ, major, page = render(er, mr)
        with open(os.path.join(out, f"{name}.html"), "w", encoding="utf-8") as f:
            f.write(page)
        p = eb.build_slack_payload("https://shio-jpn.github.io/econobot/", econ, major, MAJOR, now=NOW)
        with open(os.path.join(out, f"slack_{name}.json"), "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)


if __name__ == "__main__" or os.environ.get("ECONOBOT_TEST_OUT"):
    if os.environ.get("ECONOBOT_TEST_OUT"):
        write_samples(os.environ["ECONOBOT_TEST_OUT"])
if __name__ == "__main__":
    unittest.main()


class TrustedSourceTest(unittest.TestCase):
    def test_only_trusted_domains(self):
        import econobot as e
        ok = [{"url": "https://www.reuters.com/markets/x"}, {"url": "https://www.bbc.co.uk/news/business-1"},
              {"url": "https://apnews.com/article/y"}]
        ng = [{"url": "https://nypost.com/z"}, {"url": "https://fakereuters.com/a"},
              {"url": "https://news.google.com/rss/b"}, {"url": ""}]
        self.assertTrue(all(e._is_trusted(a) for a in ok))
        self.assertFalse(any(e._is_trusted(a) for a in ng))


class OfficialMarketsTest(unittest.TestCase):
    def test_card_values(self):
        # 2026-11-14:日付はカードごとに書かず、対象日と違う時だけ「10/7の値」と出す。利回りはbpをやめ「ポイント(前日 …%)」
        c = eb._official_card("S&P 500", "index", [("2026-10-07", 7801.77), ("2026-10-08", 7765.36)])
        self.assertEqual((c["value_text"], c["change"], c["direction"], c["source_name"], c["chg_text"], c["stale"]),
                         ("7,765.36", -0.47, -1, "FRED", "−0.47%", False))
        y = eb._official_card("米10年債利回り", "yield", [("2026-10-06", 5.27), ("2026-10-07", 5.28)])
        self.assertEqual((y["value_text"], y["chg_text"], y["direction"]), ("5.28%", "+0.01ポイント(前日 5.27%)", 1))
        old = eb._official_card("米2年債利回り", "yield", [("2026-10-06", 4.0), ("2026-10-07", 4.0)], "2026-10-08")
        self.assertEqual((old["chg_text"], old["stale"], old["date_label"]), ("前日と同じ", True, "10/7の値"))

    def test_merge_prefers_official_and_keeps_order(self):
        ai = [{"name": "S&P 500", "x": "ai"}, {"name": "ビットコイン", "x": "ai"}]
        off = [{"name": "ダウ平均", "x": "off"}, {"name": "S&P 500", "x": "off"}]
        m = eb.merge_markets(off, ai)
        self.assertEqual([(c["name"], c["x"]) for c in m],
                         [("S&P 500", "off"), ("ダウ平均", "off"), ("ビットコイン", "ai")])

    def test_render_official_card_without_article(self):
        econ = eb.parse_summary(json.dumps(ECON_JSON, ensure_ascii=False), ECON)
        econ["markets"] = eb.merge_markets(
            [eb._official_card("S&P 500", "index", [("2026-10-07", 7801.77), ("2026-10-08", 7765.36)])],
            econ["markets"])
        major = eb.parse_major_news(json.dumps(MAJOR_JSON, ensure_ascii=False), MAJOR)
        page = eb.generate_html(econ, ECON, major, MAJOR, now=NOW)
        text = visible(page)
        self.assertIn("7,765.36", text)
        sp_card = text.split("主な数値")[1].split("ナスダック")[0]
        self.assertNotIn("報道時点の値", sp_card)   # 公式の数値が記事由来のカードより優先される(旧:「FRED 10/8終値」の表示を確認)
        self.assertNotIn("値の記載なし", sp_card)


class IndexTrendTest(unittest.TestCase):
    def test_trend_row(self):
        rows = [("2025-10-15", 7000.0), ("2025-12-31", 6000.0), ("2026-09-13", 7500.0),
                ("2026-10-06", 8000.0), ("2026-10-12", 7900.0), ("2026-10-13", 7821.0)]
        r = eb.index_trend_row("S&P 500", rows)
        self.assertEqual(r["date"], "10/13")
        self.assertEqual(r["d1"], -1.0)                       # 7900→7821
        self.assertEqual(r["w1"], -2.24)                      # 10/6の8000から
        self.assertEqual(r["m1"], 4.28)                       # 9/13の7500から
        self.assertEqual(r["ytd"], 30.35)                     # 前年末6000から
        self.assertEqual(r["from_high"], -2.24)               # 1年の高値8000から

    def test_table_renders(self):
        econ = eb.parse_summary(json.dumps(ECON_JSON, ensure_ascii=False), ECON)
        econ["trends"] = [eb.index_trend_row("ダウ平均", [("2026-10-12", 100.0), ("2026-10-13", 101.0)])]
        major = eb.parse_major_news(json.dumps(MAJOR_JSON, ensure_ascii=False), MAJOR)
        text = visible(eb.generate_html(econ, ECON, major, MAJOR, now=NOW))
        self.assertIn("株価指数の推移", text)          # 2026-11-14「(公式統計)」は外し、出どころはフッターへ
        self.assertNotIn("(公式統計)", text)
        self.assertIn("1年の高値から:", text)         # tt-note。前日比の列(+1.00%)はカードと重なるため外した
        for w in BANNED:
            self.assertNotIn(w, text)


class TrendHighWindowTest(unittest.TestCase):
    def test_high_only_within_one_year(self):
        rows = [("2025-09-10", 9999.0), ("2025-12-31", 6000.0), ("2026-10-12", 7900.0), ("2026-10-13", 7821.0)]
        r = eb.index_trend_row("S&P 500", rows)   # 13か月前の9999は1年の高値に含めない
        self.assertEqual(r["from_high"], -1.0)

    def test_news_get_failure_is_empty(self):
        orig = eb.urllib.request.urlopen
        def boom(*a, **k):
            raise eb.urllib.error.URLError("down")
        eb.urllib.request.urlopen = boom
        try:
            self.assertEqual(eb._news_get(eb.urllib.request.Request("https://newsapi.org/x")), {"articles": []})
        finally:
            eb.urllib.request.urlopen = orig


class MacroTest(unittest.TestCase):
    # 2026-11-14:表(macro_row)を指標ごとのブロック(indicator_block)に作り直した(仕様4-8)。同じデータで値を確かめ直す
    def test_macro_rows(self):
        cpi = [("2025-07-01", 100.0), ("2025-08-01", 101.0), ("2026-07-01", 103.0), ("2026-08-01", 104.03)]
        r = eb.indicator_block("CPI", "CPIAUCSL", "price", cpi)
        self.assertEqual((r["value"], r["period"]), ("前年比 +3.0% ・ 前月比 +1.0%", "8月分"))
        self.assertEqual(r["prev"], "前回(7月分) 前年比 +3.0% ・ 前月比 ―")
        self.assertEqual(r["read"], "目標の2%を1.0ポイント上回る")
        nfp = [("2026-07-01", 158882.0), ("2026-08-01", 159015.0), ("2026-09-01", 159044.0)]
        r = eb.indicator_block("雇用者数", "PAYEMS", "mom_k", nfp)
        self.assertEqual((r["value"], r["prev"]), ("+2.9万人", "前回(8月分) +13.3万人"))
        down = [("2026-07-01", 159100.0), ("2026-08-01", 159015.0), ("2026-09-01", 158900.0)]
        self.assertEqual(eb.indicator_block("雇用者数", "PAYEMS", "mom_k", down)["value"], "−11.5万人")
        r = eb.indicator_block("CPI", "CPIAUCSL", "price", cpi[2:] + [("2026-09-01", 105.0)])  # 前年が無い月も残す
        self.assertEqual(r["value"], "前年比 ― ・ 前月比 +0.9%")

    def test_macro_table_renders(self):
        econ = eb.parse_summary(json.dumps(ECON_JSON, ensure_ascii=False), ECON)
        econ["macro"] = [eb.indicator_block("失業率", "UNRATE", "rate",
                                            [("2025-09-01", 4.1), ("2026-08-01", 4.1), ("2026-09-01", 4.2)])]
        major = eb.parse_major_news(json.dumps(MAJOR_JSON, ensure_ascii=False), MAJOR)
        page = eb.generate_html(econ, ECON, major, MAJOR, now=NOW)
        text = visible(page)
        self.assertIn("最新の指標", text)
        self.assertIn("4.2%", text)
        self.assertIn('data-series="UNRATE"', page)
        self.assertIn("1年前(4.1%)より0.1ポイント高い", text)


class StoryItemTest(unittest.TestCase):
    def test_title_body_items(self):
        j = json.loads(json.dumps(ECON_JSON))
        j["sections"]["stock"] = [
            {"title": "S&P500が最高値", "body": "S&P500は0.85%上昇し最高値を更新した。ハイテク株が買われた。", "sources": [1]},
            {"title": "作り話", "body": "ダウは9.99%急騰した。", "sources": [1]},       # 記事に無い% → 捨てる
            {"title": "見出しだけ", "body": "", "sources": [1]},                        # 本文なし → 捨てる
        ]
        econ = eb.parse_summary(json.dumps(j, ensure_ascii=False), ECON)
        st = econ["sections"]["stock"]
        self.assertEqual(len(st), 1)
        self.assertEqual((st[0]["title"], st[0]["text"][:6]), ("S&P500が最高値", "S&P500"))
        major = eb.parse_major_news(json.dumps(MAJOR_JSON, ensure_ascii=False), MAJOR)
        page = eb.generate_html(econ, ECON, major, MAJOR, now=NOW)
        self.assertIn('class="l-title"', page)
        self.assertIn("ハイテク株が買われた", visible(page))

    def test_content_used(self):
        a = {"title": "T", "description": "Desc.", "content": "Stocks rose 1.23% on Monday"}
        self.assertIn("1.23%", eb._body_of(a))
        self.assertEqual(eb._body_of({"title": "T", "description": "Same text here", "content": "Same text here"}), "Same text here")


# ========================================
# 2026-11-14 仕様(econobot-upgrade_仕様.md)9章Bの試験。記事・数値はすべて試験用の架空データ
# ========================================
def P(source, title, desc, url, pub):
    return {"source": source, "title": title, "description": desc, "url": url, "publishedAt": pub}


UP_ARTS = [
    P("AP", "Stocks slip as tech weighs", "The S&P 500 fell 0.42% on Friday as technology shares dropped. Nvidia lost 3.1%.",
      "https://example.com/up-ap", "2026-11-13T21:30:00Z"),                                     # 1 金曜の値動き
    P("Reuters", "Wall Street closes higher", "U.S. stocks rose on Thursday after inflation data. The Nasdaq gained 1.2%.",
      "https://example.com/up-reuters", "2026-11-12T22:00:00Z"),                                # 2 木曜の値動き
    P("CNBC", "Nvidia to report earnings", "Nvidia will report quarterly results on Nov. 20, the company said. "
      "Analysts expect $500 million in new revenue.", "https://example.com/up-cnbc", "2026-11-12T15:00:00Z"),  # 3
    P("Bloomberg", "Deal talk", "The company agreed to buy a rival for $50 million.",
      "https://example.com/up-bbg", "2026-11-12T10:00:00Z"),                                    # 4
    P("Federal Reserve", "Consumer prices rose 0.4% in October",
      "Consumer prices rose 0.4% in October from September. The next CPI report is due Dec. 10.",
      "https://example.com/up-frb", "2026-11-12T13:00:00Z"),                                    # 5
]
UP_MAJOR = [
    P("BBC News", "US and China agree chip export talks", "The two countries will hold talks on chip export controls.",
      "https://example.com/up-bbc-chip", "2026-11-13T12:00:00Z"),
    P("NPR", "Pope returns to Peru", "The pope visited his former parish.", "https://example.com/up-npr-pope",
      "2026-11-13T11:00:00Z"),
    P("CNBC", "Wall Street closes higher", "U.S. stocks rose on Thursday after inflation data. The Nasdaq gained 1.2%.",
      "https://example.com/up-reuters", "2026-11-12T22:00:00Z"),                                # 経済欄と同じURL
]
TD = "2026-11-13"   # 金曜


def up_json(**kw):
    j = {"headline": "AI関連株に売り", "market_move": None,
         "key_points": [{"category": "株式", "text": "エヌビディアが3.1%下落した", "why": None, "sources": [1]}],
         "sections": {"stock": [], "fed": [], "jobs": [], "earnings": []}, "upcoming": [], "markets": []}
    j.update(kw)
    return json.dumps(j, ensure_ascii=False)


def mkt(sp, fx=None, nasdaq=None, dow=None):
    """試験用の市場データ(series・trade_date)"""
    series = {"S&P 500": {"rows": sp, "src": "Yahoo Finance", "kind": "index"}}
    for name, rows in (("ドル円", fx), ("ナスダック総合", nasdaq), ("ダウ平均", dow)):
        if rows:
            series[name] = {"rows": rows, "src": "Yahoo Finance", "kind": "fx" if name == "ドル円" else "index"}
    return {"series": series, "trade_date": sp[-1][0]}


def page_for(econ, major=None, market=None):
    major = major or {"ok": True, "items": []}
    if market:
        econ["markets"] = eb.merge_markets(eb.build_market_cards(market), econ["markets"] if econ["ok"] else [])
        econ["trade_date"] = market["trade_date"]
        econ["today"] = eb.today_summary(market, econ["markets"])
    return eb.generate_html(econ, UP_ARTS, major, UP_MAJOR, now=NOW)


def today_why(page):
    m = re.search(r'<p class="today-why">(.*?)</p>', page, re.S)
    return visible(m.group(1)) if m else None


BASIC = mkt([("2026-11-12", 1000.0), ("2026-11-13", 995.8)], fx=[("2026-11-12", 154.0), ("2026-11-13", 154.41)])


class SpecUpgradeTest(unittest.TestCase):
    def test_b1_market_move_other_day(self):
        """B1:market_moveの曜日が対象日と違う → 「まだ取得できていません」+「参考:」"""
        mm = {"day": "木", "text": "主要な株価指数は木曜日に上昇した。", "quote": "U.S. stocks rose on Thursday after inflation data.", "sources": [2]}
        econ = eb.parse_summary(up_json(market_move=mm), UP_ARTS, TD)
        self.assertEqual((econ["market_move"]["day"], econ["market_move"]["same_day"]), ("木", False))
        w = today_why(page_for(econ, market=BASIC))
        self.assertIn("11月13日(金)の値動きの理由を書いた記事は、まだ取得できていません", w)
        self.assertIn("参考:木曜日の値動きについての報道", w)
        # 同じ曜日なら(a)の形
        mm2 = {"day": "金", "text": "S&P 500は0.42%下落した。", "quote": "The S&P 500 fell 0.42% on Friday as technology shares dropped.", "sources": [1]}
        econ2 = eb.parse_summary(up_json(market_move=mm2), UP_ARTS, TD)
        self.assertTrue(econ2["market_move"]["same_day"])
        w2 = today_why(page_for(econ2, market=BASIC))
        self.assertTrue(w2.startswith("値動きの理由(報道より):S&P 500は0.42%下落した。"), w2)

    def test_b2_weekday_not_in_quote(self):
        """B2:day="水"なのにquoteにWednesdayが無い → 「不明」扱い(参考は配信日で出す)"""
        mm = {"day": "水", "text": "主要な株価指数が上昇した。", "quote": "U.S. stocks rose on Thursday after inflation data.", "sources": [2]}
        econ = eb.parse_summary(up_json(market_move=mm), UP_ARTS, TD)
        self.assertEqual(econ["market_move"]["day"], "不明")
        self.assertIn("参考:11/12の報道", today_why(page_for(econ, market=BASIC)))

    def test_b3_quote_not_in_article(self):
        """B3:market_moveのquoteが元記事に無い → (c)の形(1文目だけ)"""
        mm = {"day": "金", "text": "株価が下落した。", "quote": "Stocks plunged 5% on Friday.", "sources": [1]}
        econ = eb.parse_summary(up_json(market_move=mm), UP_ARTS, TD)
        self.assertIsNone(econ["market_move"])
        w = today_why(page_for(econ, market=BASIC))
        self.assertIn("まだ取得できていません", w)
        self.assertNotIn("参考:", w)

    def test_b4_upcoming(self):
        """B4:元記事に無いquote/対象日以前/月名か日の数字が無い、はすべて出ない。正しい1件だけ出る"""
        q = "Nvidia will report quarterly results on Nov. 20, the company said."
        up = [
            {"date_iso": "2026-11-20", "event": "エヌビディアの決算発表", "quote": "Nvidia reports on Nov. 20.", "source": 3},
            {"date_iso": "2026-11-12", "event": "エヌビディアの決算発表", "quote": q, "source": 3},
            {"date_iso": "2026-11-21", "event": "エヌビディアの決算発表", "quote": q, "source": 3},
            {"date_iso": "2026-12-10", "event": "消費者物価(CPI)の発表", "quote": "The next CPI report is due Dec.", "source": 5},
            {"date_iso": "2026-11-20", "event": "エヌビディアの決算発表", "quote": q, "source": 3},
        ]
        econ = eb.parse_summary(up_json(upcoming=up), UP_ARTS, TD)
        self.assertEqual([(u["date"].isoformat(), u["event"]) for u in econ["upcoming"]], [("2026-11-20", "エヌビディアの決算発表")])
        page = page_for(econ, market=BASIC)
        sec = re.search(r'<section class="block" id="upcoming".*?</section>', page, re.S).group(0)
        self.assertIn("11月20日(金)", visible(sec))
        self.assertIn('class="src"', sec)
        econ0 = eb.parse_summary(up_json(upcoming=up[:4]), UP_ARTS, TD)
        self.assertNotIn('id="upcoming"', page_for(econ0, market=BASIC))

    def test_b5_money(self):
        """B5:「5億ドル」と$500 million → 通る。$50 million → 落ちる。「1兆2000億ドル」→ 落ちる"""
        self.assertIsNone(eb._nums_problem("新規売上は5億ドルの見込み", [3], UP_ARTS))
        self.assertIsNotNone(eb._nums_problem("買収額は5億ドル", [4], UP_ARTS))
        self.assertIsNotNone(eb._nums_problem("投資額は1兆2000億ドル", [3], UP_ARTS))
        st = [{"title": "買収", "what": "同社がライバルを5億ドルで買収することで合意した。", "sources": [4]},
              {"title": "買収", "what": "同社がライバルを5000万ドルで買収することで合意した。", "sources": [4]}]
        econ = eb.parse_summary(up_json(sections={"stock": st, "fed": [], "jobs": [], "earnings": []}), UP_ARTS, TD)
        self.assertEqual([l["text"] for l in econ["sections"]["stock"]], ["同社がライバルを5000万ドルで買収することで合意した。"])

    def test_b6_why_dropped_item_kept(self):
        """B6:whyだけが照合で落ちる → 項目は残り、s-whyが出ない"""
        st = [{"title": "エヌビディア下落", "what": "エヌビディアは3.1%下落した。", "why": "売上が9.9%減ったため。",
               "effect": "ハイテク株全体の重しになったとAPが報じた。", "sources": [1]}]
        econ = eb.parse_summary(up_json(sections={"stock": st, "fed": [], "jobs": [], "earnings": []}), UP_ARTS, TD)
        it = econ["sections"]["stock"][0]
        self.assertIsNone(it["why"])
        self.assertTrue(it["effect"])
        page = page_for(econ, market=BASIC)
        li = re.search(r'<li class="story-item">.*?</li>', page, re.S).group(0)
        self.assertNotIn("s-why", li)
        self.assertIn('<span class="s-effect">影響:', li)
        self.assertIn('<span class="story-date">11/13の報道</span>', li)

    def test_b7_major_dedupe_and_connection(self):
        """B7:経済欄と同じURLを出典に持つ項目、connectionが空の項目 → 出ない"""
        mm = {"day": "木", "text": "主要な株価指数が上昇した。", "quote": "U.S. stocks rose on Thursday after inflation data.", "sources": [2]}
        econ = eb.parse_summary(up_json(market_move=mm), UP_ARTS, TD)
        raw = json.dumps({"items": [
            {"category": "半導体", "connection": "円・貿易", "title": "米中、半導体の輸出規制で協議へ", "lead": "両国が半導体の輸出規制について協議する。",
             "bullets": [{"text": "輸出規制について話し合う", "sources": [1]}], "why_it_matters": None, "sources": [1]},
            {"category": "経済", "connection": "株式市場", "title": "米国株が上昇", "lead": "インフレ指標を受けて上昇した。",
             "bullets": [], "sources": [3]},
            {"category": "国際", "connection": "", "title": "教皇がペルーを訪問", "lead": "かつての教区を訪れた。",
             "bullets": [], "sources": [2]},
        ]}, ensure_ascii=False)
        major = eb.parse_major_news(raw, UP_MAJOR, eb.econ_used_urls(econ, UP_ARTS))
        self.assertEqual([it["title"] for it in major["items"]], ["米中、半導体の輸出規制で協議へ"])
        page = page_for(econ, major, BASIC)
        self.assertIn('<span class="tag">円・貿易</span>米中、半導体', page)

    def test_b8_major_empty_or_broken(self):
        """B8:{"items": []} → #majorも#major-detailも予備表示も出ない。壊れたJSON → 予備表示(_is_econを通る見出しだけ)"""
        econ = eb.parse_summary(up_json(), UP_ARTS, TD)
        m0 = eb.parse_major_news('{"items": []}', UP_MAJOR)
        self.assertEqual((m0["ok"], m0["items"]), (True, []))
        p0 = page_for(econ, m0, BASIC)
        for s in ('id="major"', 'id="major-detail"', "見出しのみ掲載"):
            self.assertNotIn(s, p0)
        mb = eb.parse_major_news('{"items": [{"title": "途中で', UP_MAJOR)
        self.assertFalse(mb["ok"])
        pb = page_for(eb.parse_summary(up_json(), UP_ARTS, TD), mb, BASIC)
        heads = re.search(r'<section class="block" id="major".*?</section>', pb, re.S).group(0)
        self.assertIn("Wall Street closes higher", heads)
        self.assertNotIn("Pope", heads)
        self.assertNotIn("chip export talks", heads)   # 経済の語を含まない見出しは予備表示にも出さない

    def test_b9_headline_gate(self):
        """B9:「S&P500が反発」→ 既定文。「エヌビディア株が急落」→ そのまま"""
        h = lambda x: eb.parse_summary(up_json(headline=x), UP_ARTS, TD)["headline"]
        self.assertEqual(h("S&P500が反発"), eb.DEFAULT_HEADLINE)
        self.assertEqual(h("米国株、続落"), eb.DEFAULT_HEADLINE)
        self.assertEqual(h("エヌビディア株が急落"), "エヌビディア株が急落")

    def test_b10_filler(self):
        """B10:「一方で、インフレ懸念もくすぶる。」→ その文だけ消える"""
        st = [{"title": "株価下落", "what": "S&P 500は0.42%下落した。一方で、インフレ懸念もくすぶる。", "sources": [1]}]
        econ = eb.parse_summary(up_json(sections={"stock": st, "fed": [], "jobs": [], "earnings": []}), UP_ARTS, TD)
        self.assertEqual(econ["sections"]["stock"][0]["text"], "S&P 500は0.42%下落した。")
        st2 = [{"title": "見通し", "what": "利下げが期待される。", "sources": [1]}]   # 全文が締めの言葉 → 項目ごと捨てる
        econ2 = eb.parse_summary(up_json(sections={"stock": st2, "fed": [], "jobs": [], "earnings": []}), UP_ARTS, TD)
        self.assertEqual(econ2["sections"]["stock"], [])

    def test_b11_cpi_missing_year_ago(self):
        """B11:CPIの前年同月が欠けた系列 → 前年比「―」、前月比、読み方の文"""
        rows = ([("2025-09-01", 100.0)]
                + [(f"2025-{m:02d}-01", 100.0 + m) for m in (11, 12)]
                + [(f"2026-{m:02d}-01", 105.0 + m * 0.1) for m in range(1, 8)]
                + [("2026-08-01", 109.67), ("2026-09-01", 110.0), ("2026-10-01", 110.44)])
        r = eb.indicator_block("消費者物価(CPI)", "CPIAUCSL", "price", rows)
        self.assertEqual(r["value"], "前年比 ― ・ 前月比 +0.4%")
        self.assertEqual(r["prev"], "前回(9月分) 前年比 +10.0% ・ 前月比 +0.3%")
        self.assertEqual(r["base"], "基準:FRBの物価目標 年2%(目安)")
        self.assertEqual(r["read"], "1年前の統計が欠けているため前年比は出せません。前月比は+0.4%で、前の月(+0.3%)より大きい")
        econ = eb.parse_summary(up_json(), UP_ARTS, TD)
        econ["macro"] = [r]
        page = page_for(econ, market=BASIC)
        block = re.search(r'<div class="ind" data-series="CPIAUCSL">.*?</div>\s*</div>', page, re.S).group(0)
        for c in ("ind-desc", "ind-prev", "ind-base", "ind-read"):
            self.assertIn(f'class="{c}"', block)
        self.assertIn("前月比 +0.4%", block)

    def test_b12_size_labels(self):
        """B12:250日の系列で N=60/30/10/3 → 4種類のラベル"""
        def rows_with(latest):
            closes, v = [1000.0], 1000.0
            for k in range(1, 251):
                v *= 1 + (0.01 * k if k % 2 else -0.01 * k) / 100
                closes.append(v)
            closes.append(v * (1 + latest / 100))
            return [(f"d{i:04d}", c) for i, c in enumerate(closes)]
        got = [eb.move_size(rows_with(lat)) for lat in (1.005, 1.755, 2.255, 2.425)]
        self.assertEqual([(g["n"], g["label"]) for g in got],
                         [(60, "小さな動き"), (30, "ふつうの動き"), (10, "大きめの動き"), (3, "この1年でも特に大きな動き")])
        self.assertIsNone(eb.move_size(rows_with(1.0)[:200]))   # 250日に満たなければ出さない

    def test_b13_jpy_sp(self):
        """B13:S&P +1.00%、ドル円 +0.50% → 円で見たS&P 500 +1.51%"""
        m = mkt([("2026-11-12", 1000.0), ("2026-11-13", 1010.0)], fx=[("2026-11-12", 150.0), ("2026-11-13", 150.75)])
        econ = eb.parse_summary(up_json(), UP_ARTS, TD)
        page = page_for(econ, market=m)
        self.assertEqual(econ["today"]["jpy_sp"]["text"], "+1.51%")
        self.assertIn("円で見たS&amp;P 500の目安:<strong>+1.51%</strong>", page)
        self.assertIn("1ドル=150.75円。前の日より0.75円の円安(ドルが高くなった)。", visible(page))
        p = eb.build_slack_payload("https://shio-jpn.github.io/econobot/", econ, {"ok": True, "items": []}, UP_MAJOR, now=NOW)
        self.assertEqual(p["text"], "米国株 S&P 500 +1.00%|1ドル=150.75円 円安|AI関連株に売り")
        self.assertIn("円で見たS&amp;P 500の目安 +1.51%", json.dumps(p, ensure_ascii=False))

    def test_b14_two_gemini_calls(self):
        """B14:build_outputs(本番と同じ流れ)で、Gemini呼び出しは経済1回+主要1回の2回。数値の取得が要約より先"""
        order, calls = [], []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            body = json.loads(req.data.decode())
            prompt = body["contents"][0]["parts"][0]["text"]
            calls.append("最新の終値の日は 11月13日(金)" in prompt)
            order.append("gemini")
            text = up_json() if "米国経済ニュースの編集者" in prompt else '{"items": []}'
            return Resp(json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode())

        def fake_market(now=None):
            order.append("market")
            return BASIC
        policy = {"lo": 3.75, "hi": 4.0, "as_of": TD, "changed": "2026-09-17", "delta": 0.25}
        with mock.patch.object(eb, "fetch_market_data", fake_market), \
             mock.patch.object(eb, "fetch_rss", lambda: []), \
             mock.patch.object(eb, "fetch_news", lambda rss=(): UP_ARTS), \
             mock.patch.object(eb, "fetch_major_news", lambda rss=(): UP_MAJOR), \
             mock.patch.object(eb, "fetch_macro", lambda: []), \
             mock.patch.object(eb, "fetch_policy_rate", lambda: policy), \
             mock.patch.object(eb, "publish_to_github_pages", side_effect=AssertionError("公開しない")), \
             mock.patch.object(eb, "post_to_slack", side_effect=AssertionError("投稿しない")), \
             mock.patch.object(eb.urllib.request, "urlopen", side_effect=fake_urlopen):
            eb._SCHEMA_REJECTED["value"] = False
            out = eb.build_outputs(now=NOW)
        self.assertEqual(order, ["market", "gemini", "gemini"])
        self.assertEqual(calls, [True, False])   # 経済用のプロンプトにだけ対象日が入る
        page = out["html"]
        self.assertIn('data-trade-date="2026-11-13"', page)
        self.assertIn("政策金利(FRBが決める金利):3.75〜4.00% ・ 最後の変更は2026年9月17日の利上げ(+0.25ポイント)", page)

    def test_page_rules(self):
        """A12・A14・A23・A24相当:bpが無い、色づけしないカード、フッター、禁止語"""
        mm = {"day": "金", "text": "S&P 500は0.42%下落した。", "quote": "The S&P 500 fell 0.42% on Friday as technology shares dropped.", "sources": [1]}
        kp = [{"category": "株式", "text": "エヌビディアが3.1%下落した", "why": "利回りが10bp上がり、ハイテク株が売られたため", "sources": [1]}]
        econ = eb.parse_summary(up_json(market_move=mm, key_points=kp), UP_ARTS, TD)
        self.assertIsNone(econ["key_points"][0]["why"])   # 10bpは記事に無い → whyだけ落ちる
        econ["markets"] = []
        page = page_for(econ, market=BASIC)
        vt = visible(page)
        body = vt.split("このページに出てきた用語")[0]
        self.assertNotIn("bp", body)
        self.assertIn('class="card neutral"', page)                # ドル円
        self.assertIn('class="card down"', page)                   # S&P 500
        self.assertIn("このページの作り方", vt)
        self.assertNotIn("直近24〜48時間", vt)
        for w in BANNED + eb.FILLER_WORDS:
            self.assertNotIn(w, vt, w)
        self.assertIn("株価指数は11月13日(金)の終値、ドル円は同じ日の米東部17時の値", vt)   # 2026-11-14 ドル円を「終値」と言わない
        self.assertIn("11月13日(金)の米国市場 ・ ニュースも同じ日までの報道", vt)
        gl = re.search(r'<section class="block" id="glossary".*?</section>', page, re.S).group(0)
        self.assertIn("S&amp;P 500", gl)


class FetchTest(unittest.TestCase):
    """2026-11-14:数値はYahooを主、FREDを予備。RSSを併用(ネットには出ない)"""
    @staticmethod
    def _res(itype, closes, reg, rmt=None, rmp=None, off=-18000):
        ts = [1794580200 - 86400 * (len(closes) - 1 - i) for i in range(len(closes))]   # 11/13 9:30 ET が最後
        return {"meta": {"instrumentType": itype, "gmtoffset": off, "symbol": "X",
                         "currentTradingPeriod": {"regular": {"start": reg[0], "end": reg[1]}},
                         "regularMarketTime": rmt, "regularMarketPrice": rmp},
                "timestamp": ts, "indicators": {"quote": [{"close": closes}]}}

    def test_yahoo_in_progress_bar(self):
        reg = (1794580200, 1794603600)   # 11/13 9:30〜16:00 ET
        during = datetime(2026, 11, 13, 18, 0, tzinfo=eb.timezone.utc)    # 13:00 ET(取引中)
        after = datetime(2026, 11, 13, 22, 0, tzinfo=eb.timezone.utc)     # 17:00 ET(引け後)
        idx = self._res("INDEX", [100.0, None, 101.0], reg)
        self.assertEqual(eb._parse_yahoo(idx, during)[-1][0], "2026-11-11")   # 取引中の足は使わない・Noneは飛ばす
        self.assertEqual(eb._parse_yahoo(idx, after)[-1], ("2026-11-13", 101.0))
        fut = self._res("FUTURE", [80.0, 81.0], (1794546000, 1794632340))     # 先物のregularは1日まるごと
        self.assertEqual(eb._parse_yahoo(fut, during)[-1], ("2026-11-13", 81.0))
        fx = self._res("CURRENCY", [150.0, 159.875], (1794528000, 1794614340), rmt=1794607185, rmp=159.686, off=0)
        self.assertEqual(eb._parse_yahoo(fx, after)[-1], ("2026-11-13", 159.686))   # 日足の遅れはregularMarketPriceで直す

    def test_yahoo_429_falls_back_to_fred(self):
        """Yahooが429の日もページは壊れず、FREDの値を日付つきで出す"""
        def boom(sym, rng="2y", now=None):
            raise urllib.error.HTTPError("https://query1.finance.yahoo.com/x", 429, "Too Many Requests", {}, None)
        fred = {"SP500": [("2026-11-11", 1000.0), ("2026-11-12", 1010.0)],
                "DEXJPUS": [("2026-11-05", 150.0), ("2026-11-06", 151.0)]}
        with mock.patch.object(eb, "_yahoo_rows", boom), \
             mock.patch.object(eb, "_treasury_csv", side_effect=urllib.error.URLError("試験では財務省に接続しない")), \
             mock.patch.object(eb, "_fred_cached", lambda sid, days: fred.get(sid, [])):
            m = eb.fetch_market_data()
        self.assertEqual((m["trade_date"], m["series"]["S&P 500"]["src"]), ("2026-11-12", "FRED"))
        cards = eb.build_market_cards(m)
        fx = [c for c in cards if c["name"] == "ドル円"][0]
        self.assertEqual((fx["stale"], fx["date_label"]), (True, "11/6の値"))
        econ = eb.parse_summary(up_json(), UP_ARTS, m["trade_date"])
        econ["markets"], econ["trade_date"] = cards, m["trade_date"]
        econ["today"] = eb.today_summary(m, cards)
        page = eb.generate_html(econ, UP_ARTS, {"ok": True, "items": []}, UP_MAJOR, now=NOW)
        self.assertIn('data-trade-date="2026-11-12"', page)
        self.assertIn("1ドル=151.00円(11/6の値)", visible(page))
        self.assertNotIn('class="today-jpy-sp"', page)   # 日付のそろわないドル円では円で見た値を出さない

    def test_rss_items(self):
        xml = (b'<?xml version="1.0"?><rss><channel><item><title>Fed &amp; rates</title>'
               b'<link>https://www.cnbc.com/a.html</link><description>&lt;p&gt;Rates rose 0.25%.&lt;/p&gt;</description>'
               b'<pubDate>Fri, 13 Nov 2026 16:06:10 -0500</pubDate></item>'
               b'<item><title>No date</title><link>https://www.cnbc.com/b.html</link></item></channel></rss>')
        items = eb._rss_items(xml, "CNBC")
        self.assertEqual((items[0]["title"], items[0]["description"], items[0]["publishedAt"]),
                         ("Fed & rates", "Rates rose 0.25%.", "2026-11-13T21:06:10Z"))
        self.assertEqual(items[1]["publishedAt"], "")   # 日時の無い記事はfetch_rssで落ちる
        self.assertEqual(eb._date_tag(items[0]), "(11/13 金) ")


class VerifierFixTest(unittest.TestCase):
    """2026-11-14 verifier指摘(ドル円の前日比・Slackの古い値)の試験"""
    # ---- 2026-11-14(3回目):試験の材料は保存した本物の応答(tests/fixtures/、11-14 05:00 UTC頃に取得)----
    # 日足の応答にはmeta.previousCloseが無い(1時間足の応答にだけある)。偽データは本物を削るだけで作り、項目を足さない
    FIX = os.path.join(os.path.dirname(__file__), "fixtures")
    NOW_UTC = datetime(2026, 11, 14, 5, 0, tzinfo=eb.timezone.utc)

    def _saved(self, name):
        with open(os.path.join(self.FIX, name), encoding="utf-8") as f:
            return json.load(f)["chart"]["result"][0]

    def _market(self, hourly_ok):
        """保存した本物の応答で fetch_market_data を通す。hourly_ok=False は1時間足だけを消した(取得失敗の)場合"""
        saved = {("^GSPC", "1d"): "yahoo_GSPC_1d_2y_2026-11-14.json", ("JPY=X", "1d"): "yahoo_JPYX_1d_2y_2026-11-14.json",
                 ("JPY=X", "60m"): "yahoo_JPYX_60m_1mo_2026-11-14.json"}
        calls = []

        def chart(sym, rng, interval, host="query1"):
            calls.append((sym, interval, host))
            if interval == "60m" and not hourly_ok:
                raise urllib.error.HTTPError("https://query1.finance.yahoo.com/x", 429, "Too Many Requests", {}, None)
            if (sym, interval) not in saved:
                raise urllib.error.HTTPError("https://query1.finance.yahoo.com/x", 404, "Not saved", {}, None)
            return self._saved(saved[(sym, interval)])
        with mock.patch.object(eb, "_yahoo_chart", chart), mock.patch.object(eb, "_fred_cached", lambda sid, days: []), \
             mock.patch.object(eb, "_treasury_csv", side_effect=urllib.error.URLError("試験では財務省に接続しない")):
            m = eb.fetch_market_data(now=self.NOW_UTC)
        m["fetched_at"] = "2026-11-14T07:42"
        return m, calls

    def _outputs(self, m):
        econ = eb.parse_summary(up_json(), UP_ARTS, m["trade_date"])
        econ["markets"] = eb.build_market_cards(m)
        econ["trade_date"] = m["trade_date"]
        econ["today"] = eb.today_summary(m, econ["markets"])
        page = eb.generate_html(econ, UP_ARTS, {"ok": True, "items": []}, UP_MAJOR, now=NOW)
        slack = eb.build_slack_payload("https://shio-jpn.github.io/econobot/", econ, {"ok": True, "items": []}, UP_MAJOR, now=NOW)
        return econ, page, slack

    def test_fx_hourly_from_saved_response(self):
        """1時間足あり(本物の応答)→ ドル円は 11/12 159.821 → 11/13 159.686(米東部17時直前の足)"""
        self.assertNotIn("previousClose", self._saved("yahoo_JPYX_1d_2y_2026-11-14.json")["meta"])   # 前提の確認
        m, calls = self._market(hourly_ok=True)
        fx = dict(m["series"]["ドル円"]["rows"])
        self.assertEqual((round(fx["2026-11-12"], 3), round(fx["2026-11-13"], 3)), (159.821, 159.686))
        self.assertTrue(m["series"]["ドル円"]["compare"])
        self.assertEqual(m["trade_date"], "2026-11-13")
        econ, page, slack = self._outputs(m)
        card = [c for c in econ["markets"] if c["name"] == "ドル円"][0]
        self.assertEqual(card["chg_text"], "−0.13円 円高")
        self.assertEqual(econ["today"]["yen"]["line"], "1ドル=159.69円。前の日より0.13円の円高(ドルが安くなった)。")
        self.assertEqual(econ["today"]["jpy_sp"]["text"], "−0.48%")   # (1−0.40%)×(1−0.08%)−1
        self.assertEqual(slack["text"], "米国株 S&P 500 −0.40%|1ドル=159.69円 円高|AI関連株に売り")

    def test_fx_hourly_missing_no_comparison(self):
        """1時間足が query1・query2 とも失敗(保存した応答から1時間足だけ消す)→ 値だけ出し、前日比・円高円安・円で見たS&P 500はどこにも出さない"""
        m, calls = self._market(hourly_ok=False)
        self.assertEqual([c[2] for c in calls if c[1] == "60m"], ["query1", "query2"])   # 取り直しは1回だけ
        self.assertFalse(m["series"]["ドル円"]["compare"])
        econ, page, slack = self._outputs(m)
        card = [c for c in econ["markets"] if c["name"] == "ドル円"][0]
        self.assertEqual((card["value_text"], card["chg_text"]), ("159.69円", "前の日との比較は取得できませんでした"))
        self.assertIsNone(econ["today"]["jpy_sp"])
        self.assertEqual(econ["today"]["yen"]["line"], "1ドル=159.69円。前の日との比較は取得できませんでした。")
        vt = visible(page)
        self.assertNotIn('class="today-jpy-sp"', page)
        self.assertNotIn("円で見たS&P 500", vt)
        fx_card = re.search(r'(<li class="card [^"]*" role="group" aria-label="ドル円.*?</li>)', page, re.S).group(1)
        chg = visible(re.search(r'(<span class="card-chg">.*?</span></span>)', fx_card, re.S).group(1))
        self.assertEqual(chg, "前の日との比較は取得できませんでした")   # 変化の行(説明文の「円安」は定型文なので対象外)
        for w in ("▲", "▼", "−0.04", "+0.04", "円高"):
            self.assertNotIn(w, visible(fx_card), w)
        today = visible(re.search(r'(<section class="block today".*?</section>)', page, re.S).group(1))
        for w in ("円高", "円安", "ほぼ変わらず"):
            self.assertNotIn(w, today, w)
        self.assertIn("前の日との比較は取得できませんでした", visible(fx_card))
        # Slackの出口すべて(通知の1行・本文・文字だけの再送)
        self.assertEqual(slack["text"], "米国株 S&P 500 −0.40%|1ドル=159.69円|AI関連株に売り")
        for out in (json.dumps(slack, ensure_ascii=False), eb._slack_text_only(slack, "https://x/")["text"]):
            for w in ("円高", "円安", "前日並み", "円で見た", "ほぼ変わらず"):
                self.assertNotIn(w, out, w)
            self.assertIn("前の日との比較は取得できませんでした", out)

    def test_slack_skips_stale_nasdaq_and_dates_stale_yen(self):
        """ナスダックだけ古い日はSlackの1段目に出さない。古いドル円は通知文にも日付を付ける"""
        m = mkt([("2026-11-12", 1000.0), ("2026-11-13", 990.0)], fx=[("2026-11-05", 150.0), ("2026-11-06", 151.0)],
                nasdaq=[("2026-11-11", 100.0), ("2026-11-12", 102.0)], dow=[("2026-11-12", 100.0), ("2026-11-13", 99.0)])
        econ = eb.parse_summary(up_json(), UP_ARTS, TD)
        page = page_for(econ, market=m)
        self.assertEqual(econ["today"]["stocks"], "米国株は下落。S&P 500 −1.00%、ダウ −1.00%。")
        self.assertEqual(econ["today"]["nasdaq_text"], "")
        p = eb.build_slack_payload("https://shio-jpn.github.io/econobot/", econ, {"ok": True, "items": []}, UP_MAJOR, now=NOW)
        s = json.dumps(p, ensure_ascii=False)
        self.assertNotIn("ナスダック +2.00%", s)
        self.assertEqual(p["text"], "米国株 S&P 500 −1.00%|1ドル=151.00円 円安(11/6の値)|AI関連株に売り")
        self.assertIn("ナスダック総合", visible(page))          # ページのカードには日付つきで残す
        self.assertIn("11/12の値", visible(page))

    def test_prev_word_for_holiday(self):
        """2年債:前の値が祝日をはさんだ日なら「前日」ではなく日付を書く"""
        c = eb._official_card("米2年債利回り", "yield", [("2026-11-10", 4.73), ("2026-11-12", 4.86)])
        self.assertEqual(c["chg_text"], "+0.13ポイント(11/10 4.73%)")
        c2 = eb._official_card("米10年債利回り", "yield", [("2026-11-13", 5.10), ("2026-11-16", 5.15)])   # 金→月
        self.assertEqual(c2["chg_text"], "+0.05ポイント(前日 5.10%)")


class AsofNoteTest(unittest.TestCase):
    """2026-11-14(3回目):WTI・ビットコインは取得時点の値。注記が「終値」と言う対象に入れない"""
    def test_note_does_not_call_wti_btc_close(self):
        td = "2026-11-13"
        m = {"trade_date": td, "fetched_at": "2026-11-14T07:42", "series": {
            "S&P 500": {"rows": [("2026-11-12", 1000.0), ("2026-11-13", 995.8)], "src": "Yahoo Finance", "kind": "index"},
            "米10年債利回り": {"rows": [("2026-11-12", 5.103), ("2026-11-13", 5.154)], "src": "Yahoo Finance", "kind": "yield"},
            "WTI原油": {"rows": [("2026-11-12", 88.74), ("2026-11-13", 88.56)], "src": "Yahoo Finance", "kind": "usd"},
            "ビットコイン": {"rows": [("2026-11-12", 71342.97), ("2026-11-13", 70000.0)], "src": "Yahoo Finance", "kind": "usd"}}}
        cards = eb.build_market_cards(m)
        note = eb.asof_note(cards, "11月13日(金)")
        closing = note.split("の終値")[0]
        for w in ("WTI", "ビットコイン"):
            self.assertNotIn(w, closing, note)
        self.assertNotIn("すべて", note)
        self.assertEqual(note, "株価指数・利回りは11月13日(金)の終値。WTI原油・ビットコインは取得時点の値")
        econ = eb.parse_summary(up_json(), UP_ARTS, td)
        econ["markets"], econ["trade_date"] = cards, td
        page = eb.generate_html(econ, UP_ARTS, {"ok": True, "items": []}, UP_MAJOR, now=NOW)
        for name in ("WTI原油", "ビットコイン"):
            card = re.search(r'(<li class="card [^"]*" role="group" aria-label="' + name + r'.*?</li>)', page, re.S).group(1)
            self.assertIn('<span class="card-date at-time">11/14 07:42(日本時間)時点の値。あとで変わることがあります</span>', card)
        # ビットコインの日足に空(None)があって前の日を使う時は、従来どおり日付の表示
        m["series"]["ビットコイン"]["rows"] = [("2026-11-11", 73964.47), ("2026-11-12", 71342.97)]
        btc = [c for c in eb.build_market_cards(m) if c["name"] == "ビットコイン"][0]
        self.assertEqual((btc["stale"], btc["date_label"], btc.get("provisional")), (True, "11/12の値", None))
        self.assertEqual(eb.asof_note(eb.build_market_cards(m), "11月13日(金)"),
                         "株価指数・利回りは11月13日(金)の終値。WTI原油は取得時点の値。日付などの表示があるカードは、その表示のとおり")


class TreasuryTest(unittest.TestCase):
    """2026-11-14:米2年債は米国財務省の日次金利を主、FRED(1〜2日遅れ)を予備にする。
    材料は保存した本物の応答(tests/fixtures/ の財務省CSV 2025・2026年分、FRED DGS2、Yahoo ^GSPC)。行を消すだけで場合を作る"""
    FIX = os.path.join(os.path.dirname(__file__), "fixtures")
    NOW_UTC = datetime(2026, 11, 14, 5, 0, tzinfo=eb.timezone.utc)

    def _text(self, name):
        with open(os.path.join(self.FIX, name), encoding="utf-8-sig") as f:
            return f.read()

    def _market(self, tsy):
        """tsy: "full"(保存したまま)/"no_trade_day"(2026年分から11/13の行だけ消す)/"fail"(財務省が取れない)"""
        csv26 = self._text("treasury_yield_curve_2026_2026-11-14.csv")
        if tsy == "no_trade_day":
            csv26 = "\n".join(l for l in csv26.splitlines() if not l.startswith("11/13/2026"))
        csvs = {2026: csv26, 2025: self._text("treasury_yield_curve_2025_2026-11-14.csv")}

        def treasury(year):
            if tsy == "fail":
                raise urllib.error.HTTPError("https://home.treasury.gov/", 503, "Service Unavailable", {}, None)
            return csvs[year]
        gspc = json.loads(self._text("yahoo_GSPC_1d_2y_2026-11-14.json"))["chart"]["result"][0]

        def chart(sym, rng, interval, host="query1"):
            if (sym, interval) == ("^GSPC", "1d"):
                return gspc
            raise urllib.error.HTTPError("https://query1.finance.yahoo.com/x", 404, "Not saved", {}, None)
        dgs2 = eb._parse_fred_csv(self._text("fred_DGS2_2026-11-14.csv"))
        with mock.patch.object(eb, "_yahoo_chart", chart), mock.patch.object(eb, "_treasury_csv", treasury), \
             mock.patch.object(eb, "_fred_cached", lambda sid, days: dgs2 if sid == "DGS2" else []):
            m = eb.fetch_market_data(now=self.NOW_UTC)
        return m, [c for c in eb.build_market_cards(m) if c["name"] == "米2年債利回り"][0]

    def test_saved_csv_has_expected_rows(self):
        """前提の確認:保存した本物のCSVに 11/13 4.88・11/12 4.86・11/10 4.73 があり、11/11(祝日)の行は無い"""
        rows = dict(eb._parse_treasury_csv(self._text("treasury_yield_curve_2026_2026-11-14.csv"), "2 Yr"))
        self.assertEqual((rows["2026-11-13"], rows["2026-11-12"], rows["2026-11-10"]), (4.88, 4.86, 4.73))
        self.assertNotIn("2026-11-11", rows)
        ten = dict(eb._parse_treasury_csv(self._text("treasury_yield_curve_2026_2026-11-14.csv"), "10 Yr"))
        self.assertEqual(ten["2026-11-13"], 5.15)

    def test_trade_day_row_present(self):
        """対象日の行がある → 4.88%、+0.02ポイント(前日 4.86%)、日付の表示なし"""
        m, c = self._market("full")
        self.assertEqual(m["trade_date"], "2026-11-13")
        self.assertEqual((m["series"]["米2年債利回り"]["src"], c["value_text"], c["chg_text"], c["stale"], c["date_label"]),
                         ("米国財務省", "4.88%", "+0.02ポイント(前日 4.86%)", False, ""))
        self.assertGreaterEqual(min(d for d, _ in m["series"]["米2年債利回り"]["rows"]), "2025-01-01")   # 前の年の分も入る(1年の範囲)
        self.assertTrue(c["range_text"].startswith("1年の範囲"))

    def test_trade_day_row_missing_uses_fred(self):
        """対象日の行がまだ無い(11/13の行だけ消す)→ FREDの値に日付つき"""
        m, c = self._market("no_trade_day")
        self.assertEqual((m["series"]["米2年債利回り"]["src"], c["value_text"], c["chg_text"], c["stale"], c["date_label"]),
                         ("FRED", "4.86%", "+0.13ポイント(11/10 4.73%)", True, "11/12の値"))

    def test_treasury_failure_uses_fred(self):
        """財務省が取れない → FREDの値に日付つき"""
        m, c = self._market("fail")
        self.assertEqual((m["series"]["米2年債利回り"]["src"], c["value_text"], c["stale"], c["date_label"]),
                         ("FRED", "4.86%", True, "11/12の値"))

    def test_footer_names_treasury(self):
        econ = eb.parse_summary(up_json(), UP_ARTS, TD)
        page = eb.generate_html(econ, UP_ARTS, {"ok": True, "items": []}, UP_MAJOR, now=NOW)
        self.assertIn("・数値:Yahoo Finance・米国財務省(米2年債利回り)の終値と米政府統計", visible(page))
