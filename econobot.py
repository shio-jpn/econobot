"""
EconoBot - 米国経済ニュース自動要約
BBCスタイルHTMLページを生成 → GitHub Pages公開 → SlackにURLを投稿
"""

import os
import json
import time
import base64
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
    queries = [
        "US stock market S&P Nasdaq Dow",
        "Federal Reserve interest rate inflation policy",
        "US jobs unemployment CPI inflation",
        "corporate earnings revenue profit quarterly",
    ]
    articles = []
    for query in queries:
        params = urllib.parse.urlencode({
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 3,
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
            })
    return articles


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
以下の英語ニュース記事を読み、本日（{today_str}）の米国経済を日本語で要約してください。
数値・指標・企業名・変動率があれば必ず含めてください。

【企業決算（EARNINGS）のルール】
- NVDA・GOOGL・AAPL・MSFT・AMZN・META・TSLA・JPM・BAC・WMT など主要大手企業の決算発表が
  本日のニュースに含まれる場合のみ、3〜4文で具体的に要約する。
- 上記に該当する決算ニュースがない場合は、必ず EARNINGS: NONE と出力する。

【決算なしの場合のルール】
- EARNINGSがNONEの場合、STOCK・FED・JOBSをそれぞれ5〜6文と詳しく書く。
- 具体的な数値（指数の値・変動率・金利・雇用者数など）を必ず含める。
- 背景・要因・今後の見通しまで掘り下げて書く。

【決算ありの場合のルール】
- STOCK・FED・JOBSはそれぞれ3〜4文でまとめる。
- EARNINGSは決算企業名・売上高・EPS・市場予想との比較・株価反応を含める。

