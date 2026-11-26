"""claude.ai に公開している株トレ道場(Artifact)を、毎朝の最新データで作り直す。

使い方:
    python3 learn/tools/refresh_artifact.py <出力先のフォルダ>

出力:
    <出力先>/kabu-dojo.html  Artifact として公開する1枚のページ(learn/index.html の head と body から作る)
    <出力先>/market.json     FRED から取得した市場データ(毎朝のBotと同じ build_market_json を使う)

公開は Artifact の機能で行う(このスクリプトはファイルを作るだけ)。
データが取れなかった時は終了コード 1 で止まり、前の日の公開内容はそのまま残る。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEARN = os.path.dirname(HERE)
REPO = os.path.dirname(LEARN)
sys.path.insert(0, REPO)

import econobot as eb  # noqa: E402

MIN_SERIES = 8  # これより少ない日は、取得に問題があるとみなして公開し直さない


def build_page(index_html):
    """Artifact の公開形式: 文書の骨組みは公開時に付くので、<title> から </style> までと body の中身だけを使う"""
    head = re.search(r"<title>.*?</style>", index_html, re.S).group(0)
    head = re.sub(r'<meta name="description"[^>]*>\n|<link rel="icon"[^>]*>\n', "", head)
    body = re.search(r"<body>(.*)</body>", index_html, re.S).group(1)
    return head + body


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(LEARN, "index.html"), encoding="utf-8") as f:
        page = build_page(f.read())
    data = eb.build_market_json({"ok": False})
    n = len(data["series"])
    latest = max((s["rows"][-1][0] for s in data["series"].values()), default="-")
    if n < MIN_SERIES:
        print(f"取得できた系列が{n}件しかないため、公開し直さない(前日の内容を残す)")
        return 1
    with open(os.path.join(out_dir, "market.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out_dir, "kabu-dojo.html"), "w", encoding="utf-8") as f:
        f.write(page)
    print(f"OK 系列{n}件 最新の日付 {latest} 更新 {data['updated']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
