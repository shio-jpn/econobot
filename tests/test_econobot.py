"""EconoBotの表示・検証ロジックの試験(Gemini・NewsAPI・Slackは呼ばない)

使い方:  python -m unittest tests/test_econobot.py
生成したHTMLとSlack用JSONを見たい時: 環境変数 ECONOBOT_TEST_OUT=<フォルダ> を付けて実行する

ここの記事・JSONはすべて試験用の架空データ(2026-10-08朝の見出しの傾向を真似たもの)。
"""
import base64
import io
import json
import os
import re
import sys
import unittest
import urllib.error
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import econobot as eb  # noqa: E402
import deep_dive  # noqa: E402
deep_dive.RETRY_WAITS = deep_dive.BACKUP_WAITS = ()   # 試験では、取れない銘柄の取り直しを待たない

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

    def test_failure_is_remembered_and_years_fetched_once(self):
        """11-14:失敗も覚えておき、2年債と10年債の照合で同じ年を取り直さない(財務省は1回18〜20秒かかるため)"""
        calls = []

        def treasury(year):
            calls.append(year)
            if year == 2026:
                raise urllib.error.HTTPError("https://home.treasury.gov/", 503, "Service Unavailable", {}, None)
            return self._text("treasury_yield_curve_2025_2026-11-14.csv")
        eb._TREASURY_CACHE.clear()
        with mock.patch.object(eb, "_treasury_csv", treasury):
            for col in ("2 Yr", "10 Yr"):
                with self.assertRaises(urllib.error.HTTPError):
                    eb.treasury_rows(col, now=self.NOW_UTC)
        eb._TREASURY_CACHE.clear()
        self.assertEqual(sorted(calls), [2025, 2026])

    def test_timeout_is_long_enough(self):
        """11-14実測で1回18〜20秒。上限が近いと遅い日にFREDの前日値へ戻る"""
        self.assertGreaterEqual(eb.TREASURY_TIMEOUT, 60)

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


