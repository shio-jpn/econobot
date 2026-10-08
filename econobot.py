"""
EconoBot - 米国経済ニュース自動要約
BBCスタイルHTMLページを生成 → GitHub Pages公開 → SlackにURLを投稿
"""

import os
import json
import re
import time
import base64
import html
import unicodedata
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta

# ========================================
# 設定
# ========================================
# APIキー無しでもHTML生成部分を試験できるよう、ここでは.get()で読み、必須チェックはmain()で行う
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
NEWS_API_KEY      = os.environ.get("NEWS_API_KEY", "")
GITHUB_REPO       = os.environ.get("GITHUB_REPOSITORY", "")   # 例: username/econobot
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "")         # Actions自動提供
_REQUIRED_ENV = ["GEMINI_API_KEY", "SLACK_WEBHOOK_URL", "NEWS_API_KEY", "GITHUB_REPOSITORY", "GITHUB_TOKEN"]

JST = timezone(timedelta(hours=9))
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def _jp_date(now):
    """「10月8日(木)」。strftimeの%-mはWindowsで動かないため、数値から組み立てる"""
    return f"{now.month}月{now.day}日({WEEKDAYS[now.weekday()]})"


_TRUNC_RE = re.compile(r"\s*\[\+\d+ chars\]\s*$")


def _clean_desc(text):
    """NewsAPIの説明文は途中で切れていることがある。切れた末尾の数値をAIが拾わないよう、
    「[+123 chars]」と、末尾の「…」「...」で終わる途中の文を取り除く"""
    t = _TRUNC_RE.sub("", text or "").strip()
    if t.endswith(("…", "...")):
        cut = max(t.rfind(". "), t.rfind("。"))
        t = t[:cut + 1] if cut > 0 else ""
    return t


# 参照ソース欄に出す記事の判定用(セール情報・事故など経済と無関係な見出しを外す)
_ECON_RE = re.compile(
    r"stock|market|price|wage|s&p|nasdaq|dow|fed|rate|inflation|cpi|job|payroll|unemploy|earning|revenue|"
    r"profit|economy|economic|gdp|treasury|yield|bond|dollar|tariff|trade|bank|oil|bitcoin|crypto|"
    r"shares|investor|wall street|recession|deficit|debt|ipo|merger|acquisition",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(r"\bdeals?\b|prime day|discount|coupon|\bsales? event\b|\bon sale\b|gift guide", re.IGNORECASE)


def _is_econ(a):
    text = f"{a.get('title', '')} {a.get('description', '')}"
    return bool(_ECON_RE.search(text)) and not _NOISE_RE.search(a.get("title", ""))

# ========================================
# 1. NewsAPIでニュースを取得
# ========================================
# 信頼できる報道機関・公的機関だけを使う(2026-10-08 Shio指示「BBCなど公式の信憑性の高い情報のみ」)。
# NewsAPIのeverything検索はこのドメインに限定し、top-headlinesは取得後にURLで絞り込む。
TRUSTED_DOMAINS = [
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "wsj.com", "bloomberg.com",
    "ft.com", "cnbc.com", "nytimes.com", "washingtonpost.com", "npr.org",
    "marketwatch.com", "barrons.com", "economist.com",
    "federalreserve.gov", "bls.gov", "bea.gov", "treasury.gov", "whitehouse.gov",
]


def _is_trusted(a):
    host = urllib.parse.urlparse(a.get("url", "")).hostname or ""
    return any(host == d or host.endswith("." + d) for d in TRUSTED_DOMAINS)


def _only_trusted(articles, label):
    kept = [a for a in articles if _is_trusted(a)]
    print(f"    [信頼できる媒体のみ:{label}] {len(articles)}件 → {len(kept)}件")
    return kept


def fetch_news():
    """経済ニュースを取得：top-headlines（常に最新）+ everything（キーワード検索）を併用"""
    articles = []

    # ① top-headlines: 米国ビジネスの最新トップニュース（常に当日更新）
    for category, q in [("business", ""), ("general", "economy OR stock OR Fed")]:
        params = {
            "country": "us",
            "category": category,
            "pageSize": 10,
            "apiKey": NEWS_API_KEY,
        }
        if q:
            params["q"] = q
        url = f"https://newsapi.org/v2/top-headlines?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "EconoBot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode())
        fetched = data.get("articles", [])
        print(f"    [top-headlines/{category}] {len(fetched)}件")
        for a in fetched:
            articles.append({
                "title": a.get("title", ""),
                "description": _clean_desc(a.get("description", "")),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", ""),
                "publishedAt": a.get("publishedAt", ""),
            })

    # ② everything: キーワード検索で補完（直近48時間）
    from_date = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    queries = [
        "S&P 500 Nasdaq stock market",
        "Federal Reserve interest rate",
        "inflation CPI jobs unemployment",
        "earnings revenue quarterly results",
    ]
    for query in queries:
        params = urllib.parse.urlencode({
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "domains": ",".join(TRUSTED_DOMAINS),
            "from": from_date,
            "pageSize": 8,
            "apiKey": NEWS_API_KEY,
        })
        url = f"https://newsapi.org/v2/everything?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "EconoBot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode())
        fetched = data.get("articles", [])
        print(f"    [{query[:25]}...] {len(fetched)}件")
        for a in fetched:
            articles.append({
                "title": a.get("title", ""),
                "description": _clean_desc(a.get("description", "")),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", ""),
                "publishedAt": a.get("publishedAt", ""),
            })

    articles = _only_trusted(articles, "経済")

    # 重複除去・最新順ソート
    seen = set()
    unique = []
    for a in sorted(articles, key=lambda x: x.get("publishedAt", ""), reverse=True):
        if a["title"] not in seen and a["title"]:
            seen.add(a["title"])
            unique.append(a)
    print(f"  合計 {len(unique)}件取得")
    return unique


# ========================================
# 1b. 主要ニュース（トランプ・米国内政）を取得
# ========================================
def fetch_major_news():
    """主要ニュース取得：top-headlines + キーワード検索（48時間）"""
    articles = []

    # ① top-headlines: 米国の最新トップニュース
    params = urllib.parse.urlencode({
        "country": "us",
        "pageSize": 10,
        "apiKey": NEWS_API_KEY,
    })
    url = f"https://newsapi.org/v2/top-headlines?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "EconoBot/1.0"})
    with urllib.request.urlopen(req, timeout=10) as res:
        data = json.loads(res.read().decode())
    fetched = data.get("articles", [])
    print(f"    [top-headlines/us] {len(fetched)}件")
    for a in fetched:
        articles.append({
            "title": a.get("title", ""),
            "description": _clean_desc(a.get("description", "")),
            "source": a.get("source", {}).get("name", ""),
            "url": a.get("url", ""),
            "publishedAt": a.get("publishedAt", ""),
        })

    # ② キーワード検索で補完（48時間）
    from_date = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    queries = [
        "Trump White House policy executive order",
        "artificial intelligence AI technology OpenAI Google",
        "semiconductor chip NVIDIA TSMC export",
    ]
    for query in queries:
        params = urllib.parse.urlencode({
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "domains": ",".join(TRUSTED_DOMAINS),
            "from": from_date,
            "pageSize": 8,
            "apiKey": NEWS_API_KEY,
        })
        url = f"https://newsapi.org/v2/everything?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "EconoBot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode())
        for a in data.get("articles", []):
            articles.append({
                "title": a.get("title", ""),
                "description": _clean_desc(a.get("description", "")),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", ""),
                "publishedAt": a.get("publishedAt", ""),
            })

    articles = _only_trusted(articles, "主要")

    # 重複除去・最新順ソート
    seen = set()
    unique = []
    for a in sorted(articles, key=lambda x: x.get("publishedAt", ""), reverse=True):
        if a["title"] not in seen and a["title"]:
            seen.add(a["title"])
            unique.append(a)
    print(f"  合計 {len(unique)}件取得")
    return unique


