"""時計(2026-11-27): GitHubのscheduleに頼らず、決めた時刻にEconoBotを起動する。

GitHubのscheduleは後回しにされ、11/27は7〜9時間以上遅れ、夕方の起動は1回も来なかった。
手動実行(workflow_dispatch)の起動は数秒で始まるので、この時計のジョブがGitHubの中で目標の時刻まで待ち、
時刻になったら econobot.yml を slot(morning / evening)付きで起動する。
ジョブは6時間で打ち切られるため、上限の前に次の時計を起動して引き継ぐ(リレー)。

・朝:   JST 7:00 に起動 → econobot が 7:25 に取得、8:00 に公開・投稿
・夕方: JST 17:15 に起動 → econobot が 17:30 に学習アプリのデータを作り直す
・始まった時点で目標の時刻を過ぎていて、その日の分がまだなら(朝は12:00まで、夕方は23:30まで)すぐ起動する(取り戻し)
・二重に起動しても、econobot が記録(state/last_posted.txt・state/last_learn.txt)を見て何もせず終わる
・リレーが切れた時のため、clock.yml の schedule(数時間おき)が時計を起こし直す。時計が動いていれば何もせず終わる
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
SLOTS = [  # (名前, 起動の時刻, 取り戻しの締め切り)
    ("morning", (7, 0), (12, 0)),
    ("evening", (17, 15), (23, 30)),
]
SLOT_LABEL = {"morning": "朝(7:25取得・8:00投稿)", "evening": "夕方(17:30の更新)"}
BUDGET = 5 * 3600 + 40 * 60   # 1回の時計が待つ長さの上限(ジョブの上限6時間より短く)
API = "https://api.github.com"


def now_jst():
    return datetime.now(JST)


def _at(day, hm):
    return datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=JST)


def next_fire(now):
    """now より後で最も近い (時刻, slot)"""
    cands = []
    for d in (now.date(), now.date() + timedelta(days=1)):
        for name, hm, _ in SLOTS:
            t = _at(d, hm)
            if t > now:
                cands.append((t, name))
    return min(cands)


def missed(now):
    """目標の時刻を過ぎて締め切り前の slot(取り戻しの候補)"""
    return [name for name, hm, until in SLOTS if _at(now.date(), hm) <= now < _at(now.date(), until)]


def plan(now, budget=BUDGET):
    """(すぐ起動する slot の一覧, 次に待つ時刻, その時刻の slot または None=引き継ぎ)"""
    t, name = next_fire(now)
    end = now + timedelta(seconds=budget)
    if t <= end:
        return missed(now), t, name
    return missed(now), end, None


# ---------- GitHub API ----------
def _req(method, path, body=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    req = urllib.request.Request(f"{API}/repos/{repo}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                          "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def dispatch(workflow, inputs, tries=5):
    ref = os.environ.get("GITHUB_REF_NAME") or "main"
    for i in range(tries):
        try:
            _req("POST", f"/actions/workflows/{workflow}/dispatches", {"ref": ref, "inputs": inputs})
            print(f"  {now_jst():%H:%M:%S} {workflow} を起動した {inputs}")
            return True
        except Exception as e:
            print(f"  [WARN] {workflow} の起動に失敗({i + 1}回目): {e}")
            time.sleep(15 * (i + 1))
    return False


def other_clocks(own_id):
    """自分以外の、動いている・順番待ちの時計の run(作られた時刻つき)"""
    out = []
    for st in ("in_progress", "queued"):
        try:
            res = _req("GET", f"/actions/workflows/clock.yml/runs?status={st}&per_page=20")
        except Exception as e:
            print(f"  [WARN] 時計の一覧を読めない: {e}")
            continue
        out += [r for r in res.get("workflow_runs", []) if str(r.get("id")) != str(own_id)]
    return out


def fire(name):
    print(f"⏰ {SLOT_LABEL[name]} を起動する")
    if not dispatch("econobot.yml", {"slot": name}):
        print(f"❌ {SLOT_LABEL[name]} を起動できなかった")
        return False
    return True


def main():
    own = os.environ.get("GITHUB_RUN_ID", "")
    relay = os.environ.get("RELAY", "").strip().lower() == "true"
    now = now_jst()
    print(f"🕰 時計: JST {now:%Y-%m-%d %H:%M:%S}({'リレーで引き継ぎ' if relay else '起こし直し・手動'})")
    if not relay:
        others = other_clocks(own)
        if others:
            print(f"  ほかの時計が動いている({[r['id'] for r in others]})ため、何もせず終わる")
            return 0
    ok = True
    now_slots, until, name = plan(now)
    if not relay:
        for s in now_slots:   # 取り戻し(econobot が記録を見るので、済んでいれば何もしない)。リレーの時計は前の時計が起動済み
            ok &= fire(s)
    left = (until - now_jst()).total_seconds()
    print(f"  次: {until:%m-%d %H:%M} {SLOT_LABEL.get(name, '時計の引き継ぎ')}(あと{max(left, 0) / 60:.0f}分待つ)")
    while True:
        left = (until - now_jst()).total_seconds()
        if left <= 0:
            break
        time.sleep(min(left, 60))
    if name:
        ok &= fire(name)
    # 引き継ぎ。より新しい時計が動いていれば(二重になった時)、自分のリレーはここで終える
    newer = [r for r in other_clocks(own) if int(r.get("id") or 0) > int(own)] if own else []
    if newer:
        print(f"  より新しい時計が動いている({[r['id'] for r in newer]})ため、引き継がずに終わる")
    elif not dispatch("clock.yml", {"relay": "true"}):
        print("❌ 次の時計を起動できなかった(clock.yml の schedule が起こし直す)")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
