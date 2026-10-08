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
    "headline": "米株、史上最高値を更新",
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
        {"category": "政治・政策", "title": "トランプ氏、銃殺刑による死刑執行を承認",
         "lead": "軍で1961年以来となる銃殺刑による死刑執行を承認した。",
         "bullets": [{"text": "1961年以来初めての軍の銃殺刑となる", "sources": [1]},
                     {"text": "大統領が承認したと報じられた", "sources": [1]}],
         "sources": [1]},
        {"category": "AI・テック", "title": "AIチャットボット偽装の詐欺が拡大",
         "lead": "偽のAIチャットボット広告で個人情報や認証コードを盗む手口が広がっている。",
         "bullets": [{"text": "偽広告から個人情報とワンタイムコードを盗む", "sources": [2]},
                     {"text": "被害額は前年比300%増と報じられた", "sources": [2]}],  # 作り話の% → 捨てる
         "sources": [2]},
        {"category": "AI・テック", "title": "Meta、AI同士の取引ルールづくりに参加",
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
        self.assertIn("−" + "3bp", page)
        self.assertIn("向きの記載なし", page)
        # 要点は作り話の12%が捨てられて3つ
        self.assertEqual(len(econ["key_points"]), 3)
        self.assertNotIn("12%", page)
        self.assertNotIn("300%", page)
        # 11: fed・earnings が空なら見出しごと出ない
        self.assertNotIn("FRB・金融政策", page)
        self.assertNotIn("企業決算", page)
        self.assertIn("雇用・物価", page)
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
        j = dict(ECON_JSON, headline="あ" * 21)
        econ = eb.parse_summary(json.dumps(j, ensure_ascii=False), ECON)
        self.assertEqual(econ["headline"], eb.DEFAULT_HEADLINE)

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
        self.assertEqual(p["text"], "米国経済 朝刊|米株、史上最高値を更新")
        s = json.dumps(p, ensure_ascii=False)
        self.assertIn("S&amp;P 500 7,840 ▲+0.85%", s)
        self.assertIn("#major|主要ニュースへ", s)
        self.assertNotIn("WTI", s)
        ctx = [b for b in p["blocks"] if b["type"] == "context"][0]["elements"][0]["text"]
        self.assertEqual(ctx.count("|"), 2)  # 最大3つ


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