# ========================================
# 2. Gemini APIで要約(JSON形式・リトライあり)
# ========================================
# 試すモデルの優先順位(上から順に試す)。
# 以前先頭にあった gemini-2.5-flash-lite-preview-06-17 はプレビュー版で提供終了済みのため外した
# (残すと毎回404→次のモデル、と無駄な試行が1回増えるため)
GEMINI_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]

# responseSchemaをモデルに拒否された(HTTP 400)ことがある実行中は、2回目以降の呼び出しで
# 最初からスキーマ無しにする(同じ400を毎回踏んで呼び出し回数を増やさないため)
_SCHEMA_REJECTED = {"value": False}


def _call_gemini(prompt, schema, label):
    """Geminiを呼んで本文テキストを返す。JSONで返すよう指定し、スキーマも付ける。
    - 429/503 は待って同じモデルで最大3回(従来どおり)
    - スキーマ付きで400が返ったら、同じモデルでスキーマ無し(JSON指定のみ)で1回だけ送り直す
    - 404やその他の失敗は次のモデルへ
    全モデルで失敗したら RuntimeError"""
    for model in GEMINI_MODELS:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models"
            f"/{model}:generateContent?key={GEMINI_API_KEY}"
        )
        use_schema = schema is not None and not _SCHEMA_REJECTED["value"]
        attempt = 0
        while attempt < 3:
            gen_cfg = {"temperature": 0.2, "responseMimeType": "application/json"}
            if use_schema:
                gen_cfg["responseSchema"] = schema
            body = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": gen_cfg,
            }).encode("utf-8")
            print(f"  モデル試行: {model} [{label}] schema={'on' if use_schema else 'off'}")
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as res:
                    data = json.loads(res.read().decode())
                print(f"  成功: {model}")
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError, TypeError):
                    # 安全フィルタ等で本文が空のとき。呼び直さず「JSONが読めない」扱いにする
                    print("  [WARN] Geminiの応答に本文がありません")
                    return ""
            except urllib.error.HTTPError as e:
                if e.code == 400 and use_schema:
                    print(f"  HTTP 400(スキーマ指定を拒否された可能性)→ スキーマ無しで再送")
                    _SCHEMA_REJECTED["value"] = True
                    use_schema = False
                    continue  # attemptは増やさない(400の送り直しは1回だけ)
                if e.code in (503, 429) and attempt < 2:
                    wait = 15 * (attempt + 1)
                    print(f"  HTTP {e.code} → {wait}秒後にリトライ ({attempt+1}/3)...")
                    time.sleep(wait)
                    attempt += 1
                    continue
                print(f"  {model} 失敗(HTTP {e.code})、次のモデルへ...")
                break
    raise RuntimeError("全モデルで失敗しました")


def _numbered(articles):
    """記事を「[1] [WSJ] タイトル: 説明文」の形に並べる(AIに出典を番号で答えさせるため)"""
    return "\n".join(
        f"[{i}] [{a['source']}] {a['title']}: {a['description']}"
        for i, a in enumerate(articles, 1)
    )


def usable_econ_articles(articles):
    """経済用にAIへ渡す記事(セール情報等を除いたもの)。番号はこの並びの1始まり"""
    return [a for a in articles if a.get("title") and not _NOISE_RE.search(a["title"])]


def usable_major_articles(articles):
    return [a for a in articles if a.get("title")]


_SRC_ARRAY = {"type": "ARRAY", "items": {"type": "INTEGER"}}
_LINE = {
    "type": "OBJECT",
    "properties": {"text": {"type": "STRING"}, "sources": _SRC_ARRAY},
    "required": ["text", "sources"],
}

MARKET_NAMES = ["S&P 500", "ナスダック総合", "ダウ平均", "米10年債利回り", "ドル円", "WTI原油", "ビットコイン"]
KEY_CATEGORIES = ["株式", "金融政策", "雇用・物価", "決算", "企業", "その他"]
MAJOR_CATEGORIES = ["政治・政策", "国際", "AI・テック", "半導体", "経済"]

ECON_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "key_points": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "category": {"type": "STRING", "enum": KEY_CATEGORIES},
                    "text": {"type": "STRING"},
                    "sources": _SRC_ARRAY,
                },
                "required": ["category", "text", "sources"],
            },
        },
        "markets": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING", "enum": MARKET_NAMES},
                    "value_text": {"type": "STRING", "nullable": True},
                    "change_value": {"type": "NUMBER", "nullable": True},
                    "change_unit": {"type": "STRING", "enum": ["%", "bp"]},
                    "quote": {"type": "STRING"},
                    "source": {"type": "INTEGER"},
                },
                "required": ["name", "quote", "source"],
            },
        },
        "sections": {
            "type": "OBJECT",
            "properties": {
                "stock": {"type": "ARRAY", "items": _LINE},
                "fed": {"type": "ARRAY", "items": _LINE},
                "jobs": {"type": "ARRAY", "items": _LINE},
                "earnings": {"type": "ARRAY", "items": _LINE},
            },
            "required": ["stock", "fed", "jobs", "earnings"],
        },
    },
    "required": ["headline", "key_points", "markets", "sections"],
}

MAJOR_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "category": {"type": "STRING", "enum": MAJOR_CATEGORIES},
                    "title": {"type": "STRING"},
                    "lead": {"type": "STRING"},
                    "bullets": {"type": "ARRAY", "items": _LINE},
                    "sources": _SRC_ARRAY,
                },
                "required": ["category", "title", "lead", "bullets", "sources"],
            },
        },
    },
    "required": ["items"],
}

