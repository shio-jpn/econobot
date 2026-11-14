"""
EconoBot - 米国経済ニュース自動要約
BBCスタイルHTMLページを生成 → GitHub Pages公開 → SlackにURLを投稿

数値:Yahoo Financeのchart API(主)。取れない系列はFRED(セントルイス連銀)の値を日付つきで使う(2026-11-14)
ニュース:NewsAPI(無料版は記事が約24時間遅れ)+信頼媒体のRSS(CNBC・BBC・NPR・FRB)を併用(2026-11-14)
"""

import os
import json
import re
import time
import base64
import html
import unicodedata
import email.utils
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta, date

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

try:  # GitHub Actions(Ubuntu)では必ず使える。使えない環境では下の計算で代用する
    from zoneinfo import ZoneInfo
    _NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _NY = None


def _jp_date(now):
    """「10月8日(木)」。strftimeの%-mはWindowsで動かないため、数値から組み立てる(dateでもdatetimeでも可)"""
    return f"{now.month}月{now.day}日({WEEKDAYS[now.weekday()]})"


def _md(d):
    """「11/12」"""
    return f"{d.month}/{d.day}"


def _to_iso_date(d):
    """'2026-11-13' / date / None → date または None"""
    if d is None:
        return None
    if isinstance(d, date):
        return d
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _us_dst(dt_utc):
    """米国の夏時間か(3月第2日曜2時〜11月第1日曜2時)。zoneinfoが無い環境の代用"""
    y = dt_utc.year

    def sunday(month, n):
        d = datetime(y, month, 1, tzinfo=timezone.utc)
        return d + timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))
    return sunday(3, 2) + timedelta(hours=7) <= dt_utc < sunday(11, 1) + timedelta(hours=6)


def _to_et(dt_utc):
    """UTCの日時を米国東部時間に直す"""
    if _NY is not None:
        return dt_utc.astimezone(_NY)
    return dt_utc.astimezone(timezone(timedelta(hours=-4 if _us_dst(dt_utc) else -5)))


def _pub_et(a):
    """記事の配信日時(publishedAt、UTCのISO形式)を米国東部時間で返す。読めなければNone"""
    s = (a or {}).get("publishedAt") or ""
    try:
        dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return _to_et(dt)


def _latest_pub_date(articles):
    """記事のうち、いちばん新しい配信日(米国東部時間の日付)"""
    ds = [d.date() for d in (_pub_et(a) for a in articles) if d]
    return max(ds) if ds else None


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
# 1. ニュースを取得(NewsAPI+信頼媒体のRSS)
# ========================================
# 信頼できる報道機関・公的機関だけを使う(2026-10-08 Shio指示「BBCなど公式の信憑性の高い情報のみ」)。
# NewsAPIのeverything検索はこのドメインに限定し、top-headlines・RSSは取得後にURLで絞り込む。
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


def _news_get(req):
    """NewsAPIを1回呼ぶ。1つの検索が失敗しても実行全体は止めず、空の結果として続ける(2026-10-14)"""
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read().decode())
    except Exception as e:
        print(f"    [NewsAPI] 取得失敗(この検索は飛ばす): {type(e).__name__}")
        return {"articles": []}


def _from_newsapi(a):
    return {
        "title": a.get("title", ""),
        "description": _clean_desc(a.get("description", "")),
        "content": _clean_desc(a.get("content") or ""),
        "source": a.get("source", {}).get("name", ""),
        "url": a.get("url", ""),
        "publishedAt": a.get("publishedAt", ""),
    }


# NewsAPIの無料版は記事が約24時間遅れで届く。直前の取引日の記事を拾うため、信頼媒体が無料・キー不要で
# 公開しているRSSを併用する(2026-11-14、司令塔判断。各URLは11-14に取得して11/13の記事が返ることを確認)
RSS_FEEDS = [
    ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),  # 経済
    ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),  # 金融
    ("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("NPR", "https://feeds.npr.org/1006/rss.xml"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
]
_UA = "Mozilla/5.0 (compatible; EconoBot/1.0)"   # Yahoo・一部のRSSはUser-Agentが無いと断る
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", s or ""))).strip()


def _rss_items(xml_bytes, source):
    """RSSのXMLを、NewsAPIと同じ形の記事のリストにする(配信日時はUTCのISO形式に直す)"""
    root = ET.fromstring(xml_bytes)
    out = []
    for it in root.iter("item"):
        title = _strip_html(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        try:
            dt = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            published = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, IndexError):
            published = ""
        if title and link:
            out.append({"title": title, "description": _clean_desc(_strip_html(it.findtext("description"))),
                        "content": "", "source": source, "url": link, "publishedAt": published, "via": "rss"})
    return out


def fetch_rss(hours=48, now=None):
    """信頼媒体のRSS。1つのフィードが取れなくても続ける。配信日時の無い記事・48時間より古い記事は使わない"""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    articles = []
    for source, url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=15) as res:
                items = _rss_items(res.read(), source)
            recent = [a for a in items if a["publishedAt"] >= cutoff]
            print(f"    [RSS {source}] {len(items)}件中 {len(recent)}件が{hours}時間以内")
            articles += recent
        except Exception as e:
            print(f"    [RSS {source}] 取得失敗(このフィードは飛ばす): {type(e).__name__}")
    return _only_trusted(articles, "RSS")


def _dedupe_newest(articles):
    """同じ見出し・同じURLは1本にまとめ、新しい順に並べる"""
    seen, unique = set(), []
    for a in sorted(articles, key=lambda x: x.get("publishedAt", ""), reverse=True):
        t, u = a.get("title"), a.get("url")
        if not t or t in seen or (u and u in seen):
            continue
        seen.add(t)
        if u:
            seen.add(u)
        unique.append(a)
    return unique


def fetch_news(rss_articles=()):
    """経済ニュースを取得:NewsAPI(top-headlines+everything)+RSS"""
    articles = []
    if not NEWS_API_KEY:
        print("    [NewsAPI] キーが無いため飛ばす(RSSのみで続ける)")
    else:
        # ① top-headlines: 米国ビジネスの最新トップニュース
        for category, q in [("business", ""), ("general", "economy OR stock OR Fed")]:
            params = {"country": "us", "category": category, "pageSize": 10, "apiKey": NEWS_API_KEY}
            if q:
                params["q"] = q
            url = f"https://newsapi.org/v2/top-headlines?{urllib.parse.urlencode(params)}"
            data = _news_get(urllib.request.Request(url, headers={"User-Agent": "EconoBot/1.0"}))
            fetched = data.get("articles", [])
            print(f"    [top-headlines/{category}] {len(fetched)}件")
            articles += [_from_newsapi(a) for a in fetched]

        # ② everything: キーワード検索で補完(直近48時間)
        from_date = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        queries = [
            "S&P 500 Nasdaq stock market",
            "stocks biggest movers shares surge plunge",
            "Wall Street sector technology energy bank stocks",
            "Federal Reserve interest rate",
            "inflation CPI jobs unemployment",
            "jobless claims layoffs hiring labor market wages",
            "earnings revenue quarterly results",
        ]
        for query in queries:
            params = urllib.parse.urlencode({
                "q": query, "language": "en", "sortBy": "publishedAt",
                "domains": ",".join(TRUSTED_DOMAINS), "from": from_date, "pageSize": 8,
                "apiKey": NEWS_API_KEY,
            })
            data = _news_get(urllib.request.Request(f"https://newsapi.org/v2/everything?{params}",
                                                    headers={"User-Agent": "EconoBot/1.0"}))
            fetched = data.get("articles", [])
            print(f"    [{query[:25]}...] {len(fetched)}件")
            articles += [_from_newsapi(a) for a in fetched]
        articles = _only_trusted(articles, "経済")

    unique = _dedupe_newest(articles + list(rss_articles))
    print(f"  合計 {len(unique)}件取得(うちRSS {sum(1 for a in unique if a.get('via') == 'rss')}件)")
    return unique


# ========================================
# 1b. 主要ニュース(政策・国際・AI・半導体)を取得
# ========================================
def fetch_major_news(rss_articles=()):
    """主要ニュース取得:NewsAPI(top-headlines+キーワード検索48時間)+RSS(FRBの発表は除く)"""
    articles = []
    if not NEWS_API_KEY:
        print("    [NewsAPI] キーが無いため飛ばす(RSSのみで続ける)")
    else:
        params = urllib.parse.urlencode({"country": "us", "pageSize": 10, "apiKey": NEWS_API_KEY})
        data = _news_get(urllib.request.Request(f"https://newsapi.org/v2/top-headlines?{params}",
                                                headers={"User-Agent": "EconoBot/1.0"}))
        fetched = data.get("articles", [])
        print(f"    [top-headlines/us] {len(fetched)}件")
        articles += [_from_newsapi(a) for a in fetched]

        from_date = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        queries = [
            "Trump White House policy executive order",
            "artificial intelligence AI technology OpenAI Google",
            "semiconductor chip NVIDIA TSMC export",
        ]
        for query in queries:
            params = urllib.parse.urlencode({
                "q": query, "language": "en", "sortBy": "publishedAt",
                "domains": ",".join(TRUSTED_DOMAINS), "from": from_date, "pageSize": 8,
                "apiKey": NEWS_API_KEY,
            })
            data = _news_get(urllib.request.Request(f"https://newsapi.org/v2/everything?{params}",
                                                    headers={"User-Agent": "EconoBot/1.0"}))
            articles += [_from_newsapi(a) for a in data.get("articles", [])]
        articles = _only_trusted(articles, "主要")

    unique = _dedupe_newest(articles + [a for a in rss_articles if a.get("source") != "Federal Reserve"])
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


def _body_of(a):
    """説明文+本文の冒頭(NewsAPIの無料枠は本文が約200字で切れる)。重複していれば説明文だけ"""
    d, c = a.get("description", "") or "", a.get("content", "") or ""
    if c and c[:60] not in d:
        return f"{d} {c}".strip()
    return d


def _date_tag(a):
    """AIに渡す配信日「(11/12 木) 」(米国東部時間)。読めなければ付けない"""
    dt = _pub_et(a)
    return f"({dt.month}/{dt.day} {WEEKDAYS[dt.weekday()]}) " if dt else ""


def _numbered(articles):
    """記事を「[1] [WSJ] (11/12 木) タイトル: 説明文 本文冒頭」の形に並べる(AIに出典を番号で答えさせるため)"""
    return "\n".join(
        f"[{i}] [{a['source']}] {_date_tag(a)}{a['title']}: {_body_of(a)}"
        for i, a in enumerate(articles, 1)
    )


def usable_econ_articles(articles):
    """経済用にAIへ渡す記事(セール情報等を除いたもの)。番号はこの並びの1始まり"""
    return [a for a in articles if a.get("title") and not _NOISE_RE.search(a["title"])]


def usable_major_articles(articles):
    return [a for a in articles if a.get("title")]


_SRC_ARRAY = {"type": "ARRAY", "items": {"type": "INTEGER"}}
_NSTR = {"type": "STRING", "nullable": True}
_LINE = {
    "type": "OBJECT",
    "properties": {"text": {"type": "STRING"}, "sources": _SRC_ARRAY},
    "required": ["text", "sources"],
}
# 分野別(株式・FRB・雇用・決算)の1項目:何が/なぜ/影響を分けて受け取る(2026-11-14)
_STORY = {
    "type": "OBJECT",
    "properties": {"title": {"type": "STRING"}, "what": {"type": "STRING"},
                   "why": _NSTR, "effect": _NSTR, "sources": _SRC_ARRAY},
    "required": ["title", "what", "sources"],
}

MARKET_NAMES = ["S&P 500", "ナスダック総合", "ダウ平均", "VIX(恐怖指数)", "米10年債利回り", "米2年債利回り",
                "ドル円", "WTI原油", "ビットコイン"]
KEY_CATEGORIES = ["株式", "金融政策", "雇用・物価", "決算", "企業", "その他"]
MAJOR_CATEGORIES = ["政治・政策", "国際", "AI・テック", "半導体", "経済"]
WEEKDAY_JA = ["月", "火", "水", "木", "金", "不明"]
CONNECTIONS = ["株式市場", "金利・物価", "円・貿易", "産業・企業", "規制・政策"]

ECON_MARKETS_ITEM_ARRAY = {
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
}

ECON_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "market_move": {
            "type": "OBJECT", "nullable": True,
            "properties": {"day": {"type": "STRING", "enum": WEEKDAY_JA}, "text": {"type": "STRING"},
                           "quote": {"type": "STRING"}, "sources": _SRC_ARRAY},
            "required": ["day", "text", "quote", "sources"],
        },
        "key_points": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"category": {"type": "STRING", "enum": KEY_CATEGORIES},
                           "text": {"type": "STRING"}, "why": _NSTR, "sources": _SRC_ARRAY},
            "required": ["category", "text", "sources"]}},
        "sections": {"type": "OBJECT", "properties": {
            "stock": {"type": "ARRAY", "items": _STORY}, "fed": {"type": "ARRAY", "items": _STORY},
            "jobs": {"type": "ARRAY", "items": _STORY}, "earnings": {"type": "ARRAY", "items": _STORY}},
            "required": ["stock", "fed", "jobs", "earnings"]},
        "upcoming": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"date_iso": _NSTR, "event": {"type": "STRING"},
                           "quote": {"type": "STRING"}, "source": {"type": "INTEGER"}},
            "required": ["event", "quote", "source"]}},
        "markets": ECON_MARKETS_ITEM_ARRAY,
    },
    "required": ["headline", "key_points", "sections"],
}

MAJOR_SCHEMA = {
    "type": "OBJECT",
    "properties": {"items": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"category": {"type": "STRING", "enum": MAJOR_CATEGORIES},
                       "connection": {"type": "STRING", "enum": CONNECTIONS},
                       "title": {"type": "STRING"}, "lead": {"type": "STRING"},
                       "bullets": {"type": "ARRAY", "items": _LINE},
                       "why_it_matters": _NSTR, "sources": _SRC_ARRAY},
        "required": ["category", "connection", "title", "lead", "bullets", "sources"]}}},
    "required": ["items"],
}

# ========================================
# 定型文(仕様5章。AIの文ではない。数字の読み方・用語の説明は毎回同じ文を使う)
# ========================================
CARD_DESC = {
    "S&P 500": "米国の大企業約500社の株価をまとめた指数。米国株全体の物差し",
    "ナスダック総合": "ハイテク企業が多い市場の指数。IT・AI関連の動きが出やすい",
    "ダウ平均": "米国を代表する30社の株価から計算する指数",
    "ドル円": "1ドルが何円か。数字が大きくなるほど円安",
    "米10年債利回り": "米国が10年間お金を借りる時の金利。住宅ローンなど長い借入の金利の目安",
    "米2年債利回り": "2年の金利。FRBの金利の先行きを映しやすい",
    "VIX(恐怖指数)": "今後1か月の株価の荒れ具合の予想。高いほど市場が不安",
    "WTI原油": "米国の原油の値段(1バレルあたり)。ガソリン代のもと",
    "ビットコイン": "代表的な暗号資産。値動きが大きい",
}
POLICY_DESC = ("FRBは物価の上がり方(目標は年2%)と雇用を見て、この金利を上げ下げします。"
               "上げると借金の利息が増え、景気と物価を冷やす方向に働きます。")