class TimeoutResilienceTest(unittest.TestCase):
    """2026-11-17 本番の失敗(Geminiの返事待ちの時間切れ TimeoutError で全体が止まり、公開もSlack投稿もされなかった)の再発防止。
    例外は本物と同じ形にする:返事待ちの時間切れは TimeoutError('The read operation timed out')、
    接続の時間切れは URLError(reason=TimeoutError('timed out'))"""

    class Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fetch_mocks(self):
        policy = {"lo": 3.75, "hi": 4.0, "as_of": TD, "changed": "2026-09-17", "delta": 0.25}
        return [mock.patch.object(eb, "fetch_market_data", lambda now=None: BASIC),
                mock.patch.object(eb, "fetch_rss", lambda: []),
                mock.patch.object(eb, "fetch_news", lambda rss=(): UP_ARTS),
                mock.patch.object(eb, "fetch_major_news", lambda rss=(): UP_MAJOR),
                mock.patch.object(eb, "fetch_macro", lambda: []),
                mock.patch.object(eb, "fetch_policy_rate", lambda: policy)]

    def test_gemini_timeouts_still_publish_and_post(self):
        """Geminiが毎回時間切れ → 同じモデルで1回取り直し → 次のモデル → 全部だめでも、ページを作り、公開・投稿し、注意の1行と別の失敗通知を出す"""
        gemini_calls = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url
            if "generativelanguage" in url:
                gemini_calls.append((url.split("/models/")[1].split(":")[0], timeout))
                raise TimeoutError("The read operation timed out")
            raise AssertionError("ほかの通信はしない: " + url)
        published, posted, notified = [], [], []
        env = {k: "x" for k in eb._REQUIRED_ENV}
        patches = self._fetch_mocks() + [
            mock.patch.dict(os.environ, env),
            mock.patch.object(eb.urllib.request, "urlopen", side_effect=fake_urlopen),
            mock.patch.object(eb, "publish_to_github_pages", side_effect=lambda h: published.append(h) or "https://shio-jpn.github.io/econobot/"),
            mock.patch.object(eb, "post_to_slack", side_effect=lambda *a: posted.append(a)),
            mock.patch.object(eb, "notify_failure", side_effect=lambda stage, error: notified.append((stage, error))),
            # 2026-11-18:mainは投稿済みの記録の読み書きと8:00の待ちもするようになった。この試験はAIの失敗だけを見るので差し替える
            mock.patch.object(eb, "posted_today", lambda today: (False, True)),
            mock.patch.object(eb, "record_posted", lambda *a, **k: None),
            mock.patch.object(eb, "wait_for_post_time", lambda: 0)]
        for p in patches:
            p.start()
        try:
            eb._SCHEMA_REJECTED["value"] = False
            eb.main()   # 例外で止まらないこと
        finally:
            for p in patches:
                p.stop()
        models = [m for m, _ in gemini_calls]
        self.assertEqual(models, ["gemini-2.5-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash"] * 2)
        self.assertTrue(all(t == eb.GEMINI_TIMEOUT for _, t in gemini_calls))   # 待つ上限は120秒
        self.assertEqual(len(published), 1)
        self.assertEqual(len(posted), 1)
        page = published[0]
        self.assertIn("今日はAIの要約を作れませんでした(数字は通常どおり)。", visible(page))
        self.assertIn("米国株は下落。S&P 500 −0.42%", visible(page))      # 数字はそのまま
        self.assertIn('id="today"', page)
        self.assertNotIn("約1日遅れ", visible(page))                          # 11-17 verifier:AIの失敗を記事の遅れのせいにしない
        self.assertIn("今日はAIの要約を作れなかったため、値動きの理由は載せていません。", visible(page))
        econ, major, major_articles = posted[0][1], posted[0][2], posted[0][3]
        slack = eb.build_slack_payload("https://shio-jpn.github.io/econobot/", econ, major, major_articles, now=NOW)
        s = json.dumps(slack, ensure_ascii=False)
        self.assertIn("今日はAIの要約を作れませんでした(数字は通常どおり)。", s)
        self.assertIn("S&amp;P 500 −0.42%", s)
        self.assertIn("ページで数字と見出しを見る", s)
        self.assertNotIn("理由・指標・今後の予定", s)
        self.assertEqual(len(notified), 1)                                    # 投稿とは別の失敗通知
        self.assertIn("AIの要約", notified[0][0])
        self.assertIn("TimeoutError", notified[0][1])

    def test_gemini_time_budget(self):
        """Geminiに使える時間の合計を超えそうな時は、呼ばずにあきらめる(実行全体の時間の上限を決めるため)"""
        calls = []
        with mock.patch.object(eb, "GEMINI_BUDGET", 10), \
             mock.patch.object(eb.urllib.request, "urlopen", side_effect=lambda r, timeout=None: calls.append(1)):
            eb._GEMINI_CLOCK["start"] = None
            with self.assertRaises(RuntimeError):
                eb.summarize_with_gemini(UP_ARTS)
        eb._GEMINI_CLOCK["start"] = None
        self.assertEqual(calls, [])

    def _gh(self, applied_on_timeout):
        """GitHubの contents API。1回目のPUTが返事待ちで時間切れ。applied_on_timeout=True はサーバー側では反映済みの場合"""
        state = {"content": b"<html>old</html>", "sha": "sha-old"}
        log = []

        def fake_urlopen(req, timeout=None):
            m = req.get_method()
            log.append(m)
            if m == "GET":
                body = {"sha": state["sha"], "encoding": "base64",
                        "content": base64.encodebytes(state["content"]).decode()}   # 本物は60字ごとに改行が入る
                return self.Resp(json.dumps(body).encode())
            sent = json.loads(req.data.decode())
            if log.count("PUT") == 1:
                if applied_on_timeout:
                    state.update(content=base64.b64decode(sent["content"]), sha="sha-new")
                raise TimeoutError("The read operation timed out")
            self.assertEqual(sent.get("sha"), state["sha"])
            state.update(content=base64.b64decode(sent["content"]), sha="sha-new2")
            return self.Resp(json.dumps({"content": {"sha": "sha-new2"}, "commit": {"sha": "c"}}).encode())
        with mock.patch.object(eb, "GITHUB_REPO", "shio-jpn/econobot"), mock.patch.object(eb, "GITHUB_TOKEN", "t"), \
             mock.patch.object(eb.urllib.request, "urlopen", side_effect=fake_urlopen):
            url = eb.publish_to_github_pages("<html>new</html>")
        return url, log, state

    def test_publish_timeout_retries_once(self):
        """公開が1回時間切れ(反映されていない)→ 確かめてから1回だけ取り直す"""
        url, log, state = self._gh(applied_on_timeout=False)
        self.assertEqual(log, ["GET", "PUT", "GET", "PUT"])
        self.assertEqual(state["content"], b"<html>new</html>")
        self.assertEqual(url, "https://shio-jpn.github.io/econobot/")

    def test_publish_timeout_already_applied_no_double_commit(self):
        """公開の返事が時間切れでも、実は反映済みなら取り直さない(二重のコミットを作らない)"""
        url, log, state = self._gh(applied_on_timeout=True)
        self.assertEqual(log, ["GET", "PUT", "GET"])
        self.assertEqual(state["sha"], "sha-new")

    def test_slack_connect_failure_retries_once(self):
        """Slackへ送る前の失敗(接続の時間切れ)→ 届いていないので1回だけ取り直す"""
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(json.loads(req.data.decode())["text"])
            if len(calls) == 1:
                raise urllib.error.URLError(TimeoutError("timed out"))
            return self.Resp(b"ok")
        econ = eb.parse_summary(up_json(), UP_ARTS, TD)
        with mock.patch.object(eb, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/x"), \
             mock.patch.object(eb.urllib.request, "urlopen", side_effect=fake_urlopen):
            eb.post_to_slack("https://shio-jpn.github.io/econobot/", econ, {"ok": True, "items": []}, UP_MAJOR)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])

    def test_slack_read_timeout_not_resent(self):
        """Slackの返事待ちの時間切れ → 届いた可能性があるので送り直さない(二重投稿を防ぐ)。失敗として知らせる"""
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            raise TimeoutError("The read operation timed out")
        econ = eb.parse_summary(up_json(), UP_ARTS, TD)
        with mock.patch.object(eb, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/x"), \
             mock.patch.object(eb.urllib.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaises(RuntimeError):
                eb.post_to_slack("https://shio-jpn.github.io/econobot/", econ, {"ok": True, "items": []}, UP_MAJOR)
        self.assertEqual(len(calls), 1)

    def test_every_network_call_times_out(self):
        """取得(NewsAPI・RSS・Yahoo・FRED・財務省)もGeminiも、すべての通信が時間切れでも build_outputs はページを返す"""
        hosts = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            hosts.append(urllib.parse.urlparse(url).hostname)
            raise TimeoutError("The read operation timed out")
        with mock.patch.object(eb, "NEWS_API_KEY", "k"), \
             mock.patch.object(eb.urllib.request, "urlopen", side_effect=fake_urlopen):
            eb._SCHEMA_REJECTED["value"] = False
            out = eb.build_outputs(now=NOW)
        self.assertTrue(out["html"].startswith("<!DOCTYPE html>"))
        self.assertEqual(len(out["ai_errors"]), 2)
        self.assertIn("今日はAIの要約を作れませんでした(数字は通常どおり)。", visible(out["html"]))
        for h in ("newsapi.org", "search.cnbc.com", "query1.finance.yahoo.com", "fred.stlouisfed.org",
                  "home.treasury.gov", "generativelanguage.googleapis.com"):
            self.assertIn(h, hosts)


class PostTimeTest(unittest.TestCase):
    """2026-11-18:JST 8:00に公開・投稿し、その日の投稿済みを state/last_posted.txt に記録して二重投稿を防ぐ。
    時計と待ちは差し替える(実際には待たない)。GitHubの応答は既存の試験と同じ形(sha・encoding・60字ごとに改行したcontent)"""

    class Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    # 2026-11-27: 投稿の時刻を8:00 → 7:00(取得 7:25 → 6:25)に変えた。ここの流れの試験(待ち・二重投稿の防止・記録)は
    # 時刻の値に依らないので、書いた時の設定(8:00・7:25・予備8:10)に差し替えて確かめる。今の設定は NewScheduleTest で確かめる
    def setUp(self):
        labels = dict(eb._CRON_LABEL)
        labels["10 8 * * *"] = "予備の起動(JST 8:10の予定)"
        self._ps = [mock.patch.object(eb, "POST_HOUR", 8), mock.patch.object(eb, "FETCH_AFTER", (7, 25)),
                    mock.patch.object(eb, "EARLY_LIMIT_HOUR", 7), mock.patch.object(eb, "_CRON_LABEL", labels)]
        for p in self._ps:
            p.start()

    def tearDown(self):
        for p in self._ps:
            p.stop()

    def _clock(self, h, m, s=0, day=18):
        state = {"now": datetime(2026, 11, day, h, m, s, tzinfo=eb.JST), "sleeps": []}

        def sleep(sec):
            state["sleeps"].append(sec)
            state["now"] = state["now"] + eb.timedelta(seconds=sec)
        return state, [mock.patch.object(eb, "_now_jst", lambda: state["now"]), mock.patch.object(eb, "_sleep", sleep)]

    def test_wait_from_0730(self):
        """7:30の起動 → 8:00:00まで待つ(1分ごとに時計を見直す)"""
        st, ps = self._clock(7, 30)
        for p in ps:
            p.start()
        try:
            waited = eb.wait_for_post_time()
        finally:
            for p in ps:
                p.stop()
        self.assertEqual(waited, 1800)
        self.assertEqual(st["now"], datetime(2026, 11, 18, 8, 0, 0, tzinfo=eb.JST))
        self.assertTrue(all(x <= 60 for x in st["sleeps"]))

    def test_no_wait_after_8_or_before_7(self):
        """8:20の起動はすぐ。6:30の起動(手動・設定の誤り)は待たない(待つのは最長1時間)"""
        for h, m in ((8, 20), (8, 0), (6, 30)):
            st, ps = self._clock(h, m)
            for p in ps:
                p.start()
            try:
                self.assertEqual(eb.wait_for_post_time(), 0, (h, m))
            finally:
                for p in ps:
                    p.stop()
            self.assertEqual(st["sleeps"], [])

    # ---- mainの流れ ----
    def _run_main(self, h, m, record=None, env=None, gh_fail=None, appear_during_wait=False,
                  day=18, slack_exc=None, build_minutes=0, build_exc=None):
        """record:state/last_posted.txt の中身(Noneなら無い=404)。
        gh_fail:"read"(GETが時間切れ)/"read_urlerror"(つながらない)/"read_502"(502でHTMLが返る)/
                "read_badb64"(contentがbase64として読めない)/"write"(PUTが500)。readの失敗は記録を書く前の確認のGETにも起きる
        slack_exc:post_to_slackが投げる例外。build_minutes:取得・要約にかかる分(時計を進める)"""
        st, ps = self._clock(h, m, day=day)
        files = {}
        if record is not None:
            files["state/last_posted.txt"] = {"content": record.encode(), "sha": "sha-state"}
        log, published, posted, notified, built = [], [], [], [], []

        def fake_urlopen(req, timeout=None):
            url, meth = req.full_url, req.get_method()
            self.assertTrue(url.startswith("https://api.github.com/repos/shio-jpn/econobot/contents/state/last_posted.txt"), url)
            log.append(meth)
            if meth == "GET":
                if gh_fail == "read":
                    raise TimeoutError("The read operation timed out")
                if gh_fail == "read_urlerror":
                    raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
                if gh_fail == "read_502":
                    raise urllib.error.HTTPError(url, 502, "Bad Gateway", {"Content-Type": "text/html"},
                                                 io.BytesIO(b"<html><body><h1>502 Bad Gateway</h1></body></html>"))
                if gh_fail == "read_badb64":
                    return self.Resp(json.dumps({"sha": "sha-x", "encoding": "base64", "content": "%%%not-base64%%%"}).encode())
                if appear_during_wait and st["sleeps"]:
                    files["state/last_posted.txt"] = {"content": b"2026-11-18 08:00:01 JST \xe4\xba\x88\xe5\x82\x99\n", "sha": "s2"}
                f = files.get("state/last_posted.txt")
                if not f:
                    raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
                return self.Resp(json.dumps({"sha": f["sha"], "encoding": "base64",
                                             "content": base64.encodebytes(f["content"]).decode()}).encode())
            if gh_fail == "write":
                raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, None)
            sent = json.loads(req.data.decode())
            files["state/last_posted.txt"] = {"content": base64.b64decode(sent["content"]), "sha": "sha-new"}
            return self.Resp(json.dumps({"content": {"sha": "sha-new"}, "commit": {"sha": "c"}}).encode())

        def fake_build():
            built.append(st["now"])
            st["now"] = st["now"] + eb.timedelta(minutes=build_minutes)
            if build_exc:
                raise build_exc
            econ = eb.parse_summary(up_json(), UP_ARTS, TD)
            return {"html": "<!DOCTYPE html><html><body><p>page</p></body></html>", "econ": econ,
                    "major": {"ok": True, "items": []}, "major_articles": [], "ai_errors": []}
        base_env = {k: "x" for k in eb._REQUIRED_ENV}
        base_env.update({"GITHUB_REPOSITORY": "shio-jpn/econobot", "EVENT_NAME": "", "SCHEDULE_CRON": "", "FORCE": ""})
        base_env.update(env or {})
        patches = ps + [
            mock.patch.dict(os.environ, base_env),
            mock.patch.object(eb, "GITHUB_REPO", "shio-jpn/econobot"),
            mock.patch.object(eb.urllib.request, "urlopen", side_effect=fake_urlopen),
            mock.patch.object(eb, "build_outputs", fake_build),
            mock.patch.object(eb, "publish_to_github_pages", side_effect=lambda h: published.append((st["now"], h)) or "https://shio-jpn.github.io/econobot/"),
            mock.patch.object(eb, "post_to_slack", side_effect=lambda *a: (posted.append(st["now"]), slack_exc and (_ for _ in ()).throw(slack_exc))),
            mock.patch.object(eb, "notify_failure", side_effect=lambda stage, error: notified.append((stage, error)))]
        err = None
        for p in patches:
            p.start()
        try:
            eb.main()
        except Exception as e:   # mainは失敗を知らせてから例外を投げ直す(workflowを失敗にするため)
            err = e
        finally:
            for p in patches:
                p.stop()
        rec = files.get("state/last_posted.txt", {}).get("content", b"").decode()
        return {"log": log, "published": published, "posted": posted, "notified": notified, "built": built,
                "record": rec, "sleeps": st["sleeps"], "error": err}

    # 2026-11-18(2回目):cron-job.orgはやめ、scheduleを2:17・3:47・5:17・予備8:10にした。起動の種類は github.event.schedule で分かる
    CRON = {"EVENT_NAME": "schedule", "SCHEDULE_CRON": "17 5 * * *"}     # 5:17の早い起動(遅れて7:30などに来ることもある)
    EARLY1 = {"EVENT_NAME": "schedule", "SCHEDULE_CRON": "17 2 * * *"}
    EARLY2 = {"EVENT_NAME": "schedule", "SCHEDULE_CRON": "47 3 * * *"}
    BACKUP = {"EVENT_NAME": "schedule", "SCHEDULE_CRON": "10 8 * * *"}
    MANUAL = {"EVENT_NAME": "workflow_dispatch"}

    def test_0730_dispatch_posts_at_8(self):
        """7:30の起動 → 取得・要約を済ませ、8:00:00に公開・投稿し、記録を書く"""
        r = self._run_main(7, 30, env=self.CRON)
        eight = datetime(2026, 11, 18, 8, 0, 0, tzinfo=eb.JST)
        self.assertEqual(r["built"], [datetime(2026, 11, 18, 7, 30, tzinfo=eb.JST)])
        self.assertEqual([t for t, _ in r["published"]], [eight])
        self.assertEqual(r["posted"], [eight])
        self.assertEqual(r["record"], "2026-11-18 投稿 2026-11-18 08:00:00 JST 早い起動(JST 5:17の予定)\n")
        self.assertIn("<!-- 起動: 早い起動(JST 5:17の予定) JST 2026-11-18 07:30 -->", r["published"][0][1])
        self.assertEqual(r["notified"], [])

    def test_0820_schedule_posts_now(self):
        """8:20の起動(予備のschedule)→ 待たずに公開・投稿"""
        r = self._run_main(8, 20, env=self.BACKUP)
        self.assertEqual(r["sleeps"], [])
        self.assertEqual(len(r["posted"]), 1)
        self.assertTrue(r["record"].startswith("2026-11-18 投稿 2026-11-18 08:20:00 JST 予備の起動"))

    def test_already_posted_today_does_nothing(self):
        """今日の分が記録済み → 取得も公開も投稿もせず、正常に終わる"""
        r = self._run_main(8, 12, record="2026-11-18 08:00:02 JST 早い起動(JST 5:17の予定)\n", env=self.BACKUP)
        self.assertEqual((r["built"], r["published"], r["posted"], r["notified"]), ([], [], [], []))
        self.assertEqual(r["log"], ["GET"])

    def test_yesterday_record_posts(self):
        """記録が前の日の日付なら投稿する"""
        r = self._run_main(8, 5, record="2026-11-17 08:00:01 JST 早い起動(JST 5:17の予定)\n", env=self.CRON)
        self.assertEqual(len(r["posted"]), 1)
        self.assertTrue(r["record"].startswith("2026-11-18"))

    def test_force_ignores_record(self):
        """force:記録済みでも投稿し、記録を上書きする"""
        r = self._run_main(9, 15, record="2026-11-18 08:00:02 JST 早い起動(JST 5:17の予定)\n",
                           env={"EVENT_NAME": "workflow_dispatch", "FORCE": "true"})
        self.assertEqual(len(r["published"]), 1)
        self.assertEqual(len(r["posted"]), 1)
        self.assertEqual(r["record"], "2026-11-18 投稿 2026-11-18 09:15:00 JST 手動実行\n")

    def test_posted_by_other_run_during_wait(self):
        """8:00を待つ間に、ほかの起動が投稿して記録した → 公開も投稿もしない"""
        r = self._run_main(7, 40, env=self.CRON, appear_during_wait=True)
        self.assertEqual((r["published"], r["posted"]), ([], []))
        self.assertEqual(len(r["built"]), 1)

    def test_record_unreadable_posts_and_warns(self):
        """記録が読めない(GitHubが時間切れ)→ 投稿する側に倒し、二重の可能性を知らせる。記録も書けなければそれも知らせる"""
        r = self._run_main(8, 10, env=self.BACKUP, gh_fail="read")
        self.assertEqual(len(r["published"]), 1)
        self.assertEqual(len(r["posted"]), 1)
        msgs = " / ".join(e for _, e in r["notified"])
        self.assertIn("投稿済みの記録(state/last_posted.txt)を読めなかったため、確認せずに投稿しました", msgs)
        self.assertIn("投稿済みの記録を書けませんでした(TimeoutError)", msgs)

    def test_record_write_fails_after_post(self):
        """投稿のあと記録を書けない(GitHubがHTTP 500)→ 実行は失敗にせず、二重の可能性を知らせる"""
        r = self._run_main(8, 1, env=self.CRON, gh_fail="write")
        self.assertEqual(len(r["posted"]), 1)
        self.assertEqual(len(r["notified"]), 1)
        self.assertIn("投稿は済みましたが、投稿済みの記録を書けませんでした(HTTPError)", r["notified"][0][1])

    def test_trigger_label_in_failure_notice(self):
        """失敗の知らせに、何の起動かが入る"""
        bodies = []
        with mock.patch.dict(os.environ, {"EVENT_NAME": "schedule", "SCHEDULE_CRON": "10 8 * * *"}), \
             mock.patch.object(eb, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/x"), \
             mock.patch.object(eb.urllib.request, "urlopen",
                               side_effect=lambda req, timeout=None: bodies.append(json.loads(req.data.decode())["text"]) or self.Resp(b"ok")):
            eb.notify_failure("TimeoutError", "The read operation timed out")
        self.assertIn("起動: 予備の起動(JST 8:10の予定)", bodies[0])
        for ev, cron, want in (("schedule", "17 2 * * *", "早い起動(JST 2:17の予定)"), ("schedule", "47 3 * * *", "早い起動(JST 3:47の予定)"),
                               ("schedule", "17 5 * * *", "早い起動(JST 5:17の予定)"), ("schedule", "10 8 * * *", "予備の起動(JST 8:10の予定)"),
                               ("workflow_dispatch", "", "手動実行")):
            with mock.patch.dict(os.environ, {"EVENT_NAME": ev, "SCHEDULE_CRON": cron}):
                self.assertEqual(eb.trigger_label(), want)

    # ---- 2026-11-18 verifier指摘の試験 ----
    def test_slack_read_timeout_records_and_backup_skips(self):
        """7:30の起動でSlackの返事待ちが時間切れ → 「Slack不明」と記録し失敗として知らせる → 8:10の予備は何もしない"""
        r1 = self._run_main(7, 30, env=self.CRON, slack_exc=eb.SlackDeliveryUnknown(
            "Slackの返事を待つ間に失敗(TimeoutError)。届いたかは不明で、二重投稿を避けるため送り直していません"))
        self.assertIsInstance(r1["error"], eb.SlackDeliveryUnknown)
        self.assertEqual(len(r1["published"]), 1)
        self.assertEqual(r1["record"], "2026-11-18 投稿 2026-11-18 08:00:00 JST 早い起動(JST 5:17の予定) Slack不明(返事待ちの時間切れ)\n")
        self.assertIn("今日の分は投稿済み(Slack不明)として記録しました", r1["notified"][-1][1])
        r2 = self._run_main(8, 10, record=r1["record"], env=self.BACKUP)
        self.assertEqual((r2["built"], r2["published"], r2["posted"], r2["error"]), ([], [], [], None))

    def test_slack_connect_failure_backup_posts(self):
        """Slackの接続の段階の失敗(URLError=届いていない)→ 記録しない → 8:10の予備が投稿する"""
        r1 = self._run_main(7, 30, env=self.CRON, slack_exc=urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")))
        self.assertIsInstance(r1["error"], urllib.error.URLError)
        self.assertEqual(r1["record"], "")
        self.assertEqual(len(r1["notified"]), 1)
        r2 = self._run_main(8, 10, record=None, env=self.BACKUP)
        self.assertEqual(len(r2["published"]), 1)
        self.assertEqual(len(r2["posted"]), 1)
        self.assertTrue(r2["record"].startswith("2026-11-18 投稿 2026-11-18 08:10:00 JST 予備の起動"))

    def test_slack_retry_then_read_timeout_is_unknown(self):
        """Slackの1回目が接続の失敗、取り直しが返事待ちの時間切れ → 届いたか不明として扱う(生のTimeoutErrorで抜けない)"""
        calls = []

        def fake(url, payload):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.URLError(TimeoutError("timed out"))
            raise TimeoutError("The read operation timed out")
        with mock.patch.object(eb, "_post_json", fake):
            with self.assertRaises(eb.SlackDeliveryUnknown):
                eb._post_slack_once("https://hooks.slack.com/services/x", {"text": "t"})
        self.assertEqual(len(calls), 2)

    def test_cross_midnight_manual_then_morning(self):
        """23:50の手動実行が取得に15分かかり、投稿が翌0:05になっても、記録は起動した日 → 翌朝7:30の起動は投稿する"""
        r1 = self._run_main(23, 50, env={"EVENT_NAME": "workflow_dispatch"}, build_minutes=15)
        self.assertEqual(r1["posted"], [datetime(2026, 11, 19, 0, 5, tzinfo=eb.JST)])
        self.assertEqual(r1["record"], "2026-11-18 投稿 2026-11-19 00:05:00 JST 手動実行\n")
        r2 = self._run_main(7, 30, day=19, record=r1["record"], env=self.CRON)
        self.assertEqual(len(r2["published"]), 1)
        self.assertEqual(len(r2["posted"]), 1)
        self.assertTrue(r2["record"].startswith("2026-11-19 投稿 2026-11-19 08:00:00 JST 早い起動"))

    def _assert_read_failure_flow(self, mode):
        r = self._run_main(8, 10, env=self.BACKUP, gh_fail=mode)
        self.assertIsNone(r["error"], mode)
        self.assertEqual((len(r["published"]), len(r["posted"]), len(r["notified"])), (1, 1, 2), mode)
        msgs = [e for _, e in r["notified"]]
        self.assertIn("投稿済みの記録(state/last_posted.txt)を読めなかったため、確認せずに投稿しました", msgs[0])
        self.assertIn("投稿は済みましたが、投稿済みの記録を書けませんでした", msgs[1])
        return msgs

    def test_record_read_urlerror(self):
        """記録の読み取りがつながらない(URLError)→ 最後まで進み、公開1回・投稿1回・知らせ2通"""
        msgs = self._assert_read_failure_flow("read_urlerror")
        self.assertIn("(URLError)", msgs[1])

    def test_record_read_502_html(self):
        """記録の読み取りが壊れた返事(502でHTML)→ 最後まで進み、公開1回・投稿1回・知らせ2通"""
        msgs = self._assert_read_failure_flow("read_502")
        self.assertIn("(HTTPError)", msgs[1])

    def test_record_read_bad_base64(self):
        """記録の中身がbase64として読めない → 最後まで進み、公開1回・投稿1回・知らせ2通"""
        msgs = self._assert_read_failure_flow("read_badb64")
        self.assertIn("(Error)", msgs[1])   # binascii.Error

    # ---- 2026-11-18(2回目):scheduleを2:17・3:47・5:17・予備8:10にした方式の試験 ----
    def _seq(self, runs):
        """runs:[(時, 分, env, その他の引数)]。前の実行の記録を引き継ぎながら順に動かす(concurrencyで同時には動かない)"""
        rec, out = None, []
        for h, m, env, kw in runs:
            r = self._run_main(h, m, record=rec, env=env, **kw)
            rec = r["record"] or rec
            out.append(r)
        return out

    def test_0230_waits_fetch_at_0605_posts_at_8(self):
        """2:30の起動 → 7:25まで待って取得(取得は1回)→ 8:00:00に公開・投稿"""
        r = self._run_main(2, 30, env=self.EARLY1)
        self.assertEqual(r["built"], [datetime(2026, 11, 18, 7, 25, tzinfo=eb.JST)])
        self.assertEqual([t for t, _ in r["published"]], [datetime(2026, 11, 18, 8, 0, tzinfo=eb.JST)])
        self.assertEqual(r["posted"], [datetime(2026, 11, 18, 8, 0, tzinfo=eb.JST)])
        self.assertEqual(r["record"], "2026-11-18 投稿 2026-11-18 08:00:00 JST 早い起動(JST 2:17の予定)\n")
        self.assertEqual(sum(r["sleeps"]), (8 * 60 - (2 * 60 + 30)) * 60)   # 5時間30分(7:25まで+8:00まで)
        self.assertEqual(r["log"], ["GET", "GET", "GET", "GET", "PUT"])    # 起動時・取得前・公開前の確認、記録の書き込み

    def test_first_posts_others_do_nothing(self):
        """1回目が投稿 → 3:47・5:17・8:10の起動(1回目が終わってから順に動く)は何もしない"""
        rs = self._seq([(2, 17, self.EARLY1, {}), (8, 1, self.EARLY2, {}), (8, 1, self.CRON, {}), (8, 10, self.BACKUP, {})])
        self.assertEqual([len(r["posted"]) for r in rs], [1, 0, 0, 0])
        self.assertEqual([len(r["built"]) for r in rs], [1, 0, 0, 0])
        self.assertTrue(all(r["error"] is None and not r["notified"] for r in rs))

    def test_first_fails_mid_fetch_next_posts(self):
        """1回目が7:25の取得の途中で失敗 → 順番待ちの次の起動(7:30に始まる)が取得し、8:00に投稿する"""
        rs = self._seq([(2, 17, self.EARLY1, {"build_exc": urllib.error.URLError("network down")}),
                        (7, 30, self.CRON, {}), (8, 10, self.BACKUP, {})])
        self.assertIsInstance(rs[0]["error"], urllib.error.URLError)
        self.assertEqual((rs[0]["posted"], rs[0]["record"], len(rs[0]["notified"])), ([], "", 1))
        self.assertEqual(rs[1]["built"], [datetime(2026, 11, 18, 7, 30, tzinfo=eb.JST)])
        self.assertEqual(rs[1]["posted"], [datetime(2026, 11, 18, 8, 0, tzinfo=eb.JST)])
        self.assertEqual(rs[2]["posted"], [])

    def test_all_three_late_at_0820(self):
        """3回とも遅れて8:20以降に起動 → 最初の1回がすぐ投稿し、残りは何もしない"""
        rs = self._seq([(8, 20, self.EARLY1, {}), (8, 21, self.EARLY2, {}), (8, 22, self.CRON, {})])
        self.assertEqual(rs[0]["posted"], [datetime(2026, 11, 18, 8, 20, tzinfo=eb.JST)])
        self.assertEqual(rs[0]["sleeps"], [])
        self.assertEqual([len(r["posted"]) for r in rs[1:]], [0, 0])

    def test_manual_0630_posts_without_waiting(self):
        """手動の6:30起動 → 今まで通り、取得も投稿も待たない"""
        r = self._run_main(6, 30, env=self.MANUAL)
        self.assertEqual((r["sleeps"], r["built"], r["posted"]),
                         ([], [datetime(2026, 11, 18, 6, 30, tzinfo=eb.JST)], [datetime(2026, 11, 18, 6, 30, tzinfo=eb.JST)]))
        self.assertTrue(r["record"].endswith("JST 手動実行\n"))

    def test_schedule_0630_waits_for_8(self):
        """scheduleの6:30起動は、手動と違い7:25まで待って取得し、8:00まで待って投稿する"""
        r = self._run_main(6, 30, env=self.CRON)
        self.assertEqual(r["built"], [datetime(2026, 11, 18, 7, 25, tzinfo=eb.JST)])
        self.assertEqual(r["posted"], [datetime(2026, 11, 18, 8, 0, tzinfo=eb.JST)])

    def test_schedule_before_0215_does_nothing(self):
        """2:15より前に始まったscheduleの起動は、6時間の上限を超えないよう何もせず終わる(記録も読まない)"""
        r = self._run_main(1, 50, env=self.EARLY1)
        self.assertEqual((r["log"], r["built"], r["posted"], r["error"], r["notified"]), ([], [], [], None, []))

    def test_force_in_schedule_window(self):
        """force(手動)は記録済みでも、待たずに取得・投稿する"""
        r = self._run_main(6, 40, record="2026-11-18 投稿 2026-11-18 08:00:00 JST 早い起動(JST 2:17の予定)\n",
                           env={"EVENT_NAME": "workflow_dispatch", "FORCE": "true"})
        self.assertEqual((len(r["posted"]), r["sleeps"]), (1, []))

    def test_slack_unknown_on_early_run_blocks_later_runs(self):
        """早い起動でSlackの返事待ちが時間切れ → 「Slack不明」と記録 → 後の起動(5:17・8:10)は送り直さない"""
        rs = self._seq([(2, 17, self.EARLY1, {"slack_exc": eb.SlackDeliveryUnknown("返事待ちの時間切れ")}),
                        (8, 1, self.CRON, {}), (8, 10, self.BACKUP, {})])
        self.assertIn("Slack不明", rs[0]["record"])
        self.assertEqual([len(r["posted"]) for r in rs], [1, 0, 0])

    def test_timeout_budget_matches_workflow(self):
        """workflowのtimeout-minutesは360(上限)。最も早い2:15の起動から8:00までの待ち+公開・投稿の最悪(約3分)+準備(約2分)が収まる"""
        wf = open(os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "econobot.yml"), encoding="utf-8").read()
        self.assertIn("timeout-minutes: 360", wf)
        for cron in ("17 2 * * *", "47 3 * * *", "17 5 * * *"):
            self.assertIn(f"- cron: '{cron}'", wf)
        wait_min = (eb.POST_HOUR * 60) - (eb.SCHEDULE_EARLIEST[0] * 60 + eb.SCHEDULE_EARLIEST[1])
        self.assertLessEqual(wait_min + 3 + 2, 360)
        self.assertEqual(eb.FETCH_AFTER, (7, 25))
        # 取得の時刻+取得・要約の最悪(約21分)が8:00に間に合う。打ち切りの線(2:15)からの実行時間は、8:00までの待ち
        # (取得はその途中)+公開・投稿の最悪(約3分)+準備(約2分)で、取得の時刻を動かしても変わらない
        fetch_end = eb.FETCH_AFTER[0] * 60 + eb.FETCH_AFTER[1] + 21
        self.assertLessEqual(fetch_end, eb.POST_HOUR * 60)
        total = max(fetch_end, eb.POST_HOUR * 60) + 3 + 2 - (eb.SCHEDULE_EARLIEST[0] * 60 + eb.SCHEDULE_EARLIEST[1])
        self.assertLessEqual(total, 360)

    def test_fetch_after_close_confirmation(self):
        """取得の時刻は、冬の引け(JST 6:00)+_parse_yahooが終値の確定を待つ15分より後(6:05だと前の日の終値になっていた)。
        保存した本物の^GSPCの応答で、引け後15分以内は最後の足を捨て、それより後は使うことを確かめる"""
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "yahoo_GSPC_1d_2y_2026-11-14.json"), encoding="utf-8") as f:
            res = json.load(f)["chart"]["result"][0]
        end = res["meta"]["currentTradingPeriod"]["regular"]["end"]          # 11/13 16:00 ET = 11/14 6:00 JST
        at = lambda h, m: datetime(2026, 11, 14, h, m, tzinfo=eb.JST)
        self.assertEqual(datetime.fromtimestamp(end, eb.JST), at(6, 0))
        self.assertEqual(eb._parse_yahoo(res, at(6, 5))[-1][0], "2026-11-12")    # 6:05:まだ確定しない扱い
        self.assertEqual(eb._parse_yahoo(res, at(*eb.FETCH_AFTER))[-1][0], "2026-11-13")
        self.assertGreaterEqual(eb.FETCH_AFTER, (6, 16))

    def test_fetch_at_0725_treasury_row_used(self):
        """7:25の取得で財務省に対象日の行がある場合は、2年債は財務省の当日の値になる(保存した本物の応答=11-14取得、11/13の行あり)。
        7:25の時点で行が公表済みかどうか(公表時刻そのもの)は、保存した応答からは分からない(未確認)。無い日はFREDに日付つき(TreasuryTest)"""
        st, ps = self._clock(*eb.FETCH_AFTER, day=14)
        for p in ps:
            p.start()
        try:
            m, c = TreasuryTest()._market("full")
        finally:
            for p in ps:
                p.stop()
        self.assertEqual((m["series"]["米2年債利回り"]["src"], c["value_text"], c["stale"]), ("米国財務省", "4.88%", False))


