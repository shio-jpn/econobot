"""
EconoBot - 米国経済ニュース自動要約 & Slack投稿スクリプト
----------------------------------------
使用API:
  - Google Gemini API（ニュース要約）
  - Slack Incoming Webhook（投稿）
  - NewsAPI（ニュース取得）※無料プラン対応
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# ========================================
# 設定（GitHub Secretsから環境変数で読み込み）
# ========================================
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
NEWS_API_KEY = os.environ["NEWS_API_KEY"]  # https://newsapi.org で無料取得


# ========================================
# 1. NewsAPIでニュースを取得
# ========================================
def fetch_news():
    """株式・FRB・雇用・企業決算に関する米国経済ニュースを取得"""
    queries = [
        "US stock market",
        "Federal Reserve interest rate",
        "US inflation unemployment jobs",
        "corporate earnings results",
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
            })

    return articles


# ========================================
# 2. Gemini APIでニュースを要約
# ========================================
def summarize_with_gemini(articles):
    """Gemini APIを使って4カテゴリに分けて日本語要約"""
    news_text = "\n".join([
        f"- [{a['source']}] {a['title']}: {a['description']}"
        for a in articles if a['title']
    ])

    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y年%-m月%-d日")

    prompt = f"""
あなたは米国経済の専門アナリストです。
以下の英語ニュース記事を読み、本日（{today}）の米国経済を日本語で要約してください。

必ず以下の4つのカテゴリに分けて、それぞれ2〜3文で簡潔にまとめてください。
数値・指標があれば必ず含めてください。

【カテゴリ】
1. 📈 株式市場・相場
2. 🏦 FRB・金融政策
3. 💼 雇用・インフレ
4. 💹 企業決算

出力形式（このフォーマットを厳守）:
STOCK: （株式市場の要約）
FED: （FRB・金融政策の要約）
JOBS: （雇用・インフレの要約）
EARNINGS: （企業決算の要約）

【ニュース記事】
{news_text}
"""

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}]
    }).encode("utf-8")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models"
        f"/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        data = json.loads(res.read().decode())

    return data["candidates"][0]["content"]["parts"][0]["text"]


# ========================================
# 3. 要約テキストをパース
# ========================================
def parse_summary(text):
    """Geminiの出力をカテゴリ別に分割"""
    result = {"STOCK": "", "FED": "", "JOBS": "", "EARNINGS": ""}
    for line in text.strip().splitlines():
        for key in result:
            if line.startswith(f"{key}:"):
                result[key] = line[len(key)+1:].strip()
    return result


# ========================================
# 4. Slackに投稿
# ========================================
def post_to_slack(summary):
    """リッチフォーマットでSlackに投稿"""
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y年%-m月%-d日（%a）")

    # 曜日を日本語に変換
    weekdays = {"Mon":"月","Tue":"火","Wed":"水","Thu":"木","Fri":"金","Sat":"土","Sun":"日"}
    for en, ja in weekdays.items():
        today = today.replace(en, ja)

    text = (
        f"*🇺🇸 米国経済ニュース 朝刊｜{today}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*📈 株式市場・相場*\n{summary['STOCK']}\n\n"
        f"*🏦 FRB・金融政策*\n{summary['FED']}\n\n"
        f"*💼 雇用・インフレ*\n{summary['JOBS']}\n\n"
        f"*💹 企業決算*\n{summary['EARNINGS']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_🤖 Powered by EconoBot（Gemini + NewsAPI）_"
    )

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        print(f"Slack投稿完了: {res.status}")


# ========================================
# メイン処理
# ========================================
def main():
    print("📰 ニュース取得中...")
    articles = fetch_news()
    print(f"  {len(articles)}件取得")

    print("🤖 Geminiで要約中...")
    raw_summary = summarize_with_gemini(articles)
    summary = parse_summary(raw_summary)

    print("📤 Slackに投稿中...")
    post_to_slack(summary)
    print("✅ 完了！")


if __name__ == "__main__":
    main()