IND_DESC = {
    "UNRATE": "働く意思があるのに仕事が無い人の割合。上がると景気が弱っているサイン",
    "PAYEMS": "会社などで働く人が前の月から何人増えたか。景気の強さを見る代表的な数字",
    "CES0500000003": "働く人の1時間あたりの給料。物価の伸びより高ければ、暮らしにゆとりが出やすい",
    "CPIAUCSL": "消費者が買うモノ・サービスの値段の変化。物価の代表的な物差し",
    "CPILFESL": "CPIから値動きの激しい食品とエネルギーを除いたもの。物価の流れを見る",
    "PCEPILFE": "FRBが物価の流れを見るのに重視する物差し。目標は年2%(PCE全体で測る)",
    "ICSA": "その週に新しく失業手当を申請した人の数。増えると解雇が増えているサイン",
    "JTSJOL": "企業が出している求人の数。多いほど人手が足りない",
}
# (キー, 見出し, 本文中で探す語, 説明)
GLOSSARY = [
    ("sp500", "S&P 500", ["S&P 500", "S&P500"], "米国の大企業約500社の株価をまとめた指数。米国株全体の動きを見る物差しで、日本で売られている米国株の投資信託の多くがこの指数に連動します。"),
    ("nasdaq", "ナスダック総合", ["ナスダック"], "ハイテク企業が多く上場する米国の市場「ナスダック」の、ほぼ全銘柄の株価をまとめた指数。IT・AI関連の動きが出やすい。"),
    ("dow", "ダウ平均", ["ダウ平均", "ダウ工業株"], "米国を代表する30社の株価から計算する、歴史の長い株価指数。"),
    ("frb", "FRB", ["FRB", "連邦準備制度"], "米国の中央銀行(連邦準備制度理事会)。物価と雇用の安定のために政策金利を上げ下げします。物価の目標は年2%。"),
    ("fomc", "FOMC", ["FOMC", "連邦公開市場委員会"], "FRBが政策金利を決める会議。年8回開かれます。"),
    ("policy", "政策金利", ["政策金利"], "FRBが決める短期の金利の目標。上げると借金の利息が増え、景気と物価を冷やす方向に、下げると温める方向に働きます。"),
    ("hike", "利上げ・利下げ", ["利上げ", "利下げ"], "政策金利を上げること・下げること。一般に、利上げは株価や物価の上昇を抑える方向に、利下げは押し上げる方向に働きやすい。"),
    ("yield", "利回り", ["利回り"], "国債を持ち続けた時に1年あたり受け取れる利益の割合。国債が売られて値段が下がると、利回りは上がります。米10年債の利回りは住宅ローンなどの金利の目安です。"),
    ("bp", "ベーシスポイント(bp)", ["ベーシスポイント", "bp"], "金利の変化を表す単位。1bp=0.01ポイントで、10bp上がると4.00%→4.10%。"),
    ("inflation", "インフレ", ["インフレ"], "物価が上がり続けること。同じお金で買える量が減ります。"),
    ("cpi", "CPI(消費者物価指数)", ["CPI", "消費者物価"], "消費者が買うモノやサービスの値段の変化を表す、毎月の統計。物価の代表的な物差し。"),
    ("core", "コア(CPI・PCE)", ["コアCPI", "コアPCE"], "物価の統計から、天候や国際情勢で値動きが激しい食品とエネルギーを除いたもの。物価の流れ(基調)を見るのに使います。"),
    ("pce", "PCE物価", ["PCE"], "個人消費の値段の変化を表す統計。FRBが物価目標(年2%)の判断に使います。"),
    ("jobs", "雇用統計", ["雇用統計", "雇用者数"], "米国の雇用の状況を表す毎月の統計で、原則として翌月の第1金曜に発表されます。働く人の増減と失業率が中心で、市場が最も重視する統計の1つ。"),
    ("claims", "新規失業保険申請", ["失業保険"], "その週に新しく失業手当を申請した人の数。毎週木曜に発表され、解雇の増減をいち早く映します。"),
    ("unemp", "失業率", ["失業率"], "働く意思があるのに仕事が無い人の割合。"),
    ("earnings", "決算", ["決算"], "会社が一定の期間(多くは3か月)の売上や利益を発表すること。市場の予想との差で株価が大きく動くことがあります。"),
    ("guidance", "業績見通し(ガイダンス)", ["業績見通し", "ガイダンス"], "会社が自ら示す、次の期の売上や利益の見込み。決算の数字そのものより株価を動かすこともあります。"),
    ("dividend", "配当", ["配当"], "会社が利益の一部を株主に配るお金。「特別配当」は、いつもの配当とは別に臨時で配るもの。"),
    ("ipo", "IPO(新規上場)", ["IPO", "新規上場"], "会社が株式を初めて市場に出し、誰でも売買できるようにすること。"),
    ("vix", "VIX(恐怖指数)", ["VIX", "恐怖指数"], "S&P 500の今後30日の値動きの大きさを、オプションという取引の価格から予想した数値。高いほど市場が不安を感じており、20を超えると不安が強い状態とされることが多い。"),
    ("yen", "円安・円高", ["円安", "円高"], "1ドル=150円が155円になるのが円安(円の価値が下がる)、145円になるのが円高。円安だと、米国株の投資信託は円で見て値上がりしやすく、輸入品やガソリンは高くなりやすい。"),
    ("ytd", "年初来", ["年初来"], "その年の最初(前の年の最後の取引日の終値)から今までの変化。"),
    ("tariff", "関税", ["関税"], "輸入品にかける税金。上がると輸入品の値段が上がりやすく、貿易が減ることがあります。"),
    ("recession", "景気後退", ["景気後退", "リセッション"], "経済活動が縮み、生産や雇用が減っていく状態。"),
    ("semis", "半導体", ["半導体"], "スマホ・AI・自動車に欠かせない電子部品(チップ)の材料・部品。エヌビディアやTSMCが代表的な企業。"),
    ("crypto", "暗号資産", ["暗号資産", "仮想通貨"], "インターネット上でやり取りされるデジタルの資産。ビットコインが代表で、値動きが大きい。"),
    ("yoy", "前年同月比", ["前年同月比", "前年比"], "1年前の同じ月と比べた変化。季節による変動の影響を受けずに比べられます。"),
    ("mom", "前月比", ["前月比"], "前の月と比べた変化。最新の勢いが分かる一方、月ごとのぶれが大きい。"),
]
GLOSSARY_TERMS = "、".join(g[1] for g in GLOSSARY)

ECON_PROMPT = """あなたは米国経済ニュースの編集者です。読者は日本に住む投資の初心者で、円と米国株(投資信託を含む)に関心があります。
読者がこのページを読み終えた時に「直前の米国市場で何が起き、なぜで、自分に何が関係するか」を自分の言葉で説明できるようにするのが、あなたの仕事です。

下の【記事】は信頼できる報道機関の英語ニュースです。各記事の先頭に[番号]、媒体名、米国東部時間の配信日と曜日が付いています。
記事は取得の都合で1〜3日前のものが中心です。最新の終値の日は {last_trade_label} です。
どの日の出来事を書いた記事かは、配信日ではなく記事の文から読み取ってください。

指定したJSONの形だけを返してください。

■ 事実と数値のルール
読者はこのページを確かめずに信じます。記事に無いことが1つでも混ざると、ページ全体が信用できなくなります。
1. 書いてよい事実・数値・理由・見通しは、記事の文中にあるものだけです。差・合計・割合などの計算や推測はしません。
2. 金額は「$500 million」を「5億ドル」、「$1.2 trillion」を「1.2兆ドル」のように、億・兆の単位を1つだけ使って書いてかまいません(プログラムで元の数字と照合します)。「1兆2000億ドル」のように単位を重ねる書き方はしません。
3. 途中で切れている数値(「51...」「7,8…」など)は使いません。
4. 記者・専門家・媒体の意見や予想は、事実として書かず「〜との見方を(媒体名)が報じた」と、誰の見方かを書きます。
5. 理由・影響・見通しが記事に書かれていなければ、その欄は null にします。空欄があってかまいません。推測で埋める方が、読者を誤らせるので害が大きいためです。
6. markets は、記事に指数などの値が書かれている時だけ作ります。その数値が書かれた英語の文を quote に一字一句そのまま写し、記事番号を source に入れます。quote に無い数値を value_text や change_value に入れません。値や変動率が記事に無ければ null にします。下落は change_value を負の数(例:-0.69)、上昇は正の数にします。

■ 書き方(初心者が1回読んで分かるように)
- 1文に1つの事実。主語から書き始め、「誰が/何が → どうなった」の順にします。
- 用語は次の表記にそろえます(ページの用語集と結びつけるため):{glossary_terms}
- この一覧に無い専門用語を使う時は、初めて出た所で「IPO(株式の新規上場)」のように、15字以内の言い換えを括弧で添えます。言い換えの中に数字は入れません。
- 企業名・人名は日本で通じる表記にします(Nvidia→エヌビディア、Fed→FRB)。初めて出た企業には、記事にあれば何の会社か(「半導体大手」など)を添えます。
- 「注目が集まる」「懸念がくすぶる」「謎を深めている」「期待される」「動向が注視される」のような、事実が増えない締めの言葉は書きません。代わりに、記事にある具体的な事実で文を終えます。
- 「本日」「昨日」「今日」は使いません。記事に書かれた曜日か日付で書きます。
- 同じ事実を2か所に書きません。key_points に書いた事実は、sections では繰り返さず、詳しい数字・理由・影響だけを足します。似た記事は1つの項目にまとめ、sources に両方の番号を入れます。
- セール情報・事故・芸能など、経済と関係のない記事は使いません。

■ 各欄の中身
headline(24字以内):その日のニュースの主題を一言で。株価指数の上げ下げは見出しにしません(値動きはページの上部に正確な数値で出すため)。
market_move:記事が書いている「米国の株式市場全体が、ある1日にどう動き、それはなぜか」を1つだけ。最新の終値の日({last_trade_label})について書いた記事があればそれを選び、無ければいちばん新しい日のものを選びます。該当する記事が無ければ null。
  day:その値動きの曜日(月|火|水|木|金)。記事の英語の文に曜日が書かれていなければ「不明」。配信日から曜日を推し量りません。
  text(120字以内):「主な指数がどう動いたか → 記事が挙げた理由」の順。
  quote:その値動きを書いた英語の文を一字一句そのまま。
  sources:記事番号。
key_points(最大3つ):読者がこれだけ読めば足りる、いちばん重要な出来事から順に。
  text(60字以内):何が起きたか。記事に数字があれば1つ入れます。
  why(60字以内、無ければ null):それがなぜ起きたか、または株価・金利・物価・円にどう関係するかを、記事に書かれている範囲で。
sections(分野別の詳しい説明):各項目は title(25字以内の見出し)/what(100字以内:何が起きたか)/why(80字以内、無ければ null:記事にある理由)/effect(80字以内、無ければ null:記事にある影響や見通し。誰の見方かを書く)/sources。1つの項目では1つの話題だけを扱います。
  stock(最大6):次の順に、記事があれば。(1)主な指数の動きと理由 (2)大きく動いた個別銘柄と理由(銘柄名と変動率) (3)業種(テック・エネルギー・金融など)の動き (4)AIなど相場全体に影響した材料
  fed(最大3):FRBの金利の判断・FOMC・FRB高官の発言と、国債利回りが動いた理由。
  jobs(最大5):物価(CPI・PCE・ガソリン代など暮らしの値段)と雇用(雇用統計・失業率・新規失業保険申請・賃金・企業の人員削減)。指標は名前と数値、市場予想や前回との比較、FRBの判断への影響が記事にあればそれも。
  earnings(最大3):大手企業の決算発表。
  該当する記事が無い分野は空の配列 [] にします。関係の薄い記事で埋めません。
upcoming(最大4):記事に書かれている、これから先の予定(経済指標の発表、FOMC、大手企業の決算など)。
  date_iso:英語の文に月と日がはっきり書かれている時だけ "YYYY-MM-DD"。"next week" "later this month" のような書き方なら、その予定は入れません(日付を計算しないため)。
  event(40字以内):何の予定か。quote:その予定が書かれた英語の文を一字一句そのまま。source:記事番号。

■ 形の見本(中身は架空です。形と書き方だけを参考にし、内容は使わないでください)
sections.stock の1項目:
{{"title": "A社、売上が予想に届かず株価下落",
  "what": "半導体大手のA社が7〜9月期の決算を発表し、売上高は120億ドルで市場予想を下回った。株価は8%下落した。",
  "why": "データセンター向けの注文が減ったと会社が説明した。",
  "effect": null,
  "sources": [4]}}

■ JSONの形
{{"headline": "24字以内",
  "market_move": {{"day": "月|火|水|木|金|不明", "text": "120字以内", "quote": "英語の文をそのまま", "sources": [記事番号]}} または null,
  "key_points": [{{"category": "株式|金融政策|雇用・物価|決算|企業|その他", "text": "60字以内", "why": "60字以内 または null", "sources": [記事番号]}}],
  "sections": {{"stock": [{{"title": "25字以内", "what": "100字以内", "why": "80字以内 または null", "effect": "80字以内 または null", "sources": [記事番号]}}],
               "fed": [], "jobs": [], "earnings": []}},
  "upcoming": [{{"date_iso": "YYYY-MM-DD", "event": "40字以内", "quote": "英語の文をそのまま", "source": 記事番号}}],
  "markets": [{{"name": "S&P 500|ナスダック総合|ダウ平均|VIX(恐怖指数)|米10年債利回り|米2年債利回り|ドル円|WTI原油|ビットコイン",
               "value_text": "記事にある値 または null", "change_value": 変動の数値 または null,
               "change_unit": "%|bp", "quote": "その数値が書かれた英語の文をそのまま", "source": 記事番号}}]}}

【記事】
{numbered_news_text}
"""