ECON_PROMPT = """あなたは米国経済ニュースの編集者です。忙しい日本の読者が、朝スマホで30秒だけ見て
「今日の米国経済で何が起きたか」「主な指数は上がったか下がったか」をつかめる要約を作ります。

下の【記事】は直近24〜48時間に配信された英語ニュースで、先頭に[番号]が付いています。
指定したJSONの形だけを返してください。

■ JSONの形
{{"headline": "20字以内の見出し",
  "key_points": [{{"category": "株式|金融政策|雇用・物価|決算|企業|その他", "text": "45字以内", "sources": [記事番号]}}],
  "markets": [{{"name": "S&P 500|ナスダック総合|ダウ平均|米10年債利回り|ドル円|WTI原油|ビットコイン",
               "value_text": "記事にある値 または null", "change_value": 変動の数値 または null,
               "change_unit": "%|bp", "quote": "その数値が書かれた英語の文をそのまま", "source": 記事番号}}],
  "sections": {{"stock": [{{"text": "60字以内", "sources": [記事番号]}}], "fed": [], "jobs": [], "earnings": []}}}}
件数:key_points 1〜3、markets 0〜7、stock 最大5、fed・jobs・earnings 各最大3。

■ 数値のルール(最重要。読者はこの数値をそのまま信じるため)
1. 数値は記事の文中に書かれているものだけを使う。計算・換算・四捨五入・推測はしない。
2. markets の各項目では、その数値が書かれている英語の文を quote に一字一句そのまま写し、
   その記事の番号を source に入れる。quote に無い数値を value_text や change_value に入れない。
3. 指数の値や変動率が記事に無ければ、その欄は null にする。無理に埋めない。
4. 途中で切れている数値(「51...」「7,8…」など)は使わない。その項目ごと出さない。
5. 下落は change_value を負の数にする(例:-0.69)。上昇は正の数。

■ 文章のルール
- key_points は今日いちばん重要な出来事を最大3つ。1つの要点に1つの事実だけ。
  「誰が/何が + どうなった」を先に書き、45字以内。数字が記事にあれば1つだけ入れる。
- sections の各項目は1行60字以内の箇条書き。主語から書き始め、1行に1つの事実だけ。
- 「注目が集まる」「動向が注視される」のような中身のない締めの言葉は書かない。
- 記事に書かれていない見通し・理由づけは書かない。記事に書かれている場合だけ「〜と報じられた」と書く。
- 「本日」は使わない。日付は記事にある場合だけ書く。
- 企業名・指数名は日本で通じる表記にする(例:Nvidia→エヌビディア、Fed→FRB)。
- headline は全体を一言で表す20字以内。
- fed(FRBの金利決定・FOMC・FRB高官の発言)、jobs(雇用統計・失業率・CPI・PCE・賃金)、
  earnings(大手企業の決算発表)は、該当する記事が無ければ空の配列 [] にする。
  関係の薄い記事で無理に埋めない。
- セール情報・事故・芸能など、経済と関係のない記事は使わない。

【記事】
{numbered_news_text}
"""

MAJOR_PROMPT = """あなたは米国・国際情勢・テクノロジーニュースの編集者です。忙しい日本の読者が、朝スマホで
見出しだけ見て「経済以外で今日知っておくべきこと」をつかめる要約を作ります。

下の【記事】は直近24〜48時間に配信された英語ニュースで、先頭に[番号]が付いています。
最も重要なニュースを最大3件選び、指定したJSONの形だけを返してください。

■ JSONの形
{{"items": [{{"category": "政治・政策|国際|AI・テック|半導体|経済",
             "title": "25字以内", "lead": "1文45字以内",
             "bullets": [{{"text": "60字以内", "sources": [記事番号]}}],
             "sources": [記事番号]}}]}}
件数:items 1〜3、bullets は各2〜3個。

■ 選ぶもの(重要度が高い順に優先)
- トランプ大統領の政策・発言・行政
- 米国内政・外交・国際情勢(米中関係など)
- AI・人工知能の最新動向(新モデル・規制・企業動向)
- 半導体・チップ産業(エヌビディア・TSMC・輸出規制など)
- 経済の要約で扱わない重要な米国経済ニュース

■ 文章のルール
- 数値は記事の文中に書かれているものだけを使う。計算・換算・推測はしない。途中で切れた数値は使わない。
- title は「誰が/何が + どうした」を先に書く。lead は何が起きたかを1文で。
- bullets は1行に1つの事実だけ。記事に書かれていない見通し・理由づけは書かない。
- 「注目が集まる」のような中身のない締めの言葉、「本日」は使わない。
- 人名・企業名は日本で通じる表記にする。

【記事】
{numbered_news_text}
"""


def summarize_with_gemini(econ_articles):
    """経済ニュースの要約(Gemini 1回)。返り値はGeminiの生テキスト(JSONのはず)"""
    prompt = ECON_PROMPT.format(numbered_news_text=_numbered(econ_articles))
    return _call_gemini(prompt, ECON_SCHEMA, "経済")


def summarize_major_news(major_articles):
    """主要ニュースの要約(Gemini 1回)。失敗しても例外にせず空文字を返し、見出しのみ表示に切り替える"""
    prompt = MAJOR_PROMPT.format(numbered_news_text=_numbered(major_articles))
    try:
        return _call_gemini(prompt, MAJOR_SCHEMA, "主要ニュース")
    except Exception as e:
        print(f"  [WARN] 主要ニュースの要約に失敗: {e}")
        return ""


# ========================================
# 3. JSONの読み取りと検証(AIを信用せず、毎回プログラムで確かめる)
# ========================================
_NONE_WORDS = {"none", "null", "n/a", "na", "なし", "該当なし", "該当ニュースなし", "undefined", "-", "ー"}


def _is_empty(v):
    """null・空文字・空配列・「NONE」等の文字列を「無い」とみなす"""
    if v is None:
        return True
    if isinstance(v, (list, dict)):
        return len(v) == 0
    if isinstance(v, str):
        s = v.strip().rstrip("。.").strip().lower()
        return s == "" or s in _NONE_WORDS
    return False


def _loads_loose(text):
    """json.loads → 失敗したら ```json の囲みを外し、最初の{から最後の}までで再挑戦。
    それでも読めなければ None(Geminiは呼び直さない)"""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    t = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except (ValueError, TypeError):
        return None