class NewScheduleTest(unittest.TestCase):
    """2026-11-27 Shio「時間のズレを考慮して朝は7時、夕方は16時」: 6:25に取得、7:00に公開・投稿、予備7:10、夕方16:04は学習アプリのデータだけ"""

    def test_constants_and_workflow(self):
        self.assertEqual((eb.POST_HOUR, eb.FETCH_AFTER, eb.EARLY_LIMIT_HOUR), (7, (6, 25), 6))
        wf = open(os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "econobot.yml"), encoding="utf-8").read()
        for cron in ("17 2 * * *", "47 3 * * *", "17 5 * * *", "10 7 * * *", "4 16 * * *"):
            self.assertIn(f"- cron: '{cron}'", wf)
        self.assertNotIn("'10 8 * * *'", wf)
        self.assertIn("LEARN_ONLY: ${{ inputs.learn_only || github.event.schedule == '4 16 * * *' }}", wf)
        # 冬の引け(6:00)+終値の確定を待つ15分より後に取得し、取得・要約の最悪(約21分)でも7:00に間に合う
        self.assertGreaterEqual(eb.FETCH_AFTER[0] * 60 + eb.FETCH_AFTER[1], 6 * 60 + 15)
        self.assertLessEqual(eb.FETCH_AFTER[0] * 60 + eb.FETCH_AFTER[1] + 21, eb.POST_HOUR * 60)

    def test_labels(self):
        for cron, want in (("10 7 * * *", "予備の起動(JST 7:10の予定)"), ("4 16 * * *", "夕方の更新(JST 16:04の予定。学習アプリのデータだけ)")):
            with mock.patch.dict(os.environ, {"EVENT_NAME": "schedule", "SCHEDULE_CRON": cron}):
                self.assertEqual(eb.trigger_label(), want)

    def test_wait_until_7(self):
        state = {"now": datetime(2026, 11, 28, 6, 50, tzinfo=eb.JST)}

        def sleep(sec):
            state["now"] = state["now"] + eb.timedelta(seconds=sec)
        with mock.patch.object(eb, "_now_jst", lambda: state["now"]), mock.patch.object(eb, "_sleep", sleep), \
             mock.patch.dict(os.environ, {"EVENT_NAME": "schedule"}):
            self.assertEqual(eb.wait_for_post_time(), 600)
            self.assertEqual(state["now"], datetime(2026, 11, 28, 7, 0, tzinfo=eb.JST))
            state["now"] = datetime(2026, 11, 28, 3, 0, tzinfo=eb.JST)
            self.assertEqual(eb.wait_before_fetch(), (3 * 60 + 25) * 60)   # 6:25まで