MAJOR_PROMPT = """あなたは国際・政治・テクノロジーニュースの編集者です。読者は日本に住む投資の初心者で、円と米国株に関心があります。
経済欄とは別に「経済以外の出来事のうち、株式市場・金利や物価・円や貿易・産業・規制に波及しうるもの」を最大3件選び、読者に伝えます。

下の【記事】は信頼できる報道機関の英語ニュースです。先頭に[番号]、媒体名、米国東部時間の配信日と曜日が付いています。
指定したJSONの形だけを返してください。

■ 選ぶ基準(この順に優先)
1. 米国政府の政策・規制・関税・外交(大統領の行政命令、米中関係、制裁、予算や政府閉鎖など)
2. AIの大きな動き(主要企業の新製品・大型投資・規制)
3. 半導体(エヌビディア・TSMC・輸出規制など)
4. 上のどれにも当たらないが、株式市場・金利・円・物価に影響しうる国際情勢(戦争や紛争、エネルギーの供給など)
選ぶのは、connection(株式市場|金利・物価|円・貿易|産業・企業|規制・政策)のどれかに、どうつながるかを言える記事だけです。

■ 選ばないもの
宗教、王室・皇室、スポーツ、芸能、事件・事故・裁判(企業や政策に関わるものを除く)、政治家個人の言動や議会の手続きのうち政策の中身が動かないもの。
迷ったら選びません。関係の薄い記事で3件を埋めるより、関係の深い1件の方が読者の役に立つためです。該当が無ければ items を [] にします。

■ 事実のルール
- 書いてよい事実・数値・理由・見通しは、記事の文中にあるものだけです。計算・推測はしません。途中で切れた数値は使いません。
- 金額は億・兆の単位を1つだけ使って書いてかまいません(「$1.2 trillion」→「1.2兆ドル」)。
- 意見や予想は「〜との見方を(媒体名)が報じた」と、誰の見方かを書きます。

■ 各欄
category:政治・政策|国際|AI・テック|半導体|経済
connection:上の5つのどれか1つ。
title(28字以内):「誰が/何が → どうした」を自然な日本語で。助詞を削った電報のような文にしません(悪い例「X社IPO、市場の次期を左右」/良い例「X社の上場、AI株の先行きを測る材料に」)。
lead(60字以内):何が起きたかを1文で。
bullets(2〜3個、各60字以内):背景・数字・関係者の発言など、lead に無い事実を1行に1つ。出身地のような、本筋と関係の無い豆知識は入れません。
why_it_matters(70字以内、無ければ null):connection に書いたつながりを、記事に書かれている範囲で。記事に無ければ null にします(推測で書かない)。
sources:記事番号。
用語・人名・企業名は日本で通じる表記にし、「注目が集まる」「期待される」のような中身の無い締めの言葉、「本日」「昨日」は使いません。

■ JSONの形
{{"items": [{{"category": "政治・政策|国際|AI・テック|半導体|経済",
             "connection": "株式市場|金利・物価|円・貿易|産業・企業|規制・政策",
             "title": "28字以内", "lead": "60字以内",
             "bullets": [{{"text": "60字以内", "sources": [記事番号]}}],
             "why_it_matters": "70字以内 または null",
             "sources": [記事番号]}}]}}

【記事】
{numbered_news_text}
"""