def _norm(s):
    """照合用:全角半角をそろえ、引用符をそろえ、空白をまとめ、小文字にする"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def _article_text(a):
    return _norm(f"{a.get('title', '')} {a.get('description', '')}")


def _valid_sources(srcs, articles):
    """番号のリストのうち、実在する記事番号だけを返す(重複は除く)"""
    if isinstance(srcs, int) and not isinstance(srcs, bool):
        srcs = [srcs]
    if not isinstance(srcs, list):
        return []
    out = []
    for n in srcs:
        if isinstance(n, bool) or not isinstance(n, int):
            continue
        if 1 <= n <= len(articles) and n not in out:
            out.append(n)
    return out


def _num_pos(num, text):
    """数字numがtextの中に「1つの数字として」現れる位置を返す(無ければ-1)。
    前後に別の数字や小数点が続く場合は一致としない(0.5 と 0.55、784 と 7840 を区別するため)。
    カンマ入りの数字(7,840)は、呼び出し側で num・text の両方からカンマを除いてから渡す"""
    m = re.search(r"(?<![\d.])" + re.escape(num) + r"(?!\.?\d)", text)
    return m.start() if m else -1


_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_CUT_NUM_RE = re.compile(r"\d\s*(?:\.\.\.|…)")


def _check_line(item, articles, max_len=None):
    """箇条書き1行を検証する。ダメなら None(その1行だけ捨てる)"""
    if not isinstance(item, dict):
        return None
    text = item.get("text")
    if not isinstance(text, str) or _is_empty(text):
        return None
    text = text.replace("**", "").strip()
    srcs = _valid_sources(item.get("sources"), articles)
    if not srcs:
        print(f"    [drop] 出典なし: {text[:30]}")
        return None
    nt = unicodedata.normalize("NFKC", text)
    if _CUT_NUM_RE.search(nt):
        print(f"    [drop] 途切れた数値: {text[:30]}")
        return None
    src_text = " ".join(_article_text(articles[n - 1]) for n in srcs).replace(",", "")
    for num in _PCT_RE.findall(nt):
        if _num_pos(num, src_text) < 0:
            print(f"    [drop] 元記事に無い%({num}%): {text[:30]}")
            return None
    out = {"text": text, "sources": srcs}
    if "category" in item:
        out["category"] = item.get("category")
    return out


_UP_RE = re.compile(r"\b(rose|rise|rises|rising|gained|gains|gain|up|climbed|climbs|rallied|rallies|jumped|jumps|advanced|advances|higher|surged|soared|added|adds|increased|edged up)\b", re.I)
_DOWN_RE = re.compile(r"\b(fell|fall|falls|falling|dropped|drops|down|slid|slides|declined|declines|lost|loses|lower|sank|sinks|tumbled|slumped|shed|slipped|retreated|decreased|edged down)\b", re.I)


def _fmt_num(v):
    """0.85→'0.85'、1.0→'1'(quoteとの照合・表示用。勝手に桁を足さない)"""
    return f"{abs(v):g}"


def _direction_in_quote(quote, num_str):
    """quote内で、数値に一番近い手前の向きの語(なければ後ろも見る)から上昇=+1/下落=-1/不明=0"""
    q = quote
    pos = _num_pos(num_str, q)
    # 数値の直前に+/-の符号が付いていればそれを優先
    if pos > 0:
        k = pos - 1
        while k >= 0 and q[k] == " ":
            k -= 1
        if k >= 0 and q[k] == "+":
            return 1
        if k >= 0 and q[k] in "-−":
            return -1
    hits = [(m.start(), 1) for m in _UP_RE.finditer(q)] + [(m.start(), -1) for m in _DOWN_RE.finditer(q)]
    if not hits:
        return 0
    if pos < 0:
        pos = len(q)
    before = [h for h in hits if h[0] <= pos]
    if before:
        return max(before)[1]
    return min(hits)[1]


def _check_market(m, articles):
    """数値カード1枚を2-6の7項目で検証する。合格ならカード用dict、不合格ならNone(理由をログ)"""
    if not isinstance(m, dict):
        return None
    name = m.get("name")
    def drop(reason):
        print(f"    [drop card] {name}: {reason}")
        return None
    if name not in MARKET_NAMES:
        return drop("指数名が一覧外")
    src = m.get("source")
    if isinstance(src, bool) or not isinstance(src, int) or not (1 <= src <= len(articles)):
        return drop("出典番号が実在しない")
    quote = m.get("quote")
    if not isinstance(quote, str) or _is_empty(quote):
        return drop("quoteが空")
    nq = _norm(quote)
    if nq not in _article_text(articles[src - 1]):
        return drop("quoteが元記事に無い")
    if "..." in quote or "…" in quote:
        return drop("quoteに省略記号")
    value_text = m.get("value_text")
    if _is_empty(value_text) or not isinstance(value_text, str):
        value_text = None
    change = m.get("change_value")
    if isinstance(change, bool) or not isinstance(change, (int, float)):
        change = None
    if value_text is None and change is None:
        return drop("値も変動も無い")
    q_nocomma = nq.replace(",", "")
    if value_text is not None:
        vm = re.search(r"\d[\d,]*(?:\.\d+)?", unicodedata.normalize("NFKC", value_text))
        if not vm or _num_pos(vm.group(0).replace(",", ""), q_nocomma) < 0:
            return drop(f"値{value_text}がquoteに無い")
    direction = None  # +1/-1/0(不明)/None(変動なし)
    unit = m.get("change_unit") if m.get("change_unit") in ("%", "bp") else "%"
    if change is not None:
        num_str = _fmt_num(change)
        if _num_pos(num_str, q_nocomma) < 0:
            return drop(f"変動{num_str}がquoteに無い")
        q_dir = _direction_in_quote(q_nocomma, num_str)
        if change == 0:
            if q_dir != 0:
                return drop("変動0なのにquoteに向きの語がある")
            direction = "flat"
        elif q_dir == 0:
            direction = 0  # 向きの記載なし → 矢印を付けない
        elif (change > 0) != (q_dir > 0):
            return drop(f"向きの食い違い(change={change}, quote={'上昇' if q_dir > 0 else '下落'})")
        else:
            direction = 1 if change > 0 else -1
    return {
        "name": name,
        "value_text": value_text,
        "change": change,
        "unit": unit,
        "direction": direction,
        "source": src,
        "source_name": articles[src - 1].get("source", ""),
    }


SECTION_KEYS = [("stock", 5), ("fed", 3), ("jobs", 3), ("earnings", 3)]
DEFAULT_HEADLINE = "本日の米国経済まとめ"


def parse_summary(raw, econ_articles):
    """経済要約のJSONを読み、検証済みの中身だけを返す。
    読めなければ ok=False(要約なしモード)"""
    data = _loads_loose(raw)
    if not isinstance(data, dict):
        print("  [WARN] summary JSON parse failed")
        return {"ok": False, "headline": "米国経済ニュース(要約準備中)",
                "key_points": [], "markets": [], "sections": {k: [] for k, _ in SECTION_KEYS}}

    headline = data.get("headline")
    if not isinstance(headline, str) or _is_empty(headline) or len(headline.strip()) > 20:
        headline = DEFAULT_HEADLINE
    headline = headline.replace("**", "").strip()

    key_points = []
    kp = data.get("key_points") if isinstance(data.get("key_points"), list) else []
    for item in kp:
        line = _check_line(item, econ_articles)
        if line:
            cat = line.get("category")
            line["category"] = cat if cat in KEY_CATEGORIES else "その他"
            key_points.append(line)
        if len(key_points) == 3:
            break

    cards = {}
    mk = data.get("markets") if isinstance(data.get("markets"), list) else []
    for m in mk:
        c = _check_market(m, econ_articles)
        if c and c["name"] not in cards:
            cards[c["name"]] = c
    markets = [cards[n] for n in MARKET_NAMES if n in cards]
    print(f"  数値カード: AI出力{len(mk)}枚 → 照合通過{len(markets)}枚")

    sections = {}
    secs = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    for key, limit in SECTION_KEYS:
        items = secs.get(key) if isinstance(secs.get(key), list) else []
        lines = [l for l in (_check_line(i, econ_articles) for i in items) if l]
        sections[key] = lines[:limit]

    if not key_points and not markets and not any(sections.values()):
        # 照合ですべて捨てられた日は、見出しだけの空のページにせず「要約準備中」に切り替える
        print("  [WARN] summary items all dropped by validation")
        return {"ok": False, "headline": "米国経済ニュース(要約準備中)",
                "key_points": [], "markets": [], "sections": {k: [] for k, _ in SECTION_KEYS}}
    return {"ok": True, "headline": headline, "key_points": key_points,
            "markets": markets, "sections": sections}


def parse_major_news(raw, major_articles):
    """主要ニュースのJSONを読み、検証済みの記事だけを返す。0件なら ok=False(見出しのみ表示)"""
    data = _loads_loose(raw)
    items = []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        for it in data["items"]:
            if not isinstance(it, dict):
                continue
            title = it.get("title")
            if not isinstance(title, str) or _is_empty(title):
                continue
            srcs = _valid_sources(it.get("sources"), major_articles)
            bullets = [b for b in (_check_line(x, major_articles)
                                   for x in (it.get("bullets") if isinstance(it.get("bullets"), list) else [])) if b][:3]
            for b in bullets:
                for n in b["sources"]:
                    if n not in srcs:
                        srcs.append(n)
            if not srcs:
                continue
            lead = it.get("lead")
            lead = lead.replace("**", "").strip() if isinstance(lead, str) and not _is_empty(lead) else ""
            if lead and _CUT_NUM_RE.search(unicodedata.normalize("NFKC", lead)):
                lead = ""
            cat = it.get("category")
            items.append({
                "category": cat if cat in MAJOR_CATEGORIES else "",
                "title": title.replace("**", "").strip(),
                "lead": lead,
                "bullets": bullets,
                "sources": srcs,
            })
            if len(items) == 3:
                break
    if not items:
        print("  [WARN] 主要ニュースの要約を使えないため、英語見出しのみ表示します")
    return {"ok": bool(items), "items": items}


# ========================================
# 4. HTMLを生成
# ========================================

_ICONS = {
    "trending-up": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 17 9 11 13 15 21 6"/><polyline points="14 6 21 6 21 13"/></svg>',
    "bank": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="3" y1="21" x2="21" y2="21"/><line x1="5" y1="21" x2="5" y2="10"/><line x1="19" y1="21" x2="19" y2="10"/><line x1="12" y1="21" x2="12" y2="10"/><polygon points="12 3 21 8 3 8"/></svg>',
    "briefcase": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>',
    "bar-chart": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>',
    "newspaper": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4h13a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H7a3 3 0 0 1-3-3V4z"/><path d="M18 8h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><line x1="8" y1="8" x2="14" y2="8"/><line x1="8" y1="12" x2="14" y2="12"/><line x1="8" y1="16" x2="11" y2="16"/></svg>',
}


def _esc(s):
    """HTMLへの埋め込み用にエスケープ(外部APIの文字列を信用しない)"""
    return html.escape(s or "", quote=True)


SECTION_META = {
    "stock": ("sec-stock", "株式市場", "株式", "trending-up"),
    "fed": ("sec-fed", "FRB・金融政策", "FRB", "bank"),
    "jobs": ("sec-jobs", "雇用・物価", "雇用・物価", "briefcase"),
    "earnings": ("sec-earnings", "企業決算", "決算", "bar-chart"),
}


def _src_links(srcs, articles):
    """各行末の「出典」リンク。複数あるときは「出典1」「出典2」"""
    out = []
    for i, n in enumerate(srcs):
        a = articles[n - 1]
        if not a.get("url"):
            continue
        label = "出典" if len(srcs) == 1 else f"出典{i + 1}"
        name = a.get("source") or "元記事"
        out.append(
            f'<a class="src" href="{_esc(a["url"])}" target="_blank" rel="noopener noreferrer" '
            f'aria-label="{_esc(label)}:{_esc(name)}(新しいタブで開く)">{label}</a>'
        )
    return "".join(out)


def _change_label(c):
    """変動率の表示文字列と読み上げ文。マイナスはU+2212、プラスは+を必ず付ける"""
    if c["change"] is None:
        return "", ""
    unit = c["unit"]
    num = _fmt_num(c["change"])
    unit_read = "ベーシスポイント" if unit == "bp" else "%"
    if c["direction"] == "flat":
        return f"― {num}{unit}", f"前の取引日比{num}{unit_read}、横ばい"
    if c["direction"] == 1:
        return f"+{num}{unit}", f"前の取引日比{num}{unit_read}上昇"
    if c["direction"] == -1:
        return f"−{num}{unit}", f"前の取引日比{num}{unit_read}下落"
    return f"{num}{unit}", f"変動{num}{unit_read}、向きの記載なし"


def _market_card(c):
    cls = {1: "up", -1: "down"}.get(c["direction"], "flat")
    arrow = {1: "▲", -1: "▼", "flat": "―"}.get(c["direction"], "")
    chg, chg_read = _change_label(c)
    value_html = (f'<span class="card-value">{_esc(c["value_text"])}</span>' if c["value_text"]
                  else '<span class="card-value none">値の記載なし</span>')
    if chg:
        arrow_html = f'<span aria-hidden="true">{arrow} </span>' if arrow and c["direction"] != "flat" else ""
        if c["direction"] == "flat":
            chg_html = f'<span class="card-chg">{_esc(chg)}</span>'
        else:
            chg_html = f'<span class="card-chg">{arrow_html}{_esc(chg)}</span>'
        if c["direction"] == 0:
            chg_html += '<span class="card-note">向きの記載なし</span>'
    else:
        chg_html = '<span class="card-chg none">変動の記載なし</span>'
    read = "、".join(x for x in [c["name"], c["value_text"] or "値の記載なし", chg_read or "変動の記載なし",
                                 f'出典{c["source_name"]}' if c["source_name"] else ""] if x)
    return f"""
        <li class="card {cls}" role="group" aria-label="{_esc(read)}">
          <span class="card-name" aria-hidden="true">{_esc(c['name'])}</span>
          <span aria-hidden="true">{value_html}</span>
          <span aria-hidden="true">{chg_html}</span>
          <span class="card-src" aria-hidden="true">{_esc(c['source_name'])}</span>
        </li>"""


def _source_list(econ, econ_articles, major, major_articles):
    """元記事一覧:引用された記事を先頭に、残りは経済関連の記事だけ。最大10本"""
    picked, seen = [], set()

    def add(a):
        key = a.get("url") or a.get("title")
        if a.get("title") and a.get("url") and key not in seen:
            seen.add(key)
            picked.append(a)

    if econ["ok"]:
        for kp in econ["key_points"]:
            for n in kp["sources"]:
                add(econ_articles[n - 1])
        for c in econ["markets"]:
            add(econ_articles[c["source"] - 1])
        for key, _ in SECTION_KEYS:
            for l in econ["sections"][key]:
                for n in l["sources"]:
                    add(econ_articles[n - 1])
    for it in major["items"]:
        for n in it["sources"]:
            add(major_articles[n - 1])
    for a in econ_articles:
        if _is_econ(a):
            add(a)  # 10本に満たなくても、経済と無関係な記事では埋めない
    return picked[:10]


def generate_html(econ, econ_articles, major, major_articles, now=None):
    """静的HTML1枚を返す(JSなし。外部読み込みはGoogle Fontsのみ)"""
    now = now or datetime.now(JST)
    date_str = _jp_date(now)
    time_str = f"{now.hour}:{now.minute:02d}"

    # ── 今日の要点 ──
    kp_html = ""
    if econ["ok"] and econ["key_points"]:
        lis = "".join(f"""
        <li class="kp">
          <span class="kp-num" aria-hidden="true">{i}</span>
          <div class="kp-body"><span class="tag">{_esc(k['category'])}</span><span class="kp-text">{_esc(k['text'])}</span>{_src_links(k['sources'], econ_articles)}</div>
        </li>""" for i, k in enumerate(econ["key_points"], 1))
        kp_html = f"""
    <section class="block" aria-labelledby="h-kp">
      <h2 id="h-kp">今日の要点</h2>
      <ol class="kps">{lis}
      </ol>
    </section>"""

    # ── 主な数値 ──
    mk_html = ""
    if econ["ok"] and econ["markets"]:
        cards = "".join(_market_card(c) for c in econ["markets"])
        mk_html = f"""
    <section class="block" aria-labelledby="h-mk">
      <h2 id="h-mk">主な数値</h2>
      <ul class="cards">{cards}
      </ul>
      <p class="note">※報道時点の値で、終値とは限りません</p>
    </section>"""

    # ── 主要ニュース(見出しのみ) ──
    if major["ok"]:
        heads = "".join(
            f'\n        <li><a href="#major-{i}">{_esc(it["title"])}</a></li>'
            for i, it in enumerate(major["items"], 1))
        major_note = ""
    else:
        fb = [a for a in major_articles if a.get("url")][:3]
        heads = "".join(
            f'\n        <li><a href="{_esc(a["url"])}" target="_blank" rel="noopener noreferrer" lang="en">{_esc(a["title"])}</a>'
            f'<span class="src-name">{_esc(a.get("source", ""))}</span></li>'
            for a in fb)
        major_note = '<p class="note">要約を作れなかったため、元記事の見出しのみ掲載しています</p>' if fb else ""
    major_heads_html = f"""
    <section class="block" id="major" aria-labelledby="h-major">
      <h2 id="h-major">主要ニュース</h2>
      <ul class="heads">{heads}
      </ul>{major_note}
    </section>""" if heads else ""

    # ── 分野別(3分層) ──
    sec_html, nav_links = "", []
    if econ["ok"]:
        for key, _ in SECTION_KEYS:
            lines = econ["sections"][key]
            if not lines:
                continue  # 該当なしの日はセクションごと出さない
            sid, title, short, icon = SECTION_META[key]
            nav_links.append((sid, short))
            lis = "".join(f'\n        <li><span>{_esc(l["text"])}</span>{_src_links(l["sources"], econ_articles)}</li>' for l in lines)
            sec_html += f"""
    <section class="block" id="{sid}" aria-labelledby="h-{sid}">
      <h2 id="h-{sid}"><span class="h-icon">{_ICONS[icon]}</span>{_esc(title)}</h2>
      <ul class="lines">{lis}
      </ul>
    </section>"""

    detail_html = ""
    if major["ok"]:
        arts = ""
        for i, it in enumerate(major["items"], 1):
            bl = "".join(f'\n          <li><span>{_esc(b["text"])}</span>{_src_links(b["sources"], major_articles)}</li>' for b in it["bullets"])
            tag = f'<span class="tag">{_esc(it["category"])}</span>' if it["category"] else ""
            lead = f'\n        <p class="lead">{_esc(it["lead"])}</p>' if it["lead"] else ""
            more = "" if it["bullets"] else f'<p class="lines-src">{_src_links(it["sources"], major_articles)}</p>'
            arts += f"""
      <article class="story" id="major-{i}" aria-labelledby="h-major-{i}">
        <h3 id="h-major-{i}">{tag}{_esc(it['title'])}</h3>{lead}
        <ul class="lines">{bl}
        </ul>{more}
      </article>"""
        nav_links.append(("major-detail", "主要ニュース"))
        detail_html = f"""
    <section class="block" id="major-detail" aria-labelledby="h-major-detail">
      <h2 id="h-major-detail"><span class="h-icon">{_ICONS['newspaper']}</span>主要ニュース 詳細</h2>{arts}
    </section>"""

    nav_html = ""
    if nav_links:
        nav_html = '\n    <nav class="jump" aria-label="分野へ移動">' + "".join(
            f'<a href="#{sid}">{_esc(label)}</a>' for sid, label in nav_links) + "</nav>"

    # ── 元記事一覧 ──
    srcs = _source_list(econ, econ_articles, major, major_articles)
    src_lis = "".join(
        f'\n        <li><a href="{_esc(a["url"])}" target="_blank" rel="noopener noreferrer">'
        f'<span class="src-name">{_esc(a.get("source", ""))}</span><span class="src-title" lang="en">{_esc(a["title"])}</span></a></li>'
        for a in srcs)
    src_html = f"""
    <details class="block sources"{' open' if not econ['ok'] else ''}>
      <summary>元記事一覧({len(srcs)}本)</summary>
      <ul class="src-list">{src_lis}
      </ul>
    </details>""" if srcs else ""

    notice = ""
    if not econ["ok"]:
        notice = '\n    <p class="notice">本日はAIによる要約を作れなかったため、元記事の見出しのみ掲載しています。</p>'

    headline = econ["headline"]
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
<link rel="icon" href="data:,">
<title>米国経済ニュース | {date_str}</title>
<meta name="description" content="{_esc(headline)} | AIが自動生成する米国経済ニュースの朝刊まとめ">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:wght@600;700&family=Noto+Sans+JP:wght@400;500;700&family=Noto+Serif+JP:wght@700&family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {{
    color-scheme: light;
    --brand: #dc2626; --ink: #16181d; --text: #24272e; --muted: #5b6472; --line: #e6e8eb;
    --up: #166534; --up-bg: #f0fdf4; --down: #b91c1c; --down-bg: #fef2f2; --flat: #475569; --flat-bg: #f1f5f9;
    --focus: #1e40af;
    --sans: 'Roboto', 'Noto Sans JP', sans-serif; --serif: 'Newsreader', 'Noto Serif JP', serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  @media (prefers-reduced-motion: no-preference) {{ html {{ scroll-behavior: smooth; }} }}
  body {{ background: #ffffff; color: var(--text); font-family: var(--sans); font-size: 16px; line-height: 1.8; }}
  a {{ color: inherit; }}
  :focus-visible {{ outline: 3px solid var(--focus); outline-offset: 2px; }}
  [id] {{ scroll-margin-top: 64px; }}

  header {{ position: sticky; top: 0; z-index: 10; background: #ffffff; border-bottom: 3px solid var(--brand); }}
  .bar {{ max-width: 680px; margin: 0 auto; padding: 0 16px; height: 45px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
  .logo {{ font-family: 'Newsreader', serif; font-size: 20px; font-weight: 700; color: var(--ink); letter-spacing: 0.02em; }}
  .logo span {{ color: var(--brand); }}
  .stamp {{ font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }}

  main {{ max-width: 680px; margin: 0 auto; padding: 24px 16px 56px; }}
  h1 {{ font-family: var(--serif); font-size: 26px; font-weight: 700; line-height: 1.35; color: var(--ink); }}
  .sub {{ font-size: 13px; color: var(--muted); line-height: 1.6; margin-top: 4px; }}
  .notice {{ margin-top: 24px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 8px; font-size: 15px; }}

  .block {{ margin-top: 40px; }}
  h2 {{ display: flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 700; line-height: 1.4; color: var(--ink); margin-bottom: 16px; }}
  .h-icon {{ display: inline-flex; width: 20px; height: 20px; color: var(--muted); flex-shrink: 0; }}
  .h-icon svg {{ width: 100%; height: 100%; }}

  .kps {{ list-style: none; display: grid; gap: 12px; }}
  .kp {{ display: grid; grid-template-columns: 28px 1fr; gap: 12px; align-items: start; }}
  .kp-num {{ width: 28px; height: 28px; border-radius: 50%; background: var(--brand); color: #ffffff; font-size: 15px; font-weight: 700; display: flex; align-items: center; justify-content: center; margin-top: 1px; font-variant-numeric: tabular-nums; }}
  .kp-body {{ font-size: 17px; font-weight: 500; line-height: 1.6; color: var(--ink); }}
  .tag {{ display: inline-block; font-size: 12px; font-weight: 500; line-height: 1.5; color: var(--muted); border: 1px solid #cfd4da; border-radius: 4px; padding: 0 6px; margin-right: 8px; vertical-align: 2px; white-space: nowrap; }}

  .cards {{ list-style: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }}
  .card {{ display: flex; flex-direction: column; gap: 2px; border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; font-variant-numeric: tabular-nums; }}
  .card.up {{ background: var(--up-bg); }} .card.up .card-chg {{ color: var(--up); }}
  .card.down {{ background: var(--down-bg); }} .card.down .card-chg {{ color: var(--down); }}
  .card.flat {{ background: var(--flat-bg); }} .card.flat .card-chg {{ color: var(--flat); }}
  .card-name {{ font-size: 13px; color: var(--muted); line-height: 1.4; }}
  .card-value {{ display: block; font-family: 'Roboto', sans-serif; font-size: 22px; font-weight: 700; color: var(--ink); line-height: 1.3; }}
  .card-value.none {{ font-family: var(--sans); font-size: 13px; font-weight: 400; color: var(--muted); line-height: 1.7; padding: 3px 0 2px; }}
  .card-chg {{ display: block; font-family: 'Roboto', sans-serif; font-size: 16px; font-weight: 700; line-height: 1.4; }}
  .card-chg.none {{ font-family: var(--sans); font-size: 13px; font-weight: 400; color: var(--muted); }}
  .card-note {{ display: block; font-size: 12px; color: var(--flat); line-height: 1.4; }}
  .card-src {{ font-size: 12px; color: var(--muted); line-height: 1.4; margin-top: 4px; }}
  .note {{ font-size: 12px; color: var(--muted); line-height: 1.6; margin-top: 8px; }}

  .heads {{ list-style: none; border-top: 1px solid var(--line); }}
  .heads li {{ border-bottom: 1px solid var(--line); }}
  .heads a {{ display: block; padding: 10px 0; min-height: 44px; font-size: 16px; font-weight: 500; line-height: 1.6; color: var(--ink); text-decoration: none; }}
  .heads a:hover {{ text-decoration: underline; text-underline-offset: 3px; }}
  .heads .src-name {{ display: block; margin-top: -8px; padding-bottom: 8px; }}

  .jump {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line); }}
  .jump a {{ display: inline-flex; align-items: center; min-height: 44px; padding: 0 14px; border: 1px solid #cfd4da; border-radius: 6px; font-size: 15px; font-weight: 500; color: var(--ink); text-decoration: none; }}
  .jump a:hover {{ border-color: var(--ink); }}

  .lines {{ list-style: none; display: grid; gap: 12px; }}
  .lines li {{ position: relative; padding-left: 16px; font-size: 16px; line-height: 1.8; }}
  .lines li::before {{ content: ""; position: absolute; left: 2px; top: 0.8em; width: 5px; height: 5px; border-radius: 50%; background: #9aa1ac; }}
  .src {{ display: inline-block; margin-left: 8px; font-size: 12px; color: var(--muted); text-underline-offset: 2px; white-space: nowrap; }}
  .src + .src {{ margin-left: 6px; }}
  .src:hover {{ color: var(--ink); }}

  .story + .story {{ margin-top: 32px; padding-top: 24px; border-top: 1px solid var(--line); }}
  .story h3 {{ font-family: var(--serif); font-size: 19px; font-weight: 700; line-height: 1.45; color: var(--ink); margin-bottom: 8px; }}
  .story h3 .tag {{ font-family: var(--sans); vertical-align: 3px; }}
  .lead {{ font-size: 16px; font-weight: 500; line-height: 1.7; margin-bottom: 12px; color: var(--ink); }}

  .sources summary {{ display: flex; align-items: center; min-height: 44px; font-size: 16px; font-weight: 700; color: var(--ink); cursor: pointer; border-top: 1px solid var(--line); }}
  .src-list {{ list-style: none; }}
  .src-list a {{ display: block; padding: 10px 0; border-bottom: 1px solid var(--line); text-decoration: none; }}
  .src-list a:hover .src-title {{ text-decoration: underline; }}
  .src-name {{ display: block; font-size: 12px; color: var(--muted); line-height: 1.5; }}
  .src-title {{ display: block; font-size: 14px; line-height: 1.6; color: var(--text); }}

  footer {{ border-top: 1px solid var(--line); }}
  footer p {{ max-width: 680px; margin: 0 auto; padding: 20px 16px 32px; font-size: 12px; line-height: 1.6; color: var(--muted); }}

  @media (min-width: 600px) {{
    main {{ padding-top: 40px; }}
    h1 {{ font-size: 34px; }}
    h2 {{ font-size: 20px; }}
    .block {{ margin-top: 48px; }}
    .kp-body {{ font-size: 18px; }}
    .lines li {{ font-size: 16.5px; }}
    .stamp, .src-name {{ font-size: 13px; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    * {{ transition: none !important; }}
  }}
</style>
</head>
<body>
<header>
  <div class="bar">
    <div class="logo">ECONO<span>BOT</span></div>
    <div class="stamp">{date_str} {time_str} 更新</div>
  </div>
</header>
<main id="main">
  <h1>{_esc(headline)}</h1>
  <p class="sub">直近24〜48時間の英語報道からAIが自動要約</p>{notice}{kp_html}{mk_html}{major_heads_html}{nav_html}{sec_html}{detail_html}{src_html}
</main>
<footer>
  <p>EconoBot。この内容はAIが自動で作成したものです。誤りを含むことがあるため、投資判断の根拠にしないでください。</p>
</footer>
</body>
</html>"""