出力形式（このフォーマットを厳守。他の文字を入れないこと）:
STOCK: （株式市場・相場の要約）
FED: （FRB・金融政策の要約）
JOBS: （雇用・インフレの要約）
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
# 4. BBCスタイルHTMLを生成
# ========================================
def generate_html(summary, articles):
    now = datetime.now(JST)
    weekdays = ["月","火","水","木","金","土","日"]
    wd = weekdays[now.weekday()]
    date_str = now.strftime(f"%Y年%-m月%-d日（{wd}）")
    time_str = now.strftime("%H:%M JST")

    source_items = ""
    for a in articles[:8]:
        if a["title"] and a["url"]:
            title = a["title"][:80] + ("…" if len(a["title"]) > 80 else "")
            source_items += f"""
            <li class="source-item">
              <a href="{a['url']}" target="_blank" rel="noopener">
                <span class="source-name">{a['source']}</span>
                <span class="source-title">{title}</span>
              </a>
            </li>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>米国経済ニュース | {date_str}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght@400;600;700&family=Noto+Sans+JP:wght@400;500&family=Playfair+Display:wght@700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --red: #bb1919; --dark: #0d0d0d; --text: #1f1f1f;
    --muted: #555; --border: #e0e0e0; --bg: #f9f7f4; --white: #ffffff;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); font-family: 'Noto Sans JP', sans-serif; color: var(--text); line-height: 1.7; }}
  header {{ background: var(--dark); border-bottom: 3px solid var(--red); }}
  .header-top {{ max-width: 900px; margin: 0 auto; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; }}
  .logo {{ font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 800; color: #fff; letter-spacing: 0.04em; }}
  .logo span {{ color: var(--red); }}
  .header-date {{ font-size: 12px; color: #aaa; }}
  .main {{ max-width: 900px; margin: 0 auto; padding: 40px 24px 60px; }}
  .hero {{ border-left: 5px solid var(--red); padding-left: 20px; margin-bottom: 36px; animation: fadeUp 0.5s ease both; }}
  .hero-label {{ font-size: 11px; font-weight: 500; letter-spacing: 2px; text-transform: uppercase; color: var(--red); margin-bottom: 10px; }}
  .hero-headline {{ font-family: 'Playfair Display', serif; font-size: clamp(26px, 4vw, 38px); font-weight: 800; line-height: 1.25; color: var(--dark); margin-bottom: 10px; }}
  .hero-meta {{ font-size: 13px; color: var(--muted); }}
  .sections {{ display: grid; gap: 2px; margin-bottom: 40px; }}
  .section {{ background: var(--white); padding: 28px 32px; border-top: 1px solid var(--border); animation: fadeUp 0.5s ease both; transition: background 0.2s; }}
  .section:hover {{ background: #fafafa; }}
  .section:first-child {{ border-top: none; }}
  .section-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }}
  .section-icon {{ font-size: 22px; }}
  .section-title {{ font-family: 'Noto Serif JP', serif; font-size: 17px; font-weight: 700; color: var(--dark); border-bottom: 2px solid var(--red); padding-bottom: 2px; }}
  .section-body {{ font-size: 15px; line-height: 1.85; }}
  .sources {{ background: var(--white); border: 1px solid var(--border); padding: 24px 28px; margin-bottom: 32px; animation: fadeUp 0.6s ease both; }}
  .sources-title {{ font-size: 12px; font-weight: 500; letter-spacing: 2px; text-transform: uppercase; color: var(--muted); margin-bottom: 14px; }}
  .source-list {{ list-style: none; }}
  .source-item a {{ display: flex; gap: 12px; align-items: baseline; padding: 10px 0; border-bottom: 1px solid var(--border); text-decoration: none; color: inherit; transition: color 0.15s; }}
  .source-item:last-child a {{ border-bottom: none; }}
  .source-item a:hover .source-title {{ color: var(--red); }}
  .source-name {{ font-size: 11px; font-weight: 500; color: var(--red); white-space: nowrap; min-width: 90px; }}
  .source-title {{ font-size: 13px; color: var(--muted); transition: color 0.15s; }}
  footer {{ background: var(--dark); color: #666; text-align: center; font-size: 12px; padding: 20px; border-top: 3px solid var(--red); }}
  @keyframes fadeUp {{ from {{ opacity: 0; transform: translateY(12px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  @media (max-width: 600px) {{ .main {{ padding: 24px 16px 48px; }} .section {{ padding: 20px 18px; }} }}
</style>
</head>
<body>
<header>
  <div class="header-top">
    <div class="logo">ECONO<span>BOT</span></div>
    <div class="header-date">{date_str} {time_str}</div>
  </div>
</header>
<main class="main">
  <div class="hero">
    <div class="hero-label">🇺🇸 Daily US Economy Briefing</div>
    <h1 class="hero-headline">{summary['HEADLINE']}</h1>
    <div class="hero-meta">自動生成ニュースまとめ ｜ Powered by Gemini + NewsAPI</div>
  </div>
  <div class="sections">
    <div class="section">
      <div class="section-header"><span class="section-icon">📈</span><span class="section-title">株式市場・相場</span></div>
      <p class="section-body">{summary['STOCK']}</p>
    </div>
    <div class="section">
      <div class="section-header"><span class="section-icon">🏦</span><span class="section-title">FRB・金融政策</span></div>
      <p class="section-body">{summary['FED']}</p>
    </div>
    <div class="section">
      <div class="section-header"><span class="section-icon">💼</span><span class="section-title">雇用・インフレ</span></div>
      <p class="section-body">{summary['JOBS']}</p>
    </div>
    {f'''<div class="section">
      <div class="section-header"><span class="section-icon">💹</span><span class="section-title">企業決算</span></div>
      <p class="section-body">{summary['EARNINGS']}</p>
    </div>''' if summary['EARNINGS'].upper() != 'NONE' else ''}
  </div>
  <div class="sources">
    <div class="sources-title">📰 参照ニュースソース</div>
    <ul class="source-list">{source_items}</ul>
  </div>
</main>
<footer>
  <p>🤖 EconoBot ｜ 本コンテンツはAIが自動生成したものです。投資判断の根拠にしないでください。</p>
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
# 6. SlackにリンクURL付きで投稿
# ========================================
def post_to_slack(page_url, summary):
    now = datetime.now(JST)
    weekdays = ["月","火","水","木","金","土","日"]
    wd = weekdays[now.weekday()]
    date_str = now.strftime(f"%Y年%-m月%-d日（{wd}）")

    def trim(s): return s[:60] + "…" if len(s) > 60 else s

    text = (
        f"*🇺🇸 米国経済ニュース 朝刊｜{date_str}*\n"
        f"*📌 {summary['HEADLINE']}*\n\n"
        f"📈 *株式*　{trim(summary['STOCK'])}\n"
        f"🏦 *FRB*　{trim(summary['FED'])}\n"
        f"💼 *雇用*　{trim(summary['JOBS'])}\n"
        (f"💹 *決算*　{trim(summary['EARNINGS'])}\n\n" if summary['EARNINGS'].upper() != 'NONE' else "")
        f"🔗 *詳細レポートを読む* → {page_url}"
    )

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
def main():
    print("📰 ニュース取得中...")
    articles = fetch_news()
    print(f"  {len(articles)}件取得")

    print("🤖 Geminiで要約中...")
    raw = summarize_with_gemini(articles)
    summary = parse_summary(raw)
    print(f"  見出し: {summary['HEADLINE']}")

    print("🎨 HTMLページ生成中...")
    html = generate_html(summary, articles)

    print("🚀 GitHub Pagesに公開中...")
    page_url = publish_to_github_pages(html)

    print("📤 Slackに投稿中...")
    post_to_slack(page_url, summary)

    print("✅ 完了！")


if __name__ == "__main__":
    main()