def summarize_with_gemini(econ_articles, last_trade_label="(取得できませんでした)"):
    """経済ニュースの要約(Gemini 1回)。返り値はGeminiの生テキスト(JSONのはず)"""
    prompt = ECON_PROMPT.format(numbered_news_text=_numbered(econ_articles),
                                last_trade_label=last_trade_label, glossary_terms=GLOSSARY_TERMS)
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
    return _norm(f"{a.get('title', '')} {_body_of(a)}")


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
# 照合する「数字+単位」(2026-11-14 仕様7-1で%以外にも広げた)
_UNIT_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(%|ベーシスポイント|ポイント|bp|円|ドル)")
_DOLLAR_NUM_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_JP_MONEY_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(兆|億|万)\s*ドル")
_MULTI_UNIT_RE = re.compile(r"\d[\d,.]*\s*[兆億万]\s*\d[\d,.]*\s*[億万]\s*(?:ドル|円)")
_EN_MONEY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(trillion|billion|million|bn|tn)\b")
_EN_MONEY_SHORT_RE = re.compile(r"\$\s?(\d+(?:\.\d+)?)(m|b)\b")
_EN_BIG_DOLLAR_RE = re.compile(r"\$\s?(\d{5,}(?:\.\d+)?)")
_JP_UNIT = {"兆": 1e12, "億": 1e8, "万": 1e4}
_EN_UNIT = {"trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "m": 1e6}


def _en_amounts(src_nocomma):
    """出典本文(カンマ除去・小文字)にある英語の金額をドルの数値にして返す"""
    out = [float(n) * _EN_UNIT[u] for n, u in _EN_MONEY_RE.findall(src_nocomma)]
    out += [float(n) * _EN_UNIT[u] for n, u in _EN_MONEY_SHORT_RE.findall(src_nocomma)]
    out += [float(n) for n in _EN_BIG_DOLLAR_RE.findall(src_nocomma)]
    return out


def _nums_problem(s, srcs, articles):
    """文字列sの数字(単位つき)が出典記事の本文にあるかを調べる。問題があれば理由の文字列、無ければNone"""
    if not s:
        return None
    nt = unicodedata.normalize("NFKC", s)
    if _CUT_NUM_RE.search(nt):
        return "途切れた数値"
    if _MULTI_UNIT_RE.search(nt):
        return "単位を重ねた金額"
    src = " ".join(_article_text(articles[n - 1]) for n in srcs).replace(",", "")
    for num, unit in _UNIT_NUM_RE.findall(nt):
        if _num_pos(num.replace(",", ""), src) < 0:
            return f"元記事に無い数値({num}{unit})"
    for num in _DOLLAR_NUM_RE.findall(nt):
        if _num_pos(num.replace(",", ""), src) < 0:
            return f"元記事に無い数値(${num})"
    amounts = None
    for num, u in _JP_MONEY_RE.findall(nt):
        val = float(num.replace(",", "")) * _JP_UNIT[u]
        if amounts is None:
            amounts = _en_amounts(src)
        if not any(abs(val - a) <= 0.005 * a for a in amounts if a):
            return f"元記事に無い金額({num}{u}ドル)"
    return None


# 事実が増えない締めの言葉(仕様7-5)。プロンプトで禁じても言い換えで出るため、最後はプログラムで落とす
FILLER_WORDS = ["注目が集まる", "注目される", "注視", "くすぶ", "謎を深め", "期待される", "見方が強まる"]
_FILLER_COUNT = {"n": 0}


def _strip_filler(s):
    """「。」で文に分け、締めの言葉を含む文を取り除く(取り除いた数は_FILLER_COUNTに足す)"""
    if not s:
        return ""
    sents = re.findall(r"[^。]*。|[^。]+$", s)
    kept = [x for x in sents if not any(w in x for w in FILLER_WORDS)]
    _FILLER_COUNT["n"] += len(sents) - len(kept)
    return "".join(kept).strip()


_BP_RE = re.compile(r"(?<![A-Za-z])bp(?![A-Za-z])")


def _unbp(s):
    """画面に「bp」を出さない(初心者が分からない単位のため。照合のあとで言い換える)"""
    return _BP_RE.sub("ベーシスポイント", s) if s else s


def _clean(v):
    if not isinstance(v, str):
        return ""
    v = v.replace("**", "").strip()
    return "" if _is_empty(v) else v


def _check_line(item, articles, opt=("why", "effect")):
    """1項目を検証する。ダメなら None(その項目だけ捨てる)。
    title と本文(what/body/text)の数字が出典に無ければ項目ごと捨て、why・effect だけが合わなければその欄だけ空にする"""
    if not isinstance(item, dict):
        return None
    title = _strip_filler(_clean(item.get("title")))
    text = _strip_filler(_clean(item.get("what")) or _clean(item.get("body")) or _clean(item.get("text")))
    if not text:
        return None
    srcs = _valid_sources(item.get("sources"), articles)
    if not srcs:
        print(f"    [drop] 出典なし: {text[:30]}")
        return None
    for s in (title, text):
        reason = _nums_problem(s, srcs, articles)
        if reason:
            print(f"    [drop] {reason}: {text[:30]}")
            return None
    out = {"text": _unbp(text), "sources": srcs}
    if title:
        out["title"] = _unbp(title)
    if "category" in item:
        out["category"] = item.get("category")
    for k in opt:
        v = _strip_filler(_clean(item.get(k)))
        if v:
            reason = _nums_problem(v, srcs, articles)
            if reason:
                print(f"    [drop {k}] {reason}: {v[:30]}")
                v = ""
        out[k] = _unbp(v) or None
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
    """記事から拾った数値カード1枚を検証する。合格ならカード用dict、不合格ならNone(理由をログ)"""
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
    return _ai_card({
        "name": name,
        "value_text": value_text,
        "change": change,
        "unit": unit,
        "direction": direction,
        "source": src,
        "source_name": articles[src - 1].get("source", ""),
    })


def _ai_card(c):
    """記事から拾ったカードに、公式の数値カードと同じ表示用の欄を足す(bpは「ポイント」に直す)"""
    ch, d = c["change"], c["direction"]
    if ch is None:
        txt, read = "変動の記載なし", "変動の記載なし"
    else:
        if c["unit"] == "bp":
            mag = f"{abs(ch) / 100:.2f}ポイント"
        else:
            mag = f"{_fmt_num(ch)}%"
        if d == "flat":
            txt, read = "前日と同じ", "前日と同じ"
        elif d in (1, -1):
            txt = f"{'+' if d == 1 else '−'}{mag}"
            read = f"{mag}{'上昇' if d == 1 else '下落'}"
        else:
            txt, read = mag, f"変動{mag}、向きの記載なし"
    c.update({"kind": "ai", "chg_text": txt, "chg_read": read, "range_text": "",
              "date_label": f"報道時点の値({c['source_name']})" if c.get("source_name") else "報道時点の値",
              "stale": True, "official": False})
    return c


# ========================================
# 1c. 市場の数値(Yahoo Financeを主、FREDを予備)(2026-11-14)
# ========================================
# FRED(fredgraph.csv)は終値の公表が1〜2日遅れ、ドル円は約1週間遅れる。前日の終値を出すためYahoo Financeの
# chart API(キー不要)を主にし、取れない系列はFREDの値を日付つきで出す(古い値を最新のように見せない)
MARKET_SERIES = [
    # (表示名, Yahooの記号, FREDの系列, 種類)
    ("S&P 500", "^GSPC", "SP500", "index"),
    ("ナスダック総合", "^IXIC", "NASDAQCOM", "index"),
    ("ダウ平均", "^DJI", "DJIA", "index"),
    ("ドル円", "JPY=X", "DEXJPUS", "fx"),
    ("米10年債利回り", "^TNX", "DGS10", "yield"),          # ^TNXの値は%(例 5.154)
    ("米2年債利回り", None, "DGS2", "yield"),              # Yahooに2年債利回りの指数が無い(2YY=Fは先物)ためFREDのみ
    ("VIX(恐怖指数)", "^VIX", "VIXCLS", "level"),
    ("WTI原油", "CL=F", "DCOILWTICO", "usd"),
    ("ビットコイン", "BTC-USD", "CBBTCUSD", "usd"),
]
MARKET_GROUPS = [("米国株", ["S&P 500", "ナスダック総合", "ダウ平均"]),
                 ("円と金利", ["ドル円", "米10年債利回り", "米2年債利回り"]),
                 ("その他の市場", ["VIX(恐怖指数)", "WTI原油", "ビットコイン"])]
# 上昇=緑・下落=赤の色づけは株とビットコインだけ(円安・金利上昇・原油高は読者にとって良いとは限らないため)
NEUTRAL_CARDS = {"ドル円", "米10年債利回り", "米2年債利回り", "VIX(恐怖指数)", "WTI原油"}
# YahooとFREDの重なる日の値を比べ、これより大きくずれたらログに[WARN]を出す(利回りは差、他は%)
CROSS_TOL = {"index": 0.2, "fx": 1.0, "yield": 0.06, "level": 3.0, "usd": 3.0}
FALLBACK_MAX_AGE_DAYS = 14   # 予備のFREDの値が対象日よりこれ以上古ければカードに出さない
INDEX_TABLE = [("S&P 500", "SP500"), ("ダウ平均", "DJIA"), ("ナスダック総合", "NASDAQCOM")]


def _fred_rows(series_id, days=21):
    """FREDのCSVから、値のある行 [(日付, 値), ...] を古い順に返す"""
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    req = urllib.request.Request(url, headers={"User-Agent": "EconoBot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as res:
        text = res.read().decode("utf-8", "replace")
    rows = []
    for line in text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) != 2:
            continue
        try:
            rows.append((parts[0], float(parts[1])))
        except ValueError:
            continue  # 祝日などは「.」や空欄で値が無い
    return rows


_FRED_CACHE = {}


def _fred_cached(series_id, days):
    key = (series_id, days)
    if key not in _FRED_CACHE:
        _FRED_CACHE[key] = _fred_rows(series_id, days)
    return _FRED_CACHE[key]


def _parse_yahoo(res0, now=None):
    """Yahoo chart APIの結果1件から、日足の終値 [(日付, 値), ...] を古い順に返す。
    - 日付は取引所の時差(gmtoffset)で直した現地の日付
    - 指数・株で取引時間中(引け後15分まで)の最後の足は終値ではないので捨てる
    - 為替は日足の最後の値の更新が遅れることがあるため、同じ日のregularMarketPriceで上書きする"""
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    meta = res0.get("meta") or {}
    off = meta.get("gmtoffset") or 0
    ts = res0.get("timestamp") or []
    quote = ((res0.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []

    def day(t):
        return datetime.fromtimestamp(t + off, timezone.utc).date().isoformat()
    byday = {}
    for t, c in zip(ts, closes):
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            byday[day(t)] = float(c)
    rows = sorted(byday.items())
    if not rows:
        return []
    itype = meta.get("instrumentType", "")
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    # 先物(CL=F)の「regular」は1日まるごと(米東部0時〜24時)のため、この判定は指数・株にだけ使う
    if itype not in ("CURRENCY", "CRYPTOCURRENCY", "FUTURE") and reg.get("start") and reg.get("end"):
        if reg["start"] <= now_ts < reg["end"] + 900 and day(reg["start"]) == rows[-1][0]:
            print(f"    [Yahoo] {meta.get('symbol', '')} {rows[-1][0]}は取引中のため終値に使わない")
            rows = rows[:-1]
    rmt, rmp = meta.get("regularMarketTime"), meta.get("regularMarketPrice")
    if itype == "CURRENCY" and rows and rmt and isinstance(rmp, (int, float)) and day(rmt) == rows[-1][0]:
        rows[-1] = (rows[-1][0], float(rmp))
        # 前の日の値も日足の終値(英国時間の朝の値のことがある)ではなく、Yahooの前日終値を使う(2026-11-14 verifier指摘)
        pc = meta.get("previousClose")
        if len(rows) >= 2 and isinstance(pc, (int, float)) and not isinstance(pc, bool):
            rows[-2] = (rows[-2][0], float(pc))
    return rows


def _yahoo_chart(symbol, rng, interval):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?range={rng}&interval={interval}")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.loads(res.read().decode())
    return data["chart"]["result"][0]


def _yahoo_rows(symbol, rng="2y", now=None):
    return _parse_yahoo(_yahoo_chart(symbol, rng, "1d"), now)


FX_CLOSE_HOUR_ET = 17   # 為替の「その日の値」= 米東部17時(ニューヨークの取引の終わり)の値


def _ny_close_rows(res0):
    """1時間足から、平日の各日について米東部17時直前の足(16時台)の終値を [(日付, 値)] で返す。
    JPY=Xの日足は英国時間で区切られ、終値が米国の引けと数時間ずれる(11/12は約0.1円)ため、前日比はこちらで計算する"""
    ts = res0.get("timestamp") or []
    closes = (((res0.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    out = {}
    for t, c in zip(ts, closes):
        if not isinstance(c, (int, float)) or isinstance(c, bool):
            continue
        et = _to_et(datetime.fromtimestamp(t, timezone.utc))
        if et.weekday() < 5 and 12 <= et.hour < FX_CLOSE_HOUR_ET:
            out[et.date().isoformat()] = float(c)   # 時刻の順に上書きされ、17時直前の足が残る
    return sorted(out.items())


def _yahoo_fx_rows(symbol, now=None):
    """為替:古い日は日足、直近約1か月は米東部17時の値。1時間足が取れない日は日足+前日終値(previousClose)"""
    rows = _yahoo_rows(symbol, now=now)
    try:
        ny = _ny_close_rows(_yahoo_chart(symbol, "1mo", "60m"))
    except Exception as e:
        print(f"    [WARN] [Yahoo {symbol} 1時間足] 取得失敗 {type(e).__name__} → 日足と前日終値で計算")
        return rows
    if len(ny) < 2:
        return rows
    rows = [r for r in rows if r[0] < ny[0][0]] + ny
    print(f"    [Yahoo {symbol}] 直近{len(ny)}日は米東部17時の値({ny[-2][0]} {ny[-2][1]:.3f} → {ny[-1][0]} {ny[-1][1]:.3f})")
    return rows


def _cross_check(name, kind, yahoo, fred):
    """重なる日(直近10日)の値をYahooとFREDで比べ、ログに出す。ずれが大きければ[WARN]"""
    fd = dict(fred)
    pairs = [(d, v, fd[d]) for d, v in yahoo[-10:] if d in fd]
    if not pairs:
        print(f"    [照合 {name}] FREDと重なる日なし")
        return None
    if kind == "yield":
        devs = [(abs(y - f), d, y, f) for d, y, f in pairs]
        unit = "ポイント"
    else:
        devs = [(abs(y - f) / f * 100 if f else 0.0, d, y, f) for d, y, f in pairs]
        unit = "%"
    worst = max(devs)
    tag = "[WARN] " if worst[0] > CROSS_TOL[kind] else ""
    print(f"    {tag}[照合 {name}] Yahoo↔FRED 重なる{len(pairs)}日 最大のずれ {worst[0]:.3f}{unit}"
          f"({worst[1]} Yahoo {worst[2]:.4g} / FRED {worst[3]:.4g})")
    return worst[0]


def fetch_market_data(now=None):
    """各系列の日次の値(約2年分)と、対象日(=S&P 500の最新終値の日)を返す。
    Yahooが429等で取れない系列はFREDで代用する。1系列ずつ失敗しても他は続ける"""
    series = {}
    for name, sym, fred_id, kind in MARKET_SERIES:
        rows, src = [], None
        if sym:
            try:
                rows = _yahoo_fx_rows(sym, now=now) if kind == "fx" else _yahoo_rows(sym, now=now)
                src = "Yahoo Finance"
            except Exception as e:
                code = getattr(e, "code", "")
                print(f"    [Yahoo {sym}] 取得失敗 {type(e).__name__}{code} → FREDで代用")
                rows = []
        fred = []
        try:
            fred = _fred_cached(fred_id, 760)
        except Exception as e:
            print(f"    [FRED {fred_id}] 取得失敗: {type(e).__name__}")
        if len(rows) >= 2 and fred:
            _cross_check(name, kind, rows, fred)
        if len(rows) < 2:
            rows, src = fred, "FRED"
        if len(rows) >= 2:
            series[name] = {"rows": rows, "src": src, "kind": kind, "fred_id": fred_id}
            print(f"    [{src}] {name}: 最新 {rows[-1][0]} {rows[-1][1]:.4g}")
    trade_date = series["S&P 500"]["rows"][-1][0] if "S&P 500" in series else None
    print(f"  対象日(S&P 500の最新終値の日): {trade_date}")
    return {"series": series, "trade_date": trade_date}


def _q2(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q1(x):
    return Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _sg(d, digits=2):
    """Decimal/数値 → '+1.23' / '−1.23'(マイナスはU+2212)"""
    d = Decimal(str(d))
    s = f"{abs(d):.{digits}f}"
    return ("+" if d > 0 else "−" if d < 0 else "") + s


def _range_label(lo, hi, v):
    if hi <= lo:
        return "中ほど"
    p = (v - lo) / (hi - lo)
    if p >= 0.999:
        return "この1年で最も高い"
    if p <= 0.001:
        return "この1年で最も低い"
    if p > 0.8:
        return "高い方"
    if p < 0.2:
        return "低い方"
    return "中ほど"


def _fmt_value(kind, v, name=""):
    if kind == "yield":
        return f"{v:.2f}%"
    if kind == "fx":
        return f"{v:.2f}円"
    if kind == "usd":
        return f"${v:,.2f}" if v < 1000 else f"${v:,.0f}"
    if kind == "level":
        return f"{v:.2f}"
    return f"{v:,.2f}"


def _fmt_range(kind, lo, hi):
    if kind == "yield":
        return f"{lo:.2f}〜{hi:.2f}%"
    if kind == "fx":
        return f"{lo:.2f}〜{hi:.2f}円"
    return f"{_fmt_value(kind, lo)}〜{_fmt_value(kind, hi)}"


def _prev_word(d0, d1):
    """比べる値の日が最新日の1つ前の平日なら「前日」、祝日などで離れていれば「11/10」(2年債の11/11は祝日で値が無い)"""
    a, b = _to_iso_date(d0), _to_iso_date(d1)
    p = b - timedelta(days=1)
    while p.weekday() >= 5:
        p -= timedelta(days=1)
    return "前日" if a == p else f"{a.month}/{a.day}"


def _official_card(name, kind, rows, trade_date=None, src="FRED"):
    """日次の値から数値カードを作る。trade_date(対象日)以前の最新2日を使い、1年の範囲も付ける"""
    if trade_date:
        rows = [r for r in rows if r[0] <= str(trade_date)]
    if len(rows) < 2:
        return None
    (d0, v0), (d1, v1) = rows[-2], rows[-1]
    up_word, down_word = "上昇", "下落"
    if kind == "yield":
        a, b = _q2(v1), _q2(v0)
        diff = a - b
        mag = f"{abs(diff):.2f}ポイント"
        pw = _prev_word(d0, d1)
        chg = f"{_sg(diff)}ポイント({pw} {b:.2f}%)"
        read_tail = f"、{pw}は{b:.2f}%"
        pct_raw = None
    elif kind == "fx":
        diff = _q2(v1) - _q2(v0)
        mag = f"{abs(diff):.2f}円"
        chg = f"{_sg(diff)}円 {'円安' if diff > 0 else '円高'}"
        up_word, down_word = "円安", "円高"
        read_tail = ""
        pct_raw = (v1 - v0) / v0 * 100 if v0 else None
    elif kind == "level":
        diff = _q2(v1) - _q2(v0)
        mag = f"{abs(diff):.2f}"
        pw = _prev_word(d0, d1)
        chg = f"{_sg(diff)}({pw} {_q2(v0):.2f})"
        read_tail = f"、{pw}は{_q2(v0):.2f}"
        pct_raw = None
    else:
        pct_raw = (v1 - v0) / v0 * 100 if v0 else 0.0
        diff = _q2(pct_raw)
        mag = f"{abs(diff):.2f}%"
        chg = f"{_sg(diff)}%"
        read_tail = ""
    if diff == 0:
        direction, chg, read = "flat", "前日と同じ", "前日と同じ"
    else:
        direction = 1 if diff > 0 else -1
        read = f"前の取引日より{mag}{up_word if diff > 0 else down_word}{read_tail}"
    last = datetime.strptime(d1, "%Y-%m-%d").date()
    try:
        cutoff = last.replace(year=last.year - 1).isoformat()
    except ValueError:  # 2/29
        cutoff = (last - timedelta(days=365)).isoformat()
    year = [v for d, v in rows if d > cutoff]
    range_text = ""
    covers_year = rows[0][0] <= (last - timedelta(days=355)).isoformat()
    if covers_year and len(year) >= 2:
        lo, hi = min(year), max(year)
        range_text = f"1年の範囲 {_fmt_range(kind, lo, hi)} ・ {_range_label(lo, hi, v1)}"
    td = str(trade_date) if trade_date else d1
    return {"name": name, "kind": kind, "value_text": _fmt_value(kind, v1, name), "value": v1,
            "prev_value": v0, "prev_date": d0, "date": d1, "change": float(diff), "pct_raw": pct_raw,
            "pct_text": chg if kind in ("index", "usd") else "", "chg_text": chg, "chg_read": read,
            "direction": direction, "range_text": range_text, "stale": d1 != td,
            "date_label": f"{int(d1[5:7])}/{int(d1[8:10])}の値" if d1 != td else "",
            "source": None, "source_name": src, "official": True}


def build_market_cards(market):
    """取得した系列から数値カードを作る(並びはMARKET_NAMESの順)"""
    td = market.get("trade_date")
    cards = []
    for name, sym, fred_id, kind in MARKET_SERIES:
        s = market.get("series", {}).get(name)
        if not s:
            continue
        c = _official_card(name, kind, s["rows"], td, s["src"])
        if not c:
            continue
        if td and (_to_iso_date(td) - _to_iso_date(c["date"])).days > FALLBACK_MAX_AGE_DAYS:
            print(f"    [{name}] 最新が{c['date']}で古すぎるため出さない")
            continue
        cards.append(c)
    by = {c["name"]: c for c in cards}
    return [by[n] for n in MARKET_NAMES if n in by]


def merge_markets(official, ai_cards):
    """公式の数値を優先し、取れなかった項目だけ記事由来のカードで補う。並びはMARKET_NAMESの順"""
    by = {c["name"]: c for c in ai_cards}
    by.update({c["name"]: c for c in official})
    return [by[n] for n in MARKET_NAMES if n in by]


SIZE_LABELS = [(50, "小さな動き"), (20, "ふつうの動き"), (5, "大きめの動き"), (0, "この1年でも特に大きな動き")]


def size_label(n):
    """上位N%(大きい方から)→ ラベル"""
    for th, lab in SIZE_LABELS:
        if n > th:
            return lab
    return SIZE_LABELS[-1][1]


def move_size(rows):
    """S&P 500の終値の列から、最新日の1日の変化の大きさを「上位N%」で返す。250取引日に満たなければNone"""
    chg = [abs((rows[i][1] - rows[i - 1][1]) / rows[i - 1][1] * 100) for i in range(1, len(rows)) if rows[i - 1][1]]
    if len(chg) < 251:
        return None
    latest, prior = chg[-1], chg[-251:-1]
    cnt = sum(1 for c in prior if c >= latest)
    n = max(1, int((Decimal(cnt) * 100 / Decimal(250)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    return {"n": n, "label": size_label(n)}


def _value_on_or_before(rows, day):
    """day(YYYY-MM-DD)以前で最も新しい値"""
    cand = [v for d, v in rows if d <= day]
    return cand[-1] if cand else None


TODAY_SHORT = {"S&P 500": "S&P 500", "ナスダック総合": "ナスダック", "ダウ平均": "ダウ"}


def today_summary(market, cards):
    """「昨日の米国市場」の箱の数字(すべてプログラムで計算。ページとSlackで同じ値を使う)"""
    td = market.get("trade_date") if market else None
    by = {c["name"]: c for c in cards if c.get("official")}
    sp = by.get("S&P 500")
    if not td or not sp or sp["stale"]:
        return None
    idx = [by[n] for n in ("S&P 500", "ナスダック総合", "ダウ平均") if n in by and not by[n]["stale"]]
    raws = [c["pct_raw"] for c in idx]
    if all(r > 0 for r in raws):
        word = "上昇"
    elif all(r < 0 for r in raws):
        word = "下落"
    elif abs(sp["pct_raw"]) < 0.10:
        word = "ほぼ横ばい"
    else:
        word = "まちまち"
    parts = "、".join(f"{TODAY_SHORT[c['name']]} {c['chg_text']}" for c in idx)
    out = {"trade_date": td, "trade_label": _jp_date(_to_iso_date(td)), "word": word,
           "stocks": f"米国株は{word}。{parts}。", "sp_text": sp["chg_text"],
           "nasdaq_text": next((c["chg_text"] for c in idx if c["name"] == "ナスダック総合"), ""),  # 対象日と違う日の値は使わない
           "size": None, "yen": None, "jpy_sp": None}
    sp_rows = [r for r in market["series"]["S&P 500"]["rows"] if r[0] <= td]
    out["size"] = move_size(sp_rows)
    fx = by.get("ドル円")
    if fx:
        diff = _q2(fx["value"]) - _q2(fx["prev_value"])
        if abs(diff) < Decimal("0.05"):
            rel, short, word_fx = "前の日からほぼ変わらず", "前の日からほぼ変わらず", "前日並み"
        elif diff > 0:
            rel = f"前の日より{abs(diff):.2f}円の円安(ドルが高くなった)"
            short, word_fx = f"前の日より{abs(diff):.2f}円の円安", "円安"
        else:
            rel = f"前の日より{abs(diff):.2f}円の円高(ドルが安くなった)"
            short, word_fx = f"前の日より{abs(diff):.2f}円の円高", "円高"
        when = f"({fx['date_label']})" if fx["stale"] else ""
        out["yen"] = {"value": f"{fx['value']:.2f}", "when": when, "line": f"1ドル={fx['value']:.2f}円{when}。{rel}。",
                      "short": f"1ドル={fx['value']:.2f}円{when}({short})", "word": word_fx}
        fx_rows = market["series"]["ドル円"]["rows"]
        if not fx["stale"]:
            now_v = _value_on_or_before(fx_rows, td)
            prev_v = _value_on_or_before(fx_rows, sp["prev_date"])
            if now_v and prev_v:
                sp_p = _q2(sp["pct_raw"])
                fx_p = _q2((now_v - prev_v) / prev_v * 100)
                comb = _q2(((1 + sp_p / 100) * (1 + fx_p / 100) - 1) * 100)
                out["jpy_sp"] = {"value": comb, "text": f"{_sg(comb)}%", "sp": f"{_sg(sp_p)}%", "fx": f"{_sg(fx_p)}%"}
    return out


def index_trend_row(name, rows):
    """1年分の終値から、前日比・1週間・1か月・年初来・1年の高値からの距離を計算する"""
    if len(rows) < 2:
        return None
    last_d, last_v = rows[-1]
    last = datetime.strptime(last_d, "%Y-%m-%d").date()
    def back(days):
        v = _value_on_or_before(rows, (last - timedelta(days=days)).isoformat())
        return _pct(last_v, v) if v is not None else None
    ytd_base = _value_on_or_before(rows, f"{last.year - 1}-12-31")
    try:
        cutoff = last.replace(year=last.year - 1).isoformat()
    except ValueError:  # 2/29
        cutoff = (last - timedelta(days=365)).isoformat()
    high = max(v for d, v in rows if d > cutoff)
    return {"name": name, "date": f"{last.month}/{last.day}", "date_iso": last_d, "close": last_v,
            "d1": _pct(last_v, rows[-2][1]), "w1": back(7), "m1": back(30),
            "ytd": _pct(last_v, ytd_base) if ytd_base else None,
            "from_high": _pct(last_v, high)}


def _pct(a, b):
    return round((a - b) / b * 100, 2) if b else None


def build_index_trends(market):
    td = market.get("trade_date")
    out = []
    for name, _ in INDEX_TABLE:
        s = market.get("series", {}).get(name)
        if not s:
            continue
        r = index_trend_row(name, [x for x in s["rows"] if not td or x[0] <= td])
        if r:
            out.append(r)
    print(f"  株式の推移表: {len(out)}行")
    return out


# ---- 物価・雇用の指標(FREDの米政府統計)----
MACRO_SERIES = [
    # (表示名, FRED系列, 種類)
    ("失業率", "UNRATE", "rate"),
    ("雇用者数の増減(農業以外)", "PAYEMS", "mom_k"),
    ("平均時給(前年比)", "CES0500000003", "wage"),
    ("消費者物価(CPI)", "CPIAUCSL", "price"),
    ("コアCPI(食品・エネルギー除く)", "CPILFESL", "price"),
    ("コアPCE物価(FRBが重視)", "PCEPILFE", "price"),
    ("新規失業保険申請", "ICSA", "weekly"),
    ("求人件数", "JTSJOL", "level_k"),
]


def _mkey(d, months):
    """'2026-10-01' をmonthsか月ずらした月の1日"""
    y, m = int(d[:4]), int(d[5:7]) + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-01"


def _yoy(rows, i):
    """rows[i]の前年同月比(%)。1年前の同じ月の行が無ければNone"""
    d, v = rows[i]
    target = f"{int(d[:4]) - 1}{d[4:]}"
    base = dict(rows).get(target)
    return float(_q1((v - base) / base * 100)) if base else None


def _mom(rows, i):
    """rows[i]の前月比(%)。前の月の行が無ければNone(欠測の月をまたいで計算しない)"""
    d, v = rows[i]
    base = dict(rows).get(_mkey(d, -1))
    return float(_q1((v - base) / base * 100)) if base else None


def _p1(x):
    return "―" if x is None else f"{_sg(x, 1)}%"


def _period(d, weekly=False):
    return f"{int(d[5:7])}/{int(d[8:10])}までの週" if weekly else f"{int(d[5:7])}月分"


def indicator_block(name, sid, kind, rows, cpi_rows=None):
    """指標1つ分の表示内容(値・前回・基準・読み方)。読み方の言葉は「高い/低い」「多い/少ない」「上回る/下回る」だけ"""
    if len(rows) < 3:
        return None
    d, v = rows[-1]
    pd_, pv = rows[-2]
    weekly = kind == "weekly"
    out = {"name": name, "sid": sid, "period": _period(d, weekly), "desc": IND_DESC.get(sid, ""),
           "value": "", "prev": "", "base": "", "read": ""}
    prev_head = f"前回({_period(pd_, weekly)})"
    year_ago = f"{int(d[:4]) - 1}{d[4:]}"
    rd = dict(rows)
    if kind == "rate":
        out["value"] = f"{v:.1f}%"
        out["prev"] = f"{prev_head} {pv:.1f}%"
        out["base"] = "基準:1年前の同じ月の値"
        ya = rd.get(year_ago)
        if ya is None:
            out["read"] = "1年前の同じ月の統計が欠けているため、比べられません。"
        else:
            diff = _q1(v) - _q1(ya)
            out["read"] = (f"1年前({ya:.1f}%)と同じ" if diff == 0 else
                           f"1年前({ya:.1f}%)より{abs(diff):.1f}ポイント{'高い' if diff > 0 else '低い'}")
    elif kind == "mom_k":
        changes = [(rows[i][0], (rows[i][1] - rows[i - 1][1]) / 10) for i in range(1, len(rows))
                   if _mkey(rows[i][0], -1) == rows[i - 1][0]]
        if not changes or changes[-1][0] != d:
            return None
        c = changes[-1][1]
        out["value"] = f"{_sg(_q1(c), 1)}万人"
        if len(changes) >= 2:
            out["prev"] = f"前回({_period(changes[-2][0])}) {_sg(_q1(changes[-2][1]), 1)}万人"
        out["base"] = "基準:直前12か月の増減の平均"
        if len(changes) >= 13:
            avg = sum(x for _, x in changes[-13:-1]) / 12
            out["base"] += f" {_sg(_q1(avg), 1)}万人"
            a1, b1 = _q1(c), _q1(avg)
            head = f"ふだん(直前12か月の平均 {_sg(b1, 1)}万人)"
            out["read"] = head + ("とほぼ同じ" if a1 == b1 else f"より{'多い' if a1 > b1 else '少ない'}")
        else:
            out["read"] = "比べるための過去の統計が足りません。"
    elif kind == "wage":
        a, b = _yoy(rows, len(rows) - 1), _yoy(rows, len(rows) - 2)
        out["value"] = f"前年比 {_p1(a)}"
        out["prev"] = f"{prev_head} 前年比 {_p1(b)}"
        c = None
        if cpi_rows:
            idx = [i for i, (cd, _) in enumerate(cpi_rows) if cd == d]
            c = _yoy(cpi_rows, idx[0]) if idx else None
        if a is not None and c is not None:   # 同じ月のCPI前年比が無ければ基準と読み方は出さない
            out["base"] = f"基準:同じ月の消費者物価(CPI)の伸び {_p1(c)}"
            out["read"] = f"物価の伸び({_p1(c)})" + ("と同じ" if a == c else ("を上回る" if a > c else "を下回る"))
    elif kind == "price":
        n = len(rows)
        a, b = _yoy(rows, n - 1), _yoy(rows, n - 2)
        m, pm = _mom(rows, n - 1), _mom(rows, n - 2)
        out["value"] = f"前年比 {_p1(a)} ・ 前月比 {_p1(m)}"
        out["yoy"], out["mom"] = a, m
        out["prev"] = f"{prev_head} 前年比 {_p1(b)} ・ 前月比 {_p1(pm)}"
        out["base"] = "基準:FRBの物価目標 年2%" + ("" if sid == "PCEPILFE" else "(目安)")
        if a is not None:
            diff = Decimal(str(a)) - Decimal("2.0")
            out["read"] = ("目標の2%と同じ" if diff == 0 else
                           f"目標の2%を{abs(diff):.1f}ポイント{'上回る' if diff > 0 else '下回る'}")
        else:
            s = "1年前の統計が欠けているため前年比は出せません。"
            if m is not None and pm is not None:
                s += f"前月比は{_p1(m)}で、前の月({_p1(pm)})" + (
                    "と同じ" if m == pm else f"より{'大きい' if m > pm else '小さい'}")
            elif m is not None:
                s += f"前月比は{_p1(m)}です。"
            out["read"] = s
    elif kind == "weekly":
        out["value"] = f"{v / 10000:.1f}万件"
        out["prev"] = f"{prev_head} {pv / 10000:.1f}万件"
        out["base"] = "基準:直前52週の平均"
        if len(rows) >= 53:
            avg = sum(x for _, x in rows[-53:-1]) / 52 / 10000
            out["base"] += f" {avg:.1f}万件"
            a1, b1 = _q1(v / 10000), _q1(avg)
            out["read"] = (f"ふだん(直前52週の平均 {avg:.1f}万件)とほぼ同じ" if a1 == b1 else
                           f"ふだん(直前52週の平均 {avg:.1f}万件)より{'多い' if a1 > b1 else '少ない'}")
        else:
            out["read"] = "比べるための過去の統計が足りません。"
    else:  # level_k:千件 → 万件
        out["value"] = f"{v / 10:,.0f}万件"
        out["prev"] = f"{prev_head} {pv / 10:,.0f}万件"
        out["base"] = "基準:1年前の同じ月の値"
        ya = rd.get(year_ago)
        if ya is None:
            out["read"] = "1年前の同じ月の統計が欠けているため、比べられません。"
        else:
            a1, b1 = round(v / 10), round(ya / 10)
            out["read"] = (f"1年前({ya / 10:,.0f}万件)と同じ" if a1 == b1 else
                           f"1年前({ya / 10:,.0f}万件)より{'多い' if a1 > b1 else '少ない'}")
    for k in ("value", "prev", "base", "read"):
        out[k] = out[k].replace("-", "−")
    return out


def fetch_macro():
    rows_by = {}
    for name, sid, kind in MACRO_SERIES:
        try:
            rows_by[sid] = _fred_rows(sid, days=520)
        except Exception as e:
            print(f"    [FRED {sid} 指標] 取得失敗: {type(e).__name__}")
    out = []
    for name, sid, kind in MACRO_SERIES:
        if sid not in rows_by:
            continue
        r = indicator_block(name, sid, kind, rows_by[sid], rows_by.get("CPIAUCSL"))
        if r:
            out.append(r)
    print(f"  物価・雇用の指標: {len(out)}個")
    return out


def policy_rate_info(lo_rows, hi_rows):
    """FREDの政策金利(下限・上限)の日次から、今の範囲と最後に変わった日・幅を返す"""
    if not lo_rows or not hi_rows:
        return None
    info = {"lo": lo_rows[-1][1], "hi": hi_rows[-1][1], "as_of": hi_rows[-1][0], "changed": None, "delta": None}
    for i in range(len(hi_rows) - 1, 0, -1):
        if hi_rows[i][1] != hi_rows[i - 1][1]:
            info["changed"], info["delta"] = hi_rows[i][0], hi_rows[i][1] - hi_rows[i - 1][1]
            break
    return info


def fetch_policy_rate():
    try:
        return policy_rate_info(_fred_rows("DFEDTARL", 1100), _fred_rows("DFEDTARU", 1100))
    except Exception as e:
        print(f"    [FRED 政策金利] 取得失敗: {type(e).__name__}")
        return None


def policy_rate_text(p):
    s = f"政策金利(FRBが決める金利):{p['lo']:.2f}〜{p['hi']:.2f}%"
    if p.get("changed"):
        d = _to_iso_date(p["changed"])
        word = "利上げ" if p["delta"] > 0 else "利下げ"
        s += f" ・ 最後の変更は{d.year}年{d.month}月{d.day}日の{word}({_sg(p['delta'])}ポイント)"
    return s


# ========================================
# 3b. 要約の検証
# ========================================
SECTION_KEYS = [("stock", 6), ("fed", 3), ("jobs", 5), ("earnings", 3)]
DEFAULT_HEADLINE = "米国経済ニュースまとめ"
_HEAD_INDEX_WORDS = ["S&P", "ナスダック", "ダウ", "米国株", "米株", "株価指数", "主要指数"]
_HEAD_DIR_WORDS = ["上昇", "下落", "反発", "反落", "続伸", "続落", "急騰", "急落", "値上がり", "値下がり", "最高値"]
_EN_WEEKDAY = {"月": "monday", "火": "tuesday", "水": "wednesday", "木": "thursday", "金": "friday"}
_EN_MONTHS = {1: ["january", "jan"], 2: ["february", "feb"], 3: ["march", "mar"], 4: ["april", "apr"],
              5: ["may"], 6: ["june", "jun"], 7: ["july", "jul"], 8: ["august", "aug"],
              9: ["september", "sept", "sep"], 10: ["october", "oct"], 11: ["november", "nov"],
              12: ["december", "dec"]}


def _headline_ok(h):
    """指数名と向きの語が両方入った見出し(値動きを見出しにしたもの)はFalse"""
    nh = unicodedata.normalize("NFKC", h)
    return not (any(w in nh for w in _HEAD_INDEX_WORDS) and any(w in nh for w in _HEAD_DIR_WORDS))


def _check_market_move(mm, articles, trade_date):
    """market_moveの照合(仕様7-2)。(結果 or None, ログ用の判定)を返す"""
    if not isinstance(mm, dict):
        return None, "AI出力なし"
    srcs = _valid_sources(mm.get("sources"), articles)
    if not srcs:
        return None, "落とした:出典が実在しない"
    quote = mm.get("quote")
    if not isinstance(quote, str) or _is_empty(quote):
        return None, "落とした:quoteが空"
    if "..." in quote or "…" in quote:
        return None, "落とした:quoteに省略記号"
    nq = _norm(quote)
    if not any(nq in _article_text(articles[n - 1]) for n in srcs):
        return None, "落とした:quoteが元記事に無い"
    text = _strip_filler(_clean(mm.get("text")))
    if not text:
        return None, "落とした:textが空"
    reason = _nums_problem(text, srcs, articles)
    if reason:
        return None, f"落とした:{reason}"
    day = mm.get("day") if mm.get("day") in WEEKDAY_JA else "不明"
    note = ""
    if day in _EN_WEEKDAY and _EN_WEEKDAY[day] not in nq:
        note = f"(AIは{day}曜としたがquoteに曜日が無いため不明扱い)"
        day = "不明"
    same = bool(trade_date) and day != "不明" and WEEKDAYS[trade_date.weekday()] == day
    status = "same_day" if same else ("不明" if day == "不明" else "曜日違い")
    return {"day": day, "text": _unbp(text), "sources": srcs, "same_day": same}, status + note


def _check_upcoming(u, articles, trade_date):
    """今後の予定1件の照合(仕様7-3)。ダメならNone"""
    if not isinstance(u, dict):
        return None
    src = u.get("source")
    if isinstance(src, bool) or not isinstance(src, int) or not (1 <= src <= len(articles)):
        return None
    quote = u.get("quote")
    if not isinstance(quote, str) or _is_empty(quote) or "..." in quote or "…" in quote:
        return None
    nq = _norm(quote)
    if nq not in _article_text(articles[src - 1]):
        print(f"    [drop 予定] quoteが元記事に無い: {str(u.get('event'))[:20]}")
        return None
    d = _to_iso_date(u.get("date_iso")) if isinstance(u.get("date_iso"), str) else None
    base = trade_date or datetime.now(JST).date()
    if not d or d <= base:
        print(f"    [drop 予定] 日付が無い/対象日以前: {u.get('date_iso')}")
        return None
    names = _EN_MONTHS[d.month]
    month_ok = any(re.search(r"(?<![a-z])" + n + (r"\.?\s+\d" if n == "may" else r"(?![a-z])"), nq) for n in names)
    if not month_ok or _num_pos(str(d.day), nq.replace(",", "")) < 0:
        print(f"    [drop 予定] quoteに月名か日の数字が無い: {u.get('date_iso')}")
        return None
    event = _strip_filler(_clean(u.get("event")))
    if not event or _nums_problem(event, [src], articles):
        return None
    return {"date": d, "event": _unbp(event), "source": src}


def _pending(headline="米国経済ニュース(要約準備中)"):
    return {"ok": False, "headline": headline, "market_move": None, "key_points": [], "markets": [],
            "sections": {k: [] for k, _ in SECTION_KEYS}, "upcoming": []}


def parse_summary(raw, econ_articles, trade_date=None):
    """経済要約のJSONを読み、検証済みの中身だけを返す。読めなければ ok=False(要約なしモード)。
    trade_date:対象日(S&P 500の最新終値の日)。market_moveの曜日判定と、予定の絞り込みに使う"""
    td = _to_iso_date(trade_date)
    _FILLER_COUNT["n"] = 0
    data = _loads_loose(raw)
    if not isinstance(data, dict):
        print("  [WARN] summary JSON parse failed")
        return _pending()

    headline = data.get("headline")
    if not isinstance(headline, str) or _is_empty(headline):
        headline = DEFAULT_HEADLINE
    elif len(headline.strip()) > 20:
        # 少し超えただけで既定文に置き換えると、その日の見出しが消えてしまう(10/9の初回本番で発生)。
        # 30字までは許し、それを超える時は読点で切る。切れなければ既定文
        h = headline.strip()
        if len(h) > 30:
            cut = max(h.rfind("、", 0, 30), h.rfind("。", 0, 30))
            h = h[:cut] if cut >= 8 else ""
        headline = h or DEFAULT_HEADLINE
    headline = headline.replace("**", "").strip()
    if not _headline_ok(headline):
        print(f"  [見出し] 値動きの見出しのため既定文に差し替え: {headline}")
        headline = DEFAULT_HEADLINE
    elif _nums_problem(headline, list(range(1, len(econ_articles) + 1)), econ_articles):
        print(f"  [見出し] 記事に無い数値のため既定文に差し替え: {headline}")
        headline = DEFAULT_HEADLINE
    headline = _unbp(headline)

    mm, mm_status = _check_market_move(data.get("market_move"), econ_articles, td)
    print(f"  market_move: {mm_status}" + (f"(day={mm['day']})" if mm else ""))

    key_points = []
    kp = data.get("key_points") if isinstance(data.get("key_points"), list) else []
    for item in kp:
        line = _check_line(item, econ_articles, opt=("why",))
        if line:
            cat = line.get("category")
            line["category"] = cat if cat in KEY_CATEGORIES else "その他"
            key_points.append(line)
        if len(key_points) == 3:
            break
    print(f"  今日の要点: AI出力{len(kp)}件 → 照合通過{len(key_points)}件")

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
        print(f"  {key}: AI出力{len(items)}件 → 照合通過{len(sections[key])}件")

    upcoming = []
    up = data.get("upcoming") if isinstance(data.get("upcoming"), list) else []
    for u in up:
        r = _check_upcoming(u, econ_articles, td)
        if r:
            upcoming.append(r)
    upcoming = sorted(upcoming, key=lambda x: x["date"])[:4]
    print(f"  upcoming: AI出力{len(up)}件 → 照合通過{len(upcoming)}件")
    print(f"  [filler] {_FILLER_COUNT['n']}文を削除")

    if not key_points and not markets and not any(sections.values()) and not mm:
        # 照合ですべて捨てられた日は、見出しだけの空のページにせず「要約準備中」に切り替える
        print("  [WARN] summary items all dropped by validation")
        return _pending()
    return {"ok": True, "headline": headline, "market_move": mm, "key_points": key_points,
            "markets": markets, "sections": sections, "upcoming": upcoming}


def econ_used_urls(econ, econ_articles):
    """経済欄(要点・各欄・market_move)で使った記事のURL"""
    nums = set()
    if econ.get("ok"):
        for k in econ["key_points"]:
            nums.update(k["sources"])
        for key, _ in SECTION_KEYS:
            for l in econ["sections"][key]:
                nums.update(l["sources"])
        if econ.get("market_move"):
            nums.update(econ["market_move"]["sources"])
    return {econ_articles[n - 1].get("url") for n in nums if econ_articles[n - 1].get("url")}


def parse_major_news(raw, major_articles, econ_urls=()):
    """主要ニュースのJSONを読み、検証済みの記事だけを返す。
    JSONが読めない時だけ ok=False(英語見出しの予備表示)。items が [] なら ok=True で何も出さない"""
    _FILLER_COUNT["n"] = 0
    data = _loads_loose(raw)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        print("  [WARN] 主要ニュースの要約を使えないため、英語見出しのみ表示します")
        return {"ok": False, "items": []}
    econ_urls = set(econ_urls or ())
    items = []
    for it in data["items"]:
        if not isinstance(it, dict):
            continue
        title = _strip_filler(_clean(it.get("title")))
        if not title:
            continue
        conn = it.get("connection")
        if conn not in CONNECTIONS:
            print(f"    [drop 主要] connectionが無い/一覧外: {title[:20]}")
            continue
        srcs = _valid_sources(it.get("sources"), major_articles)
        bullets = [b for b in (_check_line(x, major_articles, opt=())
                               for x in (it.get("bullets") if isinstance(it.get("bullets"), list) else [])) if b][:3]
        for b in bullets:
            for n in b["sources"]:
                if n not in srcs:
                    srcs.append(n)
        if not srcs:
            continue
        lead = _strip_filler(_clean(it.get("lead")))
        bad = _nums_problem(title, srcs, major_articles) or _nums_problem(lead, srcs, major_articles)
        if bad:
            print(f"    [drop 主要] {bad}: {title[:20]}")
            continue
        urls = {major_articles[n - 1].get("url") for n in srcs}
        if urls & econ_urls:
            print(f"    [drop 主要] 経済欄と同じ記事: {title[:20]}")
            continue
        wim = _strip_filler(_clean(it.get("why_it_matters")))
        if wim and _nums_problem(wim, srcs, major_articles):
            wim = ""
        cat = it.get("category")
        items.append({
            "category": cat if cat in MAJOR_CATEGORIES else "",
            "connection": conn,
            "title": _unbp(title),
            "lead": _unbp(lead),
            "bullets": bullets,
            "why_it_matters": _unbp(wim),
            "sources": srcs,
        })
        if len(items) == 3:
            break
    print(f"  主要ニュース: AI出力{len(data['items'])}件 → 照合通過{len(items)}件 [filler] {_FILLER_COUNT['n']}文を削除")
    return {"ok": True, "items": items}


# ========================================
# 4. HTMLを生成
# ========================================

_ICONS = {
    "trending-up": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 17 9 11 13 15 21 6"/><polyline points="14 6 21 6 21 13"/></svg>',
    "bank": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="3" y1="21" x2="21" y2="21"/><line x1="5" y1="21" x2="5" y2="10"/><line x1="19" y1="21" x2="19" y2="10"/><line x1="12" y1="21" x2="12" y2="10"/><polygon points="12 3 21 8 3 8"/></svg>',
    "briefcase": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>',
    "bar-chart": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>',
    "newspaper": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4h13a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H7a3 3 0 0 1-3-3V4z"/><path d="M18 8h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><line x1="8" y1="8" x2="14" y2="8"/><line x1="8" y1="12" x2="14" y2="12"/><line x1="8" y1="16" x2="11" y2="16"/></svg>',
    "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><line x1="16" y1="3" x2="16" y2="7"/><line x1="8" y1="3" x2="8" y2="7"/><line x1="3" y1="11" x2="21" y2="11"/></svg>',
}


def _esc(s):
    """HTMLへの埋め込み用にエスケープ(外部APIの文字列を信用しない)"""
    return html.escape(s or "", quote=True)


SECTION_META = {
    "stock": ("sec-stock", "株式市場", "株式", "trending-up"),
    "fed": ("sec-fed", "金利・FRB", "金利・FRB", "bank"),
    "jobs": ("sec-jobs", "物価・雇用", "物価・雇用", "briefcase"),
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


def _report_date(srcs, articles):
    """出典記事のうち最も新しい配信日の「11/12の報道」。読めなければ空"""
    d = _latest_pub_date([articles[n - 1] for n in srcs])
    return f"{_md(d)}の報道" if d else ""


def _market_card(c):
    if c["name"] in NEUTRAL_CARDS:
        cls = "neutral"
    else:
        cls = {1: "up", -1: "down"}.get(c["direction"], "flat")
    arrow = {1: "▲", -1: "▼", "flat": "―"}.get(c["direction"], "")
    arrow_html = f'<span aria-hidden="true">{arrow} </span>' if arrow else ""
    value_html = (f'<span class="card-value">{_esc(c["value_text"])}</span>' if c.get("value_text")
                  else '<span class="card-value none">値の記載なし</span>')
    chg_html = f'<span class="card-chg">{arrow_html}{_esc(c["chg_text"])}</span>'
    if c.get("direction") == 0:
        chg_html += '<span class="card-note">向きの記載なし</span>'
    desc = CARD_DESC.get(c["name"], "")
    range_html = f'\n          <span class="card-range">{_esc(c["range_text"])}</span>' if c.get("range_text") else ""
    date_html = (f'\n          <span class="card-date stale">{_esc(c["date_label"])}</span>'
                 if c.get("stale") and c.get("date_label") else "")
    read = "、".join(x for x in [c["name"], c.get("value_text") or "値の記載なし", c.get("chg_read") or "",
                                 c.get("range_text") or "", c.get("date_label") if c.get("stale") else ""] if x)
    return f"""
        <li class="card {cls}" role="group" aria-label="{_esc(read)}">
          <span class="card-name" aria-hidden="true">{_esc(c['name'])}</span>
          <span class="card-desc" aria-hidden="true">{_esc(desc)}</span>
          <span aria-hidden="true">{value_html}</span>
          <span aria-hidden="true">{chg_html}</span>{range_html}{date_html}
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
        if econ.get("market_move"):
            for n in econ["market_move"]["sources"]:
                add(econ_articles[n - 1])
        for kp in econ["key_points"]:
            for n in kp["sources"]:
                add(econ_articles[n - 1])
        for c in econ["markets"]:
            if c.get("source"):
                add(econ_articles[c["source"] - 1])
        for key, _ in SECTION_KEYS:
            for l in econ["sections"][key]:
                for n in l["sources"]:
                    add(econ_articles[n - 1])
        for u in econ.get("upcoming", []):
            add(econ_articles[u["source"] - 1])
    for it in major["items"]:
        for n in it["sources"]:
            add(major_articles[n - 1])
    for a in econ_articles:
        if _is_econ(a):
            add(a)  # 10本に満たなくても、経済と無関係な記事では埋めない
    return picked[:10]


def news_date_of(econ, econ_articles, major, major_articles):
    """ページに載せた記事(元記事一覧)のうち、いちばん新しい配信日(米国東部時間)"""
    return _latest_pub_date(_source_list(econ, econ_articles, major, major_articles))


def _pct_cell(v):
    if v is None:
        return '<td class="na">―</td>'
    if v == 0:
        return '<td>±0.00%</td>'
    cls, arrow, sign = ("up", "▲", "+") if v > 0 else ("down", "▼", "−")
    return f'<td class="{cls}"><span aria-hidden="true">{arrow}</span>{sign}{abs(v):.2f}%</td>'


def _trend_table(trends, trade_date=None):
    """主要3指数の推移表(終値と前日比はカードと「昨日の米国市場」にあるため、ここでは出さない)"""
    rows = "".join(f"""
          <tr><th scope="row">{_esc(t['name'])}{f'<span class="tt-date">{_esc(t["date"])}終値</span>' if t.get('date_iso') != trade_date else ''}</th>{_pct_cell(t['w1'])}{_pct_cell(t['m1'])}{_pct_cell(t['ytd'])}{_pct_cell(t['from_high'])}</tr>"""
                   for t in trends)
    return f"""
      <h3 class="sub-h" id="h-tt">株価指数の推移</h3>
      <div class="tt-wrap" role="region" aria-labelledby="h-tt" tabindex="0">
        <table class="tt">
          <thead><tr><th scope="col">指数</th><th scope="col">1週間</th>
            <th scope="col">1か月</th><th scope="col">年初来</th><th scope="col">1年の高値から</th></tr></thead>
          <tbody>{rows}
          </tbody>
        </table>
      </div>
      <p class="tt-note">1年の高値から:この1年でいちばん高かった終値から、今どれだけ下にいるか。0%なら最高値にいる。</p>"""


def _indicators(macro):
    blocks = ""
    for m in macro:
        extra = "".join(f'\n          <p class="{k2}">{_esc(pre + m[k])}</p>'
                        for k, k2, pre in [("prev", "ind-prev", ""), ("base", "ind-base", ""), ("read", "ind-read", "読み方:")]
                        if m.get(k))
        blocks += f"""
        <div class="ind" data-series="{_esc(m['sid'])}">
          <div class="ind-head"><span class="ind-name">{_esc(m['name'])}</span><span class="ind-period">{_esc(m['period'])}</span><span class="ind-val">{_esc(m['value'])}</span></div>
          <p class="ind-desc">{_esc(m['desc'])}</p>{extra}
        </div>"""
    return f"""
      <h3 class="sub-h" id="h-mc">最新の指標</h3>
      <div class="inds">{blocks}
      </div>
      <p class="note">発表は月1回(新規失業保険申請は週1回)のため、毎日は変わりません。</p>"""


def _story_items(lines, articles):
    out = ""
    for l in lines:
        title = f'<span class="l-title">{_esc(l["title"])}</span>' if l.get("title") else ""
        why = f'<span class="s-why">なぜ:{_esc(l["why"])}</span>' if l.get("why") else ""
        eff = f'<span class="s-effect">影響:{_esc(l["effect"])}</span>' if l.get("effect") else ""
        rd = _report_date(l["sources"], articles)
        meta = f'<span class="story-meta"><span class="story-date">{_esc(rd)}</span>{_src_links(l["sources"], articles)}</span>'
        out += f'\n        <li class="story-item">{title}<span class="s-what">{_esc(l["text"])}</span>{why}{eff}{meta}</li>'
    return out


def _glossary_hits(texts, limit=6):
    """AIが書いた文に出てきた用語集の語を、出てきた順に最大limit語"""
    joined = _norm(" ".join(t for t in texts if t))
    hits = []
    for key, dt, words, dd in GLOSSARY:
        pos = []
        for w in words:
            nw = _norm(w)
            if re.fullmatch(r"[a-z0-9&\s]+", nw):   # 英字の語は英単語の一部に一致させない(BP社など)
                m = re.search(r"(?<![a-z])" + re.escape(nw) + r"(?![a-z])", joined)
            else:
                m = re.search(re.escape(nw), joined)
            if m:
                pos.append(m.start())
        if pos:
            hits.append((min(pos), key, dt, dd))
    return [h[1:] for h in sorted(hits)[:limit]]


def ai_texts(econ, major):
    """用語ブロックの対象にする、AIが書いた文(ページに出る順)"""
    t = [econ.get("headline", "")] if econ.get("ok") else []
    if econ.get("ok"):
        if econ.get("market_move"):
            t.append(econ["market_move"]["text"])
        for k in econ["key_points"]:
            t += [k["text"], k.get("why") or ""]
        for key, _ in SECTION_KEYS:
            for l in econ["sections"][key]:
                t += [l.get("title", ""), l["text"], l.get("why") or "", l.get("effect") or ""]
        t += [u["event"] for u in econ.get("upcoming", [])]
    for it in major.get("items", []):
        t += [it["title"], it["lead"], it.get("why_it_matters") or ""] + [b["text"] for b in it["bullets"]]
    return t


def generate_html(econ, econ_articles, major, major_articles, now=None):
    """静的HTML1枚を返す(JSなし。外部読み込みはGoogle Fontsのみ)"""
    now = now or datetime.now(JST)
    date_str = _jp_date(now)
    time_str = f"{now.hour}:{now.minute:02d}"
    td_iso = econ.get("trade_date")
    td = _to_iso_date(td_iso)
    td_label = _jp_date(td) if td else ""

    srcs = _source_list(econ, econ_articles, major, major_articles)
    nd = _latest_pub_date(srcs)

    # ── 対象日 ──
    asof_html = ""
    if td or nd:
        if td and nd:
            news = "ニュースも同じ日までの報道" if nd == td else f"ニュースは{_jp_date(nd)}までの報道"
            asof_html = f'\n  <p class="asof" data-trade-date="{td.isoformat()}">{_esc(td_label)}の米国市場 ・ {news}</p>'
        elif td:
            asof_html = f'\n  <p class="asof" data-trade-date="{td.isoformat()}">{_esc(td_label)}の米国市場</p>'
        else:
            asof_html = f'\n  <p class="asof">ニュースは{_jp_date(nd)}までの報道</p>'

    # ── 昨日の米国市場 ──
    today_html = ""
    t = econ.get("today")
    if t:
        size = ""
        if t.get("size"):
            size = (f'<br>S&amp;P 500の動きは<span class="size-label">「{_esc(t["size"]["label"])}」'
                    f'(この1年の1日の値動きの中で、大きい方から上位{t["size"]["n"]}%)</span>')
        lines = f'\n      <p class="today-stocks">{_esc(t["stocks"])}{size}</p>'
        if t.get("yen"):
            lines += f'\n      <p class="today-yen">{_esc(t["yen"]["line"])}</p>'
            if t.get("jpy_sp"):
                j = t["jpy_sp"]
                lines += (f'\n      <p class="today-jpy-sp">円で見たS&amp;P 500の目安:<strong>{_esc(j["text"])}</strong>'
                          f'(株の動き {_esc(j["sp"])} と、ドル円の動き {_esc(j["fx"])} を合わせたもの)'
                          f'<span class="today-note">円建ての投資信託の値段は日本の朝の為替レートで決まるため、この数字と一致はしません。</span></p>')
        missing = (f"{t['trade_label']}の値動きの理由を書いた記事は、まだ取得できていません"
                   "(使っているニュースの一部は約1日遅れで届くため)。")
        mm = econ.get("market_move") if econ.get("ok") else None
        if mm and mm["same_day"]:
            why = f'値動きの理由(報道より):{_esc(mm["text"])}{_src_links(mm["sources"], econ_articles)}'
        elif mm:
            if mm["day"] != "不明":
                ref = f"{mm['day']}曜日の値動きについての報道"
            else:
                d = _latest_pub_date([econ_articles[n - 1] for n in mm["sources"]])
                ref = f"{_md(d)}の報道" if d else "以前の報道"
            why = (f'{_esc(missing)}<span class="today-ref">参考:{_esc(ref)} ─ {_esc(mm["text"])}'
                   f'{_src_links(mm["sources"], econ_articles)}</span>')
        else:
            why = _esc(missing)
        lines += f'\n      <p class="today-why">{why}</p>'
        today_html = f"""
    <section class="block today" id="today" aria-labelledby="h-today">
      <h2 id="h-today">{_esc(t['trade_label'])}の米国市場</h2>{lines}
    </section>"""

    # ── 今日の要点 ──
    kp_html = ""
    if econ["ok"] and econ["key_points"]:
        lis = ""
        for i, k in enumerate(econ["key_points"], 1):
            why = (f'<span class="kp-why"><span aria-hidden="true">→ </span>{_esc(k["why"])}</span>'
                   if k.get("why") else "")
            rd = _report_date(k["sources"], econ_articles)
            lis += f"""
        <li class="kp">
          <span class="kp-num" aria-hidden="true">{i}</span>
          <div class="kp-body"><span class="tag">{_esc(k['category'])}</span><span class="kp-text">{_esc(k['text'])}</span>{_src_links(k['sources'], econ_articles)}{why}<span class="kp-date">{_esc(rd)}</span></div>
        </li>"""
        kp_html = f"""
    <section class="block" aria-labelledby="h-kp">
      <h2 id="h-kp">今日の要点</h2>
      <ol class="kps">{lis}
      </ol>
    </section>"""

    # ── 主な数値(3群) ──
    mk_html = ""
    if econ["markets"]:
        by = {c["name"]: c for c in econ["markets"]}
        groups = ""
        for gi, (gname, names) in enumerate(MARKET_GROUPS):
            cs = [by[n] for n in names if n in by]
            if not cs:
                continue
            groups += f"""
      <h3 class="grp-h" id="h-mk-{gi}">{_esc(gname)}</h3>
      <ul class="cards" aria-labelledby="h-mk-{gi}">{"".join(_market_card(c) for c in cs)}
      </ul>"""
        if td:
            if all(not c.get("stale") for c in econ["markets"]):
                note = f"すべて{td_label}の終値"
            else:
                note = f"日付の表示が無いカードは、{td_label}の終値"
            groups += f'\n      <p class="asof-note">{_esc(note)}</p>'
        mk_html = f"""
    <section class="block" id="markets" aria-labelledby="h-mk">
      <h2 id="h-mk">主な数値</h2>{groups}
    </section>"""

    # ── 主要ニュース(見出しのみ) ──
    major_note = ""
    if major["ok"]:
        heads = "".join(
            f'\n        <li><a href="#major-{i}"><span class="tag">{_esc(it["connection"])}</span>{_esc(it["title"])}</a></li>'
            for i, it in enumerate(major["items"], 1))
    else:
        fb = [a for a in major_articles if a.get("url") and _is_econ(a)][:3]
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

    # ── 分野別 ──
    sec_html, nav_links = "", []
    for key, _ in SECTION_KEYS:
        lines = econ["sections"][key] if econ["ok"] else []
        table = ""
        if key == "stock" and econ.get("trends"):
            table = _trend_table(econ["trends"], td_iso)
        elif key == "fed" and econ.get("policy"):
            table = (f'\n      <p class="policy-rate">{_esc(policy_rate_text(econ["policy"]))}</p>'
                     f'\n      <p class="policy-desc">{_esc(POLICY_DESC)}</p>')
        elif key == "jobs" and econ.get("macro"):
            table = _indicators(econ["macro"])
        if not lines and not table:
            continue  # 該当なしの日はセクションごと出さない
        sid, title, short, icon = SECTION_META[key]
        nav_links.append((sid, short))
        news = ""
        if lines:
            news = (f'\n      <h3 class="sub-h">ニュースから</h3>' if table else "") + f"""
      <ul class="lines">{_story_items(lines, econ_articles)}
      </ul>"""
        sec_html += f"""
    <section class="block" id="{sid}" aria-labelledby="h-{sid}">
      <h2 id="h-{sid}"><span class="h-icon">{_ICONS[icon]}</span>{_esc(title)}</h2>{table}{news}
    </section>"""

    # ── 今後の予定 ──
    up_html = ""
    if econ["ok"] and econ.get("upcoming"):
        lis = "".join(
            f'\n        <li><span class="upc-date">{_esc(_jp_date(u["date"]))}</span>'
            f'<span class="upc-event">{_esc(u["event"])}</span>{_src_links([u["source"]], econ_articles)}</li>'
            for u in econ["upcoming"])
        nav_links.append(("upcoming", "予定"))
        up_html = f"""
    <section class="block" id="upcoming" aria-labelledby="h-upcoming">
      <h2 id="h-upcoming"><span class="h-icon">{_ICONS['calendar']}</span>今後の予定(報道より)</h2>
      <ul class="upc">{lis}
      </ul>
    </section>"""

    # ── 主要ニュース 詳細 ──
    detail_html = ""
    if major["ok"] and major["items"]:
        arts = ""
        for i, it in enumerate(major["items"], 1):
            bl = "".join(f'\n          <li><span>{_esc(b["text"])}</span>{_src_links(b["sources"], major_articles)}</li>' for b in it["bullets"])
            tag = "".join(f'<span class="tag">{_esc(x)}</span>' for x in (it["category"], it["connection"]) if x)
            lead = f'\n        <p class="lead">{_esc(it["lead"])}</p>' if it["lead"] else ""
            wim = (f'\n        <p class="why-matters">私たちへのつながり:{_esc(it["why_it_matters"])}</p>'
                   if it.get("why_it_matters") else "")
            rd = _report_date(it["sources"], major_articles)
            more = "" if it["bullets"] else _src_links(it["sources"], major_articles)
            arts += f"""
      <article class="story" id="major-{i}" aria-labelledby="h-major-{i}">
        <h3 id="h-major-{i}">{tag}{_esc(it['title'])}</h3>{lead}
        <ul class="lines">{bl}
        </ul>{wim}
        <p class="story-meta"><span class="story-date">{_esc(rd)}</span>{more}</p>
      </article>"""
        nav_links.append(("major-detail", "主要ニュース"))
        detail_html = f"""
    <section class="block" id="major-detail" aria-labelledby="h-major-detail">
      <h2 id="h-major-detail"><span class="h-icon">{_ICONS['newspaper']}</span>主要ニュース 詳細</h2>{arts}
    </section>"""

    # ── 用語 ──
    gl_html = ""
    hits = _glossary_hits(ai_texts(econ, major))
    if hits:
        dl = "".join(f'\n        <dt id="g-{key}">{_esc(dt)}</dt><dd>{_esc(dd)}</dd>' for key, dt, dd in hits)
        nav_links.append(("glossary", "用語"))
        gl_html = f"""
    <section class="block" id="glossary" aria-labelledby="h-glossary">
      <h2 id="h-glossary">このページに出てきた用語</h2>
      <dl class="gl">{dl}
      </dl>
    </section>"""

    nav_html = ""
    if nav_links:
        nav_html = '\n    <nav class="jump" aria-label="分野へ移動">' + "".join(
            f'<a href="#{sid}">{_esc(label)}</a>' for sid, label in nav_links) + "</nav>"

    # ── 元記事一覧 ──
    def _src_date(a):
        d = _pub_et(a)
        return f'<span class="src-date"> ・ {_md(d)}</span>' if d else ""
    src_lis = "".join(
        f'\n        <li><a href="{_esc(a["url"])}" target="_blank" rel="noopener noreferrer">'
        f'<span class="src-name">{_esc(a.get("source", ""))}{_src_date(a)}</span><span class="src-title" lang="en">{_esc(a["title"])}</span></a></li>'
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
    --focus: #1e40af; --panel: #f8fafc;
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

  main {{ max-width: 680px; margin: 0 auto; padding: 20px 16px 56px; }}
  .asof {{ font-size: 13px; font-weight: 500; color: var(--muted); line-height: 1.6; margin-bottom: 6px; }}
  h1 {{ font-family: var(--serif); font-size: 26px; font-weight: 700; line-height: 1.35; color: var(--ink); }}
  .notice {{ margin-top: 24px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 8px; font-size: 15px; }}

  .block {{ margin-top: 40px; }}
  h2 {{ display: flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 700; line-height: 1.4; color: var(--ink); margin-bottom: 16px; }}
  .h-icon {{ display: inline-flex; width: 20px; height: 20px; color: var(--muted); flex-shrink: 0; }}
  .h-icon svg {{ width: 100%; height: 100%; }}

  .today {{ margin-top: 20px; padding: 16px; border: 1px solid var(--line); border-left: 4px solid var(--ink); border-radius: 8px; background: var(--panel); }}
  .today h2 {{ font-size: 16px; margin-bottom: 8px; }}
  .today p {{ font-size: 15px; line-height: 1.75; color: var(--ink); }}
  .today p + p {{ margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--line); }}
  .today-stocks {{ font-weight: 500; }}
  .size-label {{ font-weight: 400; color: var(--text); }}
  .today-jpy-sp strong {{ font-variant-numeric: tabular-nums; }}
  .today-note {{ display: block; font-size: 12px; color: var(--muted); line-height: 1.6; margin-top: 2px; }}
  .today-why {{ font-size: 14px !important; color: var(--text) !important; }}
  .today-ref {{ display: block; margin-top: 4px; color: var(--muted); }}

  .kps {{ list-style: none; display: grid; gap: 14px; }}
  .kp {{ display: grid; grid-template-columns: 28px 1fr; gap: 12px; align-items: start; }}
  .kp-num {{ width: 28px; height: 28px; border-radius: 50%; background: var(--brand); color: #ffffff; font-size: 15px; font-weight: 700; display: flex; align-items: center; justify-content: center; margin-top: 1px; font-variant-numeric: tabular-nums; }}
  .kp-body {{ font-size: 17px; font-weight: 500; line-height: 1.6; color: var(--ink); }}
  .kp-why {{ display: block; margin: 4px 0 0 1em; font-size: 15px; font-weight: 400; line-height: 1.7; color: var(--text); }}
  .kp-date {{ display: block; margin-left: 1em; font-size: 12px; font-weight: 400; color: var(--muted); }}
  .tag {{ display: inline-block; font-size: 12px; font-weight: 500; line-height: 1.5; color: var(--muted); border: 1px solid #cfd4da; border-radius: 4px; padding: 0 6px; margin-right: 8px; vertical-align: 2px; white-space: nowrap; }}

  .tt-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  .tt {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; font-size: 14px; white-space: nowrap; }}
  .tt th, .tt td {{ padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: right; }}
  .tt th[scope="row"], .tt thead th:first-child {{ text-align: left; position: sticky; left: 0; background: #fff; }}
  .tt thead th {{ font-size: 12px; font-weight: 600; color: var(--muted); white-space: normal; }}
  .tt .tt-date {{ display: block; font-size: 11px; font-weight: 400; color: var(--muted); }}
  .tt td.up {{ color: var(--up); }} .tt td.down {{ color: var(--down); }} .tt td.na {{ color: var(--muted); }}
  .tt-note {{ font-size: 12px; color: var(--muted); line-height: 1.6; margin-top: 8px; }}
  .sub-h {{ font-size: 14px; font-weight: 700; color: var(--muted); margin: 14px 0 6px; }}
  @media (max-width: 480px) {{
    /* 4列をスマホ幅(375px)に収める:指数名は折り返し、余白と文字を詰める */
    .tt {{ font-size: 12.5px; }}
    .tt th, .tt td {{ padding: 7px 3px; }}
    .tt th[scope="row"] {{ white-space: normal; width: 5.2em; }}
    .tt td span[aria-hidden] {{ font-size: 10px; }}
  }}
  .grp-h {{ font-size: 14px; font-weight: 700; color: var(--muted); margin: 18px 0 8px; }}
  .grp-h:first-of-type {{ margin-top: 0; }}
  .cards {{ list-style: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }}
  .card {{ display: flex; flex-direction: column; gap: 2px; border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; font-variant-numeric: tabular-nums; }}
  .card.up {{ background: var(--up-bg); }} .card.up .card-chg {{ color: var(--up); }}
  .card.down {{ background: var(--down-bg); }} .card.down .card-chg {{ color: var(--down); }}
  .card.flat {{ background: var(--flat-bg); }} .card.flat .card-chg {{ color: var(--flat); }}
  .card.neutral {{ background: var(--flat-bg); }} .card.neutral .card-chg {{ color: var(--ink); }}
  .card-name {{ font-size: 13px; font-weight: 700; color: var(--ink); line-height: 1.4; }}
  .card-desc {{ font-size: 12px; color: var(--muted); line-height: 1.5; margin-bottom: 4px; }}
  .card-value {{ display: block; font-family: 'Roboto', sans-serif; font-size: 22px; font-weight: 700; color: var(--ink); line-height: 1.3; }}
  .card-value.none {{ font-family: var(--sans); font-size: 13px; font-weight: 400; color: var(--muted); line-height: 1.7; padding: 3px 0 2px; }}
  .card-chg {{ display: block; font-family: 'Roboto', 'Noto Sans JP', sans-serif; font-size: 15px; font-weight: 700; line-height: 1.4; }}
  .card-note {{ display: block; font-size: 12px; color: var(--flat); line-height: 1.4; }}
  .card-range {{ font-size: 12px; color: var(--muted); line-height: 1.5; margin-top: 4px; }}
  .card-date {{ font-size: 12px; font-weight: 700; color: var(--muted); line-height: 1.4; }}
  .asof-note {{ font-size: 12px; color: var(--muted); line-height: 1.6; margin-top: 10px; }}
  .note {{ font-size: 12px; color: var(--muted); line-height: 1.6; margin-top: 8px; }}

  .policy-rate {{ font-size: 16px; font-weight: 700; color: var(--ink); line-height: 1.6; }}
  .policy-desc {{ font-size: 14px; color: var(--text); line-height: 1.7; margin-top: 4px; }}

  .inds {{ border-top: 1px solid var(--line); }}
  .ind {{ padding: 12px 0; border-bottom: 1px solid var(--line); }}
  .ind-head {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; }}
  .ind-name {{ font-size: 15px; font-weight: 700; color: var(--ink); }}
  .ind-period {{ font-size: 12px; color: var(--muted); }}
  .ind-val {{ margin-left: auto; font-size: 15px; font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; }}
  .ind p {{ font-size: 13px; line-height: 1.65; color: var(--text); }}
  .ind .ind-desc, .ind .ind-prev, .ind .ind-base {{ color: var(--muted); }}
  .ind .ind-read {{ color: var(--ink); margin-top: 2px; }}

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
  .lines li.story-item {{ padding-left: 0; padding-bottom: 12px; border-bottom: 1px solid var(--line); }}
  .lines li.story-item::before {{ display: none; }}
  .l-title {{ display: block; font-size: 16px; font-weight: 700; color: var(--ink); line-height: 1.6; margin-bottom: 2px; }}
  .s-what {{ display: block; font-size: 15px; line-height: 1.85; }}
  .s-why, .s-effect {{ display: block; font-size: 15px; line-height: 1.8; margin-top: 2px; }}
  .story-meta {{ display: block; font-size: 12px; color: var(--muted); margin-top: 4px; }}
  .lines li::before {{ content: ""; position: absolute; left: 2px; top: 0.8em; width: 5px; height: 5px; border-radius: 50%; background: #9aa1ac; }}
  .src {{ display: inline-block; margin-left: 8px; font-size: 12px; color: var(--muted); text-underline-offset: 2px; white-space: nowrap; }}
  .src + .src {{ margin-left: 6px; }}
  .src:hover {{ color: var(--ink); }}

  .story + .story {{ margin-top: 32px; padding-top: 24px; border-top: 1px solid var(--line); }}
  .story h3 {{ font-family: var(--serif); font-size: 19px; font-weight: 700; line-height: 1.45; color: var(--ink); margin-bottom: 8px; }}
  .story h3 .tag {{ font-family: var(--sans); vertical-align: 3px; }}
  .lead {{ font-size: 16px; font-weight: 500; line-height: 1.7; margin-bottom: 12px; color: var(--ink); }}
  .why-matters {{ font-size: 15px; line-height: 1.75; margin-top: 10px; padding: 8px 12px; background: var(--panel); border-radius: 6px; }}

  .upc {{ list-style: none; border-top: 1px solid var(--line); }}
  .upc li {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; padding: 10px 0; border-bottom: 1px solid var(--line); font-size: 15px; }}
  .upc-date {{ font-weight: 700; color: var(--ink); white-space: nowrap; font-variant-numeric: tabular-nums; }}

  .gl dt {{ font-size: 15px; font-weight: 700; color: var(--ink); margin-top: 12px; }}
  .gl dt:first-child {{ margin-top: 0; }}
  .gl dd {{ font-size: 14px; line-height: 1.75; color: var(--text); }}

  .sources summary {{ display: flex; align-items: center; min-height: 44px; font-size: 16px; font-weight: 700; color: var(--ink); cursor: pointer; border-top: 1px solid var(--line); }}
  .src-list {{ list-style: none; }}
  .src-list a {{ display: block; padding: 10px 0; border-bottom: 1px solid var(--line); text-decoration: none; }}
  .src-list a:hover .src-title {{ text-decoration: underline; }}
  .src-name {{ display: block; font-size: 12px; color: var(--muted); line-height: 1.5; }}
  .src-title {{ display: block; font-size: 14px; line-height: 1.6; color: var(--text); }}

  footer {{ border-top: 1px solid var(--line); }}
  .howmade {{ max-width: 680px; margin: 0 auto; padding: 20px 16px 32px; font-size: 12px; line-height: 1.7; color: var(--muted); }}
  .howmade h2 {{ font-size: 13px; color: var(--ink); margin-bottom: 4px; }}
  .howmade ul {{ list-style: none; }}
  .howmade p {{ margin-top: 8px; }}

  @media (min-width: 600px) {{
    main {{ padding-top: 32px; }}
    h1 {{ font-size: 34px; }}
    h2 {{ font-size: 20px; }}
    .today h2 {{ font-size: 17px; }}
    .block {{ margin-top: 48px; }}
    .today {{ margin-top: 24px; }}
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
<main id="main">{asof_html}
  <h1>{_esc(headline)}</h1>{notice}{today_html}{kp_html}{mk_html}{major_heads_html}{nav_html}{sec_html}{up_html}{detail_html}{gl_html}{src_html}
</main>
<footer>
  <div class="howmade">
    <h2>このページの作り方</h2>
    <ul>
      <li>・数値:Yahoo Finance(取れない時はセントルイス連邦準備銀行のFRED)の終値と米政府統計</li>
      <li>・文章:信頼できる報道機関の英語記事を、AI(Gemini)が要約。数字は元記事と機械で照合し、合わないものは載せていません。各文の「出典」から元記事を確かめられます</li>
      <li>・数字の読み方・用語の説明:あらかじめ用意した定型文です(AIの文ではありません)</li>
    </ul>
    <p>この内容は自動で作成したもので、誤りを含むことがあります。投資判断の根拠にしないでください。</p>
  </div>
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


def build_slack_payload(page_url, econ, major, major_articles, now=None):
    """Slackに送るJSON(dict)を作る。投稿はしない(確認時はこれをファイルに書き出す)。
    1段目の数字は「昨日の米国市場」の箱と同じ計算結果(econ['today'])から作る"""
    now = now or datetime.now(JST)
    date_str = _jp_date(now)
    headline = econ["headline"]
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"米国経済 朝刊|{date_str}"[:150]}}]
    t = econ.get("today")
    if t:
        size = f"({t['size']['label']})" if t.get("size") else ""
        first = f"米国株は{t['word']}:S&P 500 {t['sp_text']}{size}"
        if t.get("nasdaq_text"):
            first += f"・ナスダック {t['nasdaq_text']}"
        lines = [f"*{t['trade_label']}の米国市場*", first]
        if t.get("yen"):
            lines.append(t["yen"]["short"])
            if t.get("jpy_sp"):
                lines.append(f"円で見たS&P 500の目安 {t['jpy_sp']['text']}")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _slack_esc("\n".join(lines))}})
    if econ["ok"]:
        lines = [f"*{_slack_esc(headline)}*"]
        for i, k in enumerate(econ["key_points"], 1):
            lines.append(f"{i}. {_slack_esc(k['text'])}")
            if k.get("why"):
                lines.append(f"    → {_slack_esc(k['why'])}")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": "本日はAI要約を作れなかったため、元記事の見出しのみ掲載しています"}})
    nd = econ.get("news_date")
    srcs = {c.get("source_name") for c in econ.get("markets", []) if c.get("official")}
    num_src = "Yahoo Finance" + ("(一部FRED)" if "FRED" in srcs else "") if "Yahoo Finance" in srcs else "FRED"
    ctx = (f"ニュースは{_jp_date(nd)}までの報道です。" if nd else "") + (f"数値は{num_src}" if srcs else "")
    if ctx:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": _slack_esc(ctx)}]})
    if major["ok"]:
        heads = [f"[{it['connection']}] {it['title']}" for it in major["items"]]
    else:
        heads = [a["title"] for a in major_articles if _is_econ(a)][:3]
    if heads:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": "*主要ニュース*\n" + "\n".join(f"・{_slack_esc(h)}" for h in heads)}})
    if econ["ok"]:
        g = _glossary_hits([x for k in econ["key_points"] for x in (k["text"], k.get("why") or "")], limit=1)
        if g:
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                           "text": f"*今日の用語* {_slack_esc(g[0][1])}:{_slack_esc(g[0][2])}"}})
    blocks.append({"type": "section", "text": {"type": "mrkdwn",
                   "text": f"<{page_url}|ページで続きを読む(理由・指標・今後の予定)>  ・  <{page_url}#major|主要ニュースへ>"}})
    head = headline if econ["ok"] else f"{date_str}(要約準備中)"
    if t:
        parts = [f"米国株 S&P 500 {t['sp_text']}"]
        if t.get("yen"):
            parts.append(f"1ドル={t['yen']['value']}円 {t['yen']['word']}{t['yen'].get('when', '')}")
        text = "|".join(parts + [head])
    else:
        text = f"米国経済 朝刊|{head}"
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


def build_outputs(now=None, econ_summarizer=None, major_summarizer=None):
    """取得→要約→検証→HTML生成までを行い、公開・投稿はしない(main()とローカル確認の両方で使う)。
    数値を先に取るのは、最新の終値の日を要約の指示に入れるため(仕様6-5)"""
    now = now or datetime.now(JST)
    econ_summarizer = econ_summarizer or summarize_with_gemini
    major_summarizer = major_summarizer or summarize_major_news

    print("📈 市場の数値を取得中(Yahoo Finance、予備にFRED)...")
    market = fetch_market_data()
    td = market["trade_date"]
    trade_label = _jp_date(_to_iso_date(td)) if td else "(取得できませんでした)"

    print("📰 ニュース取得中(RSS)...")
    rss = fetch_rss()
    print("📰 経済ニュース取得中...")
    econ_articles = usable_econ_articles(fetch_news(rss))
    print(f"  要約に使う記事 {len(econ_articles)}件")
    print("📰 主要ニュース取得中...")
    major_articles = usable_major_articles(fetch_major_news(rss))
    print(f"  {len(major_articles)}件取得")

    print("🤖 経済ニュースを要約中...")
    econ = parse_summary(econ_summarizer(econ_articles, trade_label), econ_articles, td)
    official = build_market_cards(market)
    econ["markets"] = merge_markets(official, econ["markets"] if econ["ok"] else [])
    econ["trade_date"] = td
    econ["today"] = today_summary(market, econ["markets"])
    econ["trends"] = build_index_trends(market)
    print("📊 物価・雇用・政策金利(FRED)を取得中...")
    econ["macro"] = fetch_macro()
    econ["policy"] = fetch_policy_rate()
    print(f"  見出し: {econ['headline']}")

    print("🤖 主要ニュースを要約中...")
    major = parse_major_news(major_summarizer(major_articles), major_articles,
                             econ_used_urls(econ, econ_articles))
    for it in major["items"]:
        print(f"  主要: [{it['connection']}] {it['title']}")
    econ["news_date"] = news_date_of(econ, econ_articles, major, major_articles)

    print("🎨 HTMLページ生成中...")
    page_html = generate_html(econ, econ_articles, major, major_articles, now=now)
    return {"html": page_html, "econ": econ, "major": major, "market": market,
            "econ_articles": econ_articles, "major_articles": major_articles}


def main():
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"環境変数が未設定です: {', '.join(missing)}")
    try:
        out = build_outputs()

        print("🚀 GitHub Pagesに公開中...")
        page_url = publish_to_github_pages(out["html"])

        print("📤 Slackに投稿中...")
        post_to_slack(page_url, out["econ"], out["major"], out["major_articles"])

        print("✅ 完了！")
    except Exception as e:
        print(f"❌ エラー発生: {e}")
        notify_failure(stage=type(e).__name__, error=str(e))
        raise


if __name__ == "__main__":
    main()