# ========================================
# 5. GitHub PagesにHTMLをコミット
# ========================================
def publish_to_github_pages(html_content):
    api_base = f"https://api.github.com/repos/{GITHUB_REPO}/contents/index.html"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "EconoBot/1.0",
    }

    # 既存ファイルのSHAを取得
    sha = None
    req = urllib.request.Request(api_base, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            sha = json.loads(res.read().decode()).get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise

    content_b64 = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    payload = {"message": f"📰 EconoBot update: {now_str}", "content": content_b64, "branch": "main"}
    if sha:
        payload["sha"] = sha

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(api_base, data=body, headers=headers, method="PUT")
    with urllib.request.urlopen(req, timeout=15) as res:
        json.loads(res.read().decode())

    username, reponame = GITHUB_REPO.split("/")
    page_url = f"https://{username}.github.io/{reponame}/"
    print(f"  公開URL: {page_url}")
    return page_url


# ========================================
# 6. Slackに投稿(Block Kit)
# ========================================
def _slack_esc(s):
    """Slackの書式で特別な意味を持つ & < > を置き換える"""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


SLACK_SHORT = {"ナスダック総合": "ナスダック", "ダウ平均": "ダウ", "米10年債利回り": "米10年債"}


def build_slack_payload(page_url, econ, major, major_articles, now=None):
    """Slackに送るJSON(dict)を作る。投稿はしない(確認時はこれをファイルに書き出す)"""
    now = now or datetime.now(JST)
    date_str = _jp_date(now)
    headline = econ["headline"]
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"米国経済 朝刊|{date_str}"[:150]}}]
    if econ["ok"]:
        lines = [f"*{_slack_esc(headline)}*"]
        lines += [f"{i}. {_slack_esc(k['text'])}" for i, k in enumerate(econ["key_points"], 1)]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
        if econ["markets"]:
            parts = []
            for c in econ["markets"][:3]:
                chg, _ = _change_label(c)
                arrow = {1: "▲", -1: "▼"}.get(c["direction"], "")
                name = SLACK_SHORT.get(c["name"], c["name"])
                parts.append(" ".join(x for x in [name, c["value_text"] or "", f"{arrow}{chg}" if chg else ""] if x))
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": _slack_esc("  |  ".join(parts))}]})
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": "本日はAI要約を作れなかったため、元記事の見出しのみ掲載しています"}})
    if major["ok"]:
        heads = [it["title"] for it in major["items"]]
    else:
        heads = [a["title"] for a in major_articles[:3]]
    if heads:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": "*主要ニュース*\n" + "\n".join(f"・{_slack_esc(h)}" for h in heads)}})
    blocks.append({"type": "section", "text": {"type": "mrkdwn",
                   "text": f"<{page_url}|ページで詳しく読む>  ・  <{page_url}#major|主要ニュースへ>"}})
    text = f"米国経済 朝刊|{headline}" if econ["ok"] else f"米国経済 朝刊|{date_str}(要約準備中)"
    return {"text": text, "blocks": blocks}