class LearnMarketJsonTest(unittest.TestCase):
    def test_build_keeps_fetched_series_and_points(self):
        def fake(sid, days):
            if sid == "DGS2":
                raise OSError("timeout")
            if sid == "T10Y2Y":
                return [("2026-11-01", 0.5)] * 5  # 少なすぎる系列は入れない
            return [(f"2026-01-{i % 28 + 1:02d}", 100.0 + i) for i in range(60)]
        econ = {"ok": True, "headline": "見出し", "key_points": [{"text": "要点A", "category": "金利"}, {"text": ""}]}
        d = eb.build_market_json(econ, fetch=fake, now=NOW)
        self.assertIn("SP500", d["series"])
        self.assertNotIn("DGS2", d["series"])
        self.assertNotIn("T10Y2Y", d["series"])
        self.assertEqual(d["series"]["SP500"]["kind"], "index")
        self.assertEqual(len(d["series"]["SP500"]["rows"]), 60)
        self.assertEqual(d["points"], [{"text": "要点A", "category": "金利"}])
        self.assertEqual(d["headline"], "見出し")

    def test_build_without_summary(self):
        d = eb.build_market_json({"ok": False, "headline": "準備中"}, fetch=lambda s, n: [], now=NOW)
        self.assertEqual((d["series"], d["points"], d["headline"]), ({}, [], ""))

    def test_publish_skips_when_empty(self):
        with mock.patch.object(eb, "build_market_json", return_value={"series": {}}), \
             mock.patch.object(eb, "_gh_put_file") as put:
            self.assertFalse(eb.publish_market_json({"ok": True}))
            put.assert_not_called()

    def test_publish_writes_compact_json(self):
        data = {"updated": "x", "series": {"SP500": {"name": "S&P 500", "kind": "index", "rows": [["2026-11-01", 1.0]]}}}
        with mock.patch.object(eb, "build_market_json", return_value=data), \
             mock.patch.object(eb, "_gh_put_file") as put:
            self.assertTrue(eb.publish_market_json({"ok": True}))
            path, body, _msg = put.call_args[0]
            self.assertEqual(path, "learn/data/market.json")
            self.assertEqual(json.loads(body.decode("utf-8")), data)
            self.assertNotIn(b" ", body.replace(b"S&P 500", b""))
