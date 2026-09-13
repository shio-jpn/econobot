"""
EconoBot - 米国経済ニュース自動要約
BBCスタイルHTMLページを生成 → GitHub Pages公開 → SlackにURLを投稿
"""

import os
import json
import time
import base64
import html
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# ========================================
# 設定
# ========================================
GEMINI_API_KEY    = os.environ["GEMINI_API_KEY"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
NEWS_API_KEY      = os.environ["NEWS_API_KEY"]
GITHUB_REPO       = os.environ["GITHUB_REPOSITORY"]   # 例: username/econobot
GITHUB_TOKEN      = os.environ["GITHUB_TOKEN"]         # Actions自動提供

JST = timezone(timedelta(hours=9))


# ========================================
# 1. NewsAPIでニュースを取得
# ========================================
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
                "description": a.get("description", ""),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", ""),
                "publishedAt": a.get("publishedAt", ""),
            })

    # ② everything: キーワード検索で補完（直近48時間）
    from_date = (datetime.now(JST) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            "from": from_date,
            "pageSize": 4,
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
                "description": a.get("description", ""),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", ""),
                "publishedAt": a.get("publishedAt", ""),
            })

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
            "description": a.get("description", ""),
            "source": a.get("source", {}).get("name", ""),
            "url": a.get("url", ""),
            "publishedAt": a.get("publishedAt", ""),
        })

    # ② キーワード検索で補完（48時間）
    from_date = (datetime.now(JST) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            "from": from_date,
            "pageSize": 5,
            "apiKey": NEWS_API_KEY,
        })
        url = f"https://newsapi.org/v2/everything?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "EconoBot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode())
        for a in data.get("articles", []):
            articles.append({
                "title": a.get("title", ""),
                "description": a.get("description", ""),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", ""),
                "publishedAt": a.get("publishedAt", ""),
            })

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
# 2. Gemini APIで要約（リトライあり）
# ========================================
def summarize_with_gemini(articles):
    news_text = "\n".join([
        f"- [{a['source']}] {a['title']}: {a['description']}"
        for a in articles if a["title"]
    ])
    today_str = datetime.now(JST).strftime("%Y年%-m月%-d日")

    prompt = f"""あなたは米国経済の専門アナリストです。
以下の英語ニュース記事はすべて本日・昨日の最新ニュースです。
本日（{today_str}）時点の最新情報として、日本語で要約してください。
古い情報や一般論は避け、記事に書かれている具体的な数値・日付・企業名・変動率を必ず使ってください。

【FRB・金融政策（FED）のルール】
- FRBの政策金利決定・FOMC会合・FRB高官の重要発言・量的緩和など主要な金融政策ニュースが
  本日のニュースに含まれる場合のみ、3〜4文で具体的に要約する。
- 該当するニュースがない場合は、必ず FED: NONE と出力する。

【雇用・インフレ（JOBS）のルール】
- 非農業部門雇用者数・失業率・CPI・PCEデフレーター・賃金上昇率など
  主要な雇用・インフレ指標の発表が本日のニュースに含まれる場合のみ、3〜4文で具体的に要約する。
- 該当するニュースがない場合は、必ず JOBS: NONE と出力する。

【企業決算（EARNINGS）のルール】
- NVDA・GOOGL・AAPL・MSFT・AMZN・META・TSLA・JPM・BAC・WMT など主要大手企業の決算発表が
  本日のニュースに含まれる場合のみ、3〜4文で具体的に要約する。
- 該当する決算ニュースがない場合は、必ず EARNINGS: NONE と出力する。

【STOCKの文量ルール】
- FED・JOBS・EARNINGSがすべてNONEの場合：STOCKを8〜10文と非常に詳しく書く。
- FED・JOBS・EARNINGSのうち1つがNONEの場合：STOCKを6〜7文と詳しく書く。
- FED・JOBS・EARNINGSがすべて揃っている場合：STOCKを3〜4文でまとめる。
- いずれの場合も具体的な指数の値・変動率・背景・要因・今後の見通しを含める。

出力形式（このフォーマットを厳守。他の文字を入れないこと）:
STOCK: （株式市場・相場の要約）
FED: （FRB・金融政策の要約、または NONE）
JOBS: （雇用・インフレの要約、または NONE）
EARNINGS: （大手企業決算の要約、または NONE）
HEADLINE: （本日全体を一言で表す見出し、20文字以内）

【ニュース記事】
{news_text}
"""

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }).encode("utf-8")

    # 試すモデルの優先順位（上から順に試す）
    models = [
        "gemini-2.5-flash-lite-preview-06-17",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
    ]

    for model in models:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models"
            f"/{model}:generateContent?key={GEMINI_API_KEY}"
        )
        print(f"  モデル試行: {model}")
        for attempt in range(3):
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as res:
                    data = json.loads(res.read().decode())
                print(f"  成功: {model}")
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as e:
                if e.code in (503, 429) and attempt < 2:
                    wait = 15 * (attempt + 1)
                    print(f"  HTTP {e.code} → {wait}秒後にリトライ ({attempt+1}/3)...")
                    time.sleep(wait)
                else:
                    # リトライ上限 or 404/400 → 次のモデルへ
                    print(f"  {model} 失敗(HTTP {e.code})、次のモデルへ...")
                    break
    raise RuntimeError("全モデルで失敗しました")