def _slack_text_only(payload, page_url):
    """blocks付きが400で失敗した時の送り直し用:文字だけの1段落"""
    lines = [payload["text"]]
    for b in payload["blocks"][1:]:
        if b["type"] == "section":
            lines.append(b["text"]["text"])
        elif b["type"] == "context":
            lines.append(b["elements"][0]["text"])
    return {"text": "\n".join(lines)}


def _post_json(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return res.status


def post_to_slack(page_url, econ, major, major_articles):
    payload = build_slack_payload(page_url, econ, major, major_articles)
    try:
        status = _post_json(SLACK_WEBHOOK_URL, payload)
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        print("  blocks付き投稿が400 → 文字だけで1回送り直し")
        status = _post_json(SLACK_WEBHOOK_URL, _slack_text_only(payload, page_url))
    print(f"  Slack投稿完了: {status}")


# ========================================
# メイン
# ========================================
def notify_failure(stage, error):
    """途中で失敗した場合、サイレントに落ちずSlackにも異常を知らせる"""
    try:
        payload = json.dumps({
            "text": f":warning: *EconoBot エラー*\n段階: {stage}\n内容: {error}"
        }).encode("utf-8")
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as notify_err:
        print(f"  ⚠️ 失敗通知にも失敗: {notify_err}")


def main():
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"環境変数が未設定です: {', '.join(missing)}")
    try:
        print("📰 経済ニュース取得中...")
        articles = fetch_news()
        econ_articles = usable_econ_articles(articles)
        print(f"  {len(articles)}件取得(要約に使う記事 {len(econ_articles)}件)")

        print("📰 主要ニュース取得中...")
        major_articles = usable_major_articles(fetch_major_news())
        print(f"  {len(major_articles)}件取得")

        print("🤖 Geminiで経済ニュース要約中...")
        econ = parse_summary(summarize_with_gemini(econ_articles), econ_articles)
        print(f"  見出し: {econ['headline']}")

        print("🤖 Geminiで主要ニュース要約中...")
        major = parse_major_news(summarize_major_news(major_articles), major_articles)
        for it in major["items"]:
            print(f"  主要: {it['title']}")

        print("🎨 HTMLページ生成中...")
        page_html = generate_html(econ, econ_articles, major, major_articles)

        print("🚀 GitHub Pagesに公開中...")
        page_url = publish_to_github_pages(page_html)

        print("📤 Slackに投稿中...")
        post_to_slack(page_url, econ, major, major_articles)

        print("✅ 完了！")
    except Exception as e:
        print(f"❌ エラー発生: {e}")
        notify_failure(stage=type(e).__name__, error=str(e))
        raise


if __name__ == "__main__":
    main()