# ========================================
# 3. 要約テキストをパース
# ========================================
def parse_summary(text):
    keys = ["STOCK", "FED", "JOBS", "EARNINGS", "HEADLINE"]
    result = {k: "" for k in keys}
    for line in text.strip().splitlines():
        for key in keys:
            if line.startswith(f"{key}:"):
                result[key] = line[len(key)+1:].strip()
    if not result["HEADLINE"]:
        result["HEADLINE"] = "本日の米国経済まとめ"
    return result


# ========================================
# 3b. 主要ニュース2件をGeminiで要約
# ========================================
def summarize_major_news(articles):
    """主要ニュース2件を日本語で要約"""
    news_text = "\n".join([
        f"- [{a['source']}] {a['title']}: {a['description']}"
        for a in articles if a["title"]
    ])
    today_str = datetime.now(JST).strftime("%Y年%-m月%-d日")

    prompt = f"""あなたは米国・国際情勢・テクノロジーの専門アナリストです。
以下の英語ニュース記事から、本日（{today_str}）最も重要なニュースを3件選び、日本語で要約してください。

以下のカテゴリから重要度が高いものを優先してピックアップしてください：
- トランプ大統領の政策・発言・行政
- 米国内政・外交・国際情勢（米中関係など）
- AI・人工知能の最新動向（新モデル・規制・企業動向）
- 半導体・チップ産業（NVIDIA・TSMC・輸出規制など）
- 経済タブで扱わなかった重要な米国経済ニュース

出力形式（このフォーマットを厳守。他の文字を入れないこと）:
NEWS1_TITLE: （1件目の見出し、25文字以内）
NEWS1_BODY: （1件目の要約、3〜4文、具体的な内容・背景・影響を含める）
NEWS2_TITLE: （2件目の見出し、25文字以内）
NEWS2_BODY: （2件目の要約、3〜4文、具体的な内容・背景・影響を含める）
NEWS3_TITLE: （3件目の見出し、25文字以内）
NEWS3_BODY: （3件目の要約、3〜4文、具体的な内容・背景・影響を含める）

【ニュース記事】
{news_text}
"""

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }).encode("utf-8")

    models = [
        "gemini-2.5-flash-lite-preview-06-17",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
    ]
    for model in models:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models"
            f"/{model}:generateContent?key={GEMINI_API_KEY}"
        )
        for attempt in range(3):
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as res:
                    data = json.loads(res.read().decode())
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as e:
                if e.code in (503, 429) and attempt < 2:
                    time.sleep(15 * (attempt + 1))
                else:
                    break
    return "NEWS1_TITLE: 取得失敗\nNEWS1_BODY: ニュースの取得に失敗しました。\nNEWS2_TITLE: -\nNEWS2_BODY: -\nNEWS3_TITLE: -\nNEWS3_BODY: -"


def parse_major_news(text):
    keys = ["NEWS1_TITLE", "NEWS1_BODY", "NEWS2_TITLE", "NEWS2_BODY", "NEWS3_TITLE", "NEWS3_BODY"]
    result = {k: "" for k in keys}
    for line in text.strip().splitlines():
        for key in keys:
            if line.startswith(f"{key}:"):
                result[key] = line[len(key)+1:].strip()
    return result


# ========================================
# 4. 編集部スタイルHTMLを生成
# ========================================

# SVGアイコン（絵文字の代わり。currentColorでテーマ色を継承）
_ICONS = {
    "trending-up": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 17 9 11 13 15 21 6"/><polyline points="14 6 21 6 21 13"/></svg>',
    "bank": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="3" y1="21" x2="21" y2="21"/><line x1="5" y1="21" x2="5" y2="10"/><line x1="19" y1="21" x2="19" y2="10"/><line x1="12" y1="21" x2="12" y2="10"/><polygon points="12 3 21 8 3 8"/></svg>',
    "briefcase": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>',
    "bar-chart": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>',
    "newspaper": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4h13a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H7a3 3 0 0 1-3-3V4z"/><path d="M18 8h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><line x1="8" y1="8" x2="14" y2="8"/><line x1="8" y1="12" x2="14" y2="12"/><line x1="8" y1="16" x2="11" y2="16"/></svg>',
    "globe": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    "external-link": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
    "arrow-right": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>',
}


def _esc(s):
    """HTMLへの埋め込み用にエスケープ（外部APIの文字列を信用しない）"""
    return html.escape(s or "", quote=True)


def generate_html(summary, articles, major_news):
    now = datetime.now(JST)
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    wd = weekdays[now.weekday()]
    date_str = now.strftime(f"%Y年%-m月%-d日（{wd}）")
    time_str = now.strftime("%H:%M JST")

    source_items = ""
    for a in articles[:8]:
        if a["title"] and a["url"]:
            title = a["title"][:80] + ("…" if len(a["title"]) > 80 else "")
            safe_url = _esc(a["url"])
            source_items += f"""
            <li class="source-item">
              <a href="{safe_url}" target="_blank" rel="noopener noreferrer">
                <span class="source-name">{_esc(a['source'])}</span>
                <span class="source-title">{_esc(title)}</span>
                <span class="source-icon">{_ICONS['external-link']}</span>
              </a>
            </li>"""

    def section(icon, title, body):
        return f"""
    <div class="section">
      <div class="section-header">
        <span class="section-icon">{_ICONS[icon]}</span>
        <h2 class="section-title">{_esc(title)}</h2>
      </div>
      <p class="section-body">{_esc(body)}</p>
    </div>"""

    sections_html = section("trending-up", "株式市場・相場", summary["STOCK"])
    if summary["FED"].upper() != "NONE":
        sections_html += section("bank", "FRB・金融政策", summary["FED"])
    if summary["JOBS"].upper() != "NONE":
        sections_html += section("briefcase", "雇用・インフレ", summary["JOBS"])
    if summary["EARNINGS"].upper() != "NONE":
        sections_html += section("bar-chart", "企業決算", summary["EARNINGS"])

    def major_card(num, title, body):
        return f"""
      <div class="major-card">
        <span class="major-num">NEWS {num}</span>
        <h3 class="major-title">{_esc(title)}</h3>
        <p class="major-body">{_esc(body)}</p>
      </div>"""

    major_html = (
        major_card("01", major_news["NEWS1_TITLE"], major_news["NEWS1_BODY"])
        + major_card("02", major_news["NEWS2_TITLE"], major_news["NEWS2_BODY"])
        + major_card("03", major_news["NEWS3_TITLE"], major_news["NEWS3_BODY"])
    )

    js_code = """<script>
(function () {
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  function byId(id) { return document.getElementById(id); }
  function activate(tab, opts) {
    tabs.forEach(function (t) {
      var selected = t === tab;
      t.setAttribute('aria-selected', selected ? 'true' : 'false');
      t.tabIndex = selected ? 0 : -1;
      byId(t.getAttribute('aria-controls')).hidden = !selected;
    });
    if (!opts || opts.focus !== false) tab.focus();
  }
  tabs.forEach(function (tab, i) {
    tab.addEventListener('click', function () { activate(tab); });
    tab.addEventListener('keydown', function (e) {
      var idx = i;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') idx = (i + 1) % tabs.length;
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') idx = (i - 1 + tabs.length) % tabs.length;
      else return;
      e.preventDefault();
      activate(tabs[idx]);
    });
  });
  // "#major" 付きリンク（Slack投稿等から）で開いた場合は主要ニュースタブを自動表示
  document.querySelectorAll('[data-open-tab]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      e.preventDefault();
      var target = byId('tab-btn-' + el.getAttribute('data-open-tab'));
      if (target) activate(target);
    });
  });
  if (location.hash === '#major') {
    var majorTab = byId('tab-btn-major');
    if (majorTab) activate(majorTab, { focus: false });
  }
})();
</script>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>米国経済ニュース | {date_str}</title>
<meta name="description" content="{_esc(summary['HEADLINE'])} ｜ AIが自動生成する米国経済ニュースの朝刊まとめ">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,400;0,500;0,600;0,700;1,500&family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --red: #dc2626; --red-dark: #b91c1c; --red-soft: #fdeaea; --ink: #16181d; --text: #24272e;
    --muted: #5b6472; --border: #e6e8eb; --bg: #ffffff; --bg-soft: #fafafa;
    --focus: #1e40af;
    --shadow: 0 1px 2px rgba(16,24,40,0.04), 0 4px 12px rgba(16,24,40,0.05);
    --shadow-hover: 0 2px 4px rgba(16,24,40,0.06), 0 8px 20px rgba(16,24,40,0.08);
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{ background: var(--bg); font-family: 'Roboto', 'Noto Sans JP', sans-serif; color: var(--text); line-height: 1.7; font-size: 16px; }}
  a {{ color: inherit; }}
  :focus-visible {{ outline: 3px solid var(--focus); outline-offset: 2px; }}

  header {{ position: sticky; top: 0; z-index: 10; background: rgba(255,255,255,0.92); backdrop-filter: saturate(180%) blur(8px); border-bottom: 3px solid var(--red); }}
  .header-top {{ max-width: 900px; margin: 0 auto; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
  .logo {{ font-family: 'Newsreader', serif; font-size: 24px; font-weight: 700; color: var(--ink); letter-spacing: 0.01em; }}
  .logo span {{ color: var(--red); }}
  .header-date {{ font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; }}

  .main {{ max-width: 900px; margin: 0 auto; padding: 44px 24px 64px; }}

  .hero {{ position: relative; padding-left: 22px; margin-bottom: 36px; }}
  .hero::before {{ content: ""; position: absolute; left: 0; top: 2px; bottom: 2px; width: 5px; border-radius: 3px; background: linear-gradient(180deg, var(--red), var(--red-dark)); }}
  .hero-label {{ display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: var(--red); margin-bottom: 14px; }}
  .hero-label svg {{ width: 16px; height: 16px; }}
  .hero-headline {{ font-family: 'Newsreader', serif; font-size: clamp(28px, 5vw, 44px); font-weight: 700; line-height: 1.2; color: var(--ink); margin-bottom: 14px; letter-spacing: -0.01em; }}
  .hero-meta {{ font-size: 13px; color: var(--muted); }}

  /* ─── タブ ─── */
  .tablist {{ display: flex; border-bottom: 2px solid var(--border); margin-bottom: 28px; gap: 4px; }}
  .tab-btn {{
    display: flex; align-items: center; gap: 8px;
    padding: 12px 20px; min-height: 44px; font-size: 15px; font-weight: 500;
    font-family: 'Roboto', 'Noto Sans JP', sans-serif;
    background: none; border: none; cursor: pointer;
    color: var(--muted); border-bottom: 3px solid transparent;
    margin-bottom: -2px; transition: color 0.2s, border-color 0.2s;
  }}
  .tab-btn svg {{ width: 18px; height: 18px; flex-shrink: 0; }}
  .tab-btn:hover {{ color: var(--ink); }}
  .tab-btn[aria-selected="true"] {{ color: var(--red); border-bottom-color: var(--red); font-weight: 700; }}

  .sections {{ display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-bottom: 24px; background: var(--bg); box-shadow: var(--shadow); }}
  .section {{ padding: 30px 30px; border-top: 1px solid var(--border); transition: background 0.2s; }}
  .section:hover {{ background: var(--bg-soft); }}
  .section:first-child {{ border-top: none; }}
  .section-header {{ display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }}
  .section-icon {{ display: flex; align-items: center; justify-content: center; width: 38px; height: 38px; border-radius: 50%; background: var(--red-soft); color: var(--red); flex-shrink: 0; }}
  .section-icon svg {{ width: 20px; height: 20px; }}
  .section-title {{ font-family: 'Newsreader', serif; font-size: 18.5px; font-weight: 600; color: var(--ink); }}
  .section-body {{ font-size: 15.5px; line-height: 1.9; color: var(--text); }}

  /* ─── 主要ニュースへの誘導 ─── */
  .teaser {{
    display: flex; align-items: center; gap: 16px; justify-content: space-between;
    background: var(--ink); color: #fff; border-radius: 10px; padding: 20px 24px;
    margin-bottom: 24px; box-shadow: var(--shadow);
  }}
  .teaser-text {{ display: flex; align-items: center; gap: 12px; font-size: 14.5px; }}
  .teaser-text svg {{ width: 20px; height: 20px; color: var(--red); flex-shrink: 0; }}
  .teaser-text strong {{ font-weight: 700; }}
  .teaser-link {{
    display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0;
    background: var(--red); color: #fff; text-decoration: none;
    font-size: 13.5px; font-weight: 700; padding: 9px 16px; border-radius: 6px;
    min-height: 44px; cursor: pointer; transition: background 0.2s;
  }}
  .teaser-link:hover, .teaser-link:focus-visible {{ background: var(--red-dark); }}
  .teaser-link svg {{ width: 15px; height: 15px; }}

  .sources {{ background: var(--bg-soft); border: 1px solid var(--border); border-radius: 10px; padding: 24px 28px; margin-bottom: 8px; box-shadow: var(--shadow); }}
  .sources-title {{ display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: var(--muted); margin-bottom: 14px; }}
  .sources-title svg {{ width: 16px; height: 16px; }}
  .source-list {{ list-style: none; }}
  .source-item a {{ display: flex; gap: 12px; align-items: center; padding: 12px 8px; border-bottom: 1px solid var(--border); text-decoration: none; color: inherit; transition: color 0.15s, background 0.15s; border-radius: 6px; }}
  .source-item:last-child a {{ border-bottom: none; }}
  .source-item a:hover, .source-item a:focus-visible {{ color: var(--red); background: rgba(220,38,38,0.05); }}
  .source-item a:hover .source-title, .source-item a:focus-visible .source-title {{ color: var(--red); }}
  .source-name {{ font-size: 11px; font-weight: 700; color: var(--red); white-space: nowrap; min-width: 96px; background: var(--red-soft); padding: 3px 8px; border-radius: 4px; text-align: center; }}
  .source-title {{ font-size: 13.5px; color: var(--muted); transition: color 0.15s; flex: 1; }}
  .source-icon {{ width: 15px; height: 15px; color: var(--muted); flex-shrink: 0; opacity: 0.7; }}
  .source-icon svg {{ width: 100%; height: 100%; }}

  /* ─── 主要ニュースカード ─── */
  .major-intro {{ font-size: 13.5px; color: var(--muted); margin-bottom: 18px; }}
  .major-list {{ display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-bottom: 8px; background: var(--bg); box-shadow: var(--shadow); }}
  .major-card {{ border-top: 1px solid var(--border); padding: 30px; transition: background 0.2s; }}
  .major-card:hover {{ background: var(--bg-soft); }}
  .major-card:first-child {{ border-top: none; }}
  .major-num {{ display: inline-block; background: var(--red); color: #fff; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; padding: 4px 10px; border-radius: 4px; margin-bottom: 14px; }}
  .major-title {{ font-family: 'Newsreader', serif; font-size: 19.5px; font-weight: 600; color: var(--ink); margin-bottom: 10px; line-height: 1.4; }}
  .major-body {{ font-size: 15.5px; line-height: 1.9; color: var(--text); }}

  footer {{ background: var(--ink); color: #9aa1ac; text-align: center; font-size: 12.5px; padding: 22px; border-top: 3px solid var(--red); }}

  @media (max-width: 600px) {{
    .main {{ padding: 28px 16px 48px; }}
    .section, .major-card, .sources {{ padding: 20px 18px; }}
    .tab-btn {{ padding: 10px 14px; font-size: 14px; }}
    .teaser {{ flex-direction: column; align-items: flex-start; }}
    .teaser-link {{ width: 100%; justify-content: center; }}
  }}

  @media (prefers-reduced-motion: reduce) {{
    * {{ transition: none !important; }}
  }}
</style>
</head>
<body>
<header>
  <div class="header-top">
    <div class="logo">ECONO<span>BOT</span></div>
    <div class="header-date">{date_str} {time_str}</div>
  </div>
</header>
<main class="main" id="main">
  <div class="hero">
    <div class="hero-label">{_ICONS['globe']}<span>Daily US Economy Briefing</span></div>
    <h1 class="hero-headline">{_esc(summary['HEADLINE'])}</h1>
    <div class="hero-meta">自動生成ニュースまとめ ｜ Powered by Gemini + NewsAPI</div>
  </div>

  <div class="tablist" role="tablist" aria-label="ニュースカテゴリ">
    <button id="tab-btn-economy" class="tab-btn" role="tab" aria-selected="true" aria-controls="tab-economy" tabindex="0">{_ICONS['trending-up']}<span>経済ニュース</span></button>
    <button id="tab-btn-major" class="tab-btn" role="tab" aria-selected="false" aria-controls="tab-major" tabindex="-1">{_ICONS['newspaper']}<span>主要ニュース</span></button>
  </div>

  <div id="tab-economy" role="tabpanel" aria-labelledby="tab-btn-economy">
    <div class="sections">{sections_html}
    </div>
    <div class="teaser">
      <div class="teaser-text">{_ICONS['newspaper']}<span>本日の主要ニュース：<strong>{_esc(major_news['NEWS1_TITLE'])}</strong> ほか2本</span></div>
      <a href="#major" class="teaser-link" data-open-tab="major">読む{_ICONS['arrow-right']}</a>
    </div>
    <div class="sources">
      <div class="sources-title">{_ICONS['newspaper']}<span>参照ニュースソース</span></div>
      <ul class="source-list">{source_items}
      </ul>
    </div>
  </div>

  <div id="tab-major" role="tabpanel" aria-labelledby="tab-btn-major" hidden>
    <p class="major-intro">トランプ政権・国際情勢・AI/半導体など、経済以外の主要ニュースをピックアップ</p>
    <div class="major-list">{major_html}
    </div>
  </div>
</main>
<footer>
  <p>EconoBot ｜ 本コンテンツはAIが自動生成したものです。投資判断の根拠にしないでください。</p>
</footer>
{js_code}
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
# 6. SlackにリンクURL付きで投稿
# ========================================
def post_to_slack(page_url, summary, major_news):
    now = datetime.now(JST)
    weekdays = ["月","火","水","木","金","土","日"]
    wd = weekdays[now.weekday()]
    date_str = now.strftime(f"%Y年%-m月%-d日（{wd}）")

    def trim(s): return s[:60] + "…" if len(s) > 60 else s

    lines = []
    lines.append(f"*🇺🇸 米国経済ニュース 朝刊｜{date_str}*")
    lines.append(f"*📌 {summary['HEADLINE']}*\n")
    lines.append(f"📈 *株式*　{trim(summary['STOCK'])}")
    if summary['FED'].upper() != 'NONE':
        lines.append(f"🏦 *FRB*　{trim(summary['FED'])}")
    if summary['JOBS'].upper() != 'NONE':
        lines.append(f"💼 *雇用*　{trim(summary['JOBS'])}")
    if summary['EARNINGS'].upper() != 'NONE':
        lines.append(f"💹 *決算*　{trim(summary['EARNINGS'])}")
    # 主要ニュースタブが読まれずに埋もれないよう、見出しをここでも露出させる
    if major_news.get('NEWS1_TITLE'):
        lines.append(f"\n🗞️ *主要ニュースも公開中*　{major_news['NEWS1_TITLE']} ほか2本")
    lines.append(f"\n🔗 *詳細レポートを読む* → {page_url}")
    lines.append(f"🔗 *主要ニュースを直接読む* → {page_url}#major")
    text = "\n".join(lines)

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        print(f"  Slack投稿完了: {res.status}")


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
    try:
        print("📰 経済ニュース取得中...")
        articles = fetch_news()
        print(f"  {len(articles)}件取得")

        print("📰 主要ニュース取得中...")
        major_articles = fetch_major_news()
        print(f"  {len(major_articles)}件取得")

        print("🤖 Geminiで経済ニュース要約中...")
        raw = summarize_with_gemini(articles)
        summary = parse_summary(raw)
        print(f"  見出し: {summary['HEADLINE']}")

        print("🤖 Geminiで主要ニュース要約中...")
        major_raw = summarize_major_news(major_articles)
        major_news = parse_major_news(major_raw)
        print(f"  主要1: {major_news['NEWS1_TITLE']}")
        print(f"  主要2: {major_news['NEWS2_TITLE']}")
        print(f"  主要3: {major_news['NEWS3_TITLE']}")

        print("🎨 HTMLページ生成中...")
        page_html = generate_html(summary, articles, major_news)

        print("🚀 GitHub Pagesに公開中...")
        page_url = publish_to_github_pages(page_html)

        print("📤 Slackに投稿中...")
        post_to_slack(page_url, summary, major_news)

        print("✅ 完了！")
    except Exception as e:
        print(f"❌ エラー発生: {e}")
        notify_failure(stage=type(e).__name__, error=str(e))
        raise


if __name__ == "__main__":
    main()
