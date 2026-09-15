#!/usr/bin/env python3
"""디스코드 알림 — 수집이 죽었을 때만 말한다.

두 가지를 지킨다.
  1. 한 번 삐끗한 것으로 울리지 않는다(네트워크는 가끔 끊긴다).
  2. 고칠 때까지 계속 울리지 않는다. 상태가 바뀔 때 한 번씩만 보낸다.

웹훅 URL 은 환경변수(DISCORD_WEBHOOK)로만 받는다. 이 저장소는 공개다.

보내는 내용은 "무엇이 실패했는지"까지다 — 종목코드·계열명·건수뿐이고,
보유 수량·평가액·순자산은 이 프로세스에 들어오지도 않는다. 앞으로도 넣지 말 것.
"""
import json
import os
import pathlib
import urllib.error
import urllib.request

FAIL_THRESHOLD = 3          # 연속 3회(하루 두 번 돌면 약 하루 반) 실패하면 알린다
MAX_LISTED = 20             # 디스코드 메시지 한도 2000자 — 다 나열하지 않는다
STATE = pathlib.Path(__file__).resolve().parent / "notify_state.json"


def decide(prev_fails, cur_fails, notified, threshold=FAIL_THRESHOLD):
    """이번 실행 결과로 무엇을 할지 — "alert" | "recovered" | "quiet"."""
    if cur_fails == 0:
        return "recovered" if notified else "quiet"
    if notified:
        return "quiet"                      # 이미 알렸다. 고칠 때까지 반복하지 않는다
    return "alert" if cur_fails >= threshold else "quiet"


def build_message(verdict, ctx):
    """알림 본문. 보낼 것이 없으면 None."""
    job = ctx.get("job", "시세 수집")
    if verdict == "recovered":
        return f"✅ **{job} 복구** — 정상 수집됐습니다."
    if verdict != "alert":
        return None

    failed = list(ctx.get("failed") or [])
    head = failed[:MAX_LISTED]
    rest = len(failed) - len(head)
    listed = ", ".join(head) + (f" 외 {rest}건" if rest > 0 else "")
    lines = [
        f"⚠️ **{job} 실패** — 연속 {ctx.get('streak', 0)}회",
        f"실패 {len(failed)}/{ctx.get('total', len(failed))}종",
    ]
    if listed:
        lines.append(listed)
    return "\n".join(lines)[:1900]


def load_state(job, path=STATE):
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(job, {})
    except (OSError, ValueError):
        return {}


def save_state(job, fails, notified, path=STATE):
    try:
        all_state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        all_state = {}
    all_state[job] = {"fails": fails, "notified": notified}
    path.write_text(json.dumps(all_state, ensure_ascii=False, indent=2), encoding="utf-8")


def post(text, webhook=None):
    """디스코드로 보낸다. URL 이 없으면 조용히 건너뛴다(로컬 실행 대비)."""
    url = webhook or os.environ.get("DISCORD_WEBHOOK", "")
    if not url:
        print("[notify] DISCORD_WEBHOOK 없음 — 보내지 않음")
        return False
    body = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except urllib.error.URLError as e:
        print(f"[notify] 전송 실패: {e}")
        return False


def report(job, failed, total, path=STATE, webhook=None, threshold=FAIL_THRESHOLD):
    """수집 결과를 받아 판단하고, 필요할 때만 보낸다. 실제로 보냈으면 True.

    전송이 실패하면 '알렸다'로 기록하지 않는다 — 디스코드가 잠깐 죽은 사이에
    표시만 남기면 그 장애는 영영 알림을 받지 못한다.
    """
    prev = load_state(job, path)
    prev_fails = int(prev.get("fails", 0))
    notified = bool(prev.get("notified", False))
    streak = prev_fails + 1 if failed else 0

    verdict = decide(prev_fails, streak, notified, threshold)
    msg = build_message(verdict, {"job": job, "failed": failed,
                                  "total": total, "streak": streak})
    sent = post(msg, webhook) if msg else False

    if verdict == "alert":
        notified = sent
    elif verdict == "recovered" or streak == 0:
        notified = False

    save_state(job, streak, notified, path)
    return sent


def cli(argv=None):
    """셸에서 부르는 통로. run.sh 의 push 실패처럼 파이썬 밖 실패도 같은 규칙을 탄다."""
    import argparse
    ap = argparse.ArgumentParser(description="디스코드 알림")
    ap.add_argument("--test", action="store_true", help="연결 확인용 시험 메시지 발송")
    ap.add_argument("--job", default="시세 수집", help="상태를 따로 기록할 작업 이름")
    ap.add_argument("--failed", nargs="*", default=[], help="실패 항목(없으면 정상으로 본다)")
    ap.add_argument("--total", type=int, default=0)
    ap.add_argument("--threshold", type=int, default=FAIL_THRESHOLD)
    ap.add_argument("--state", default=str(STATE))
    a = ap.parse_args(argv)

    if a.test:
        ok = post("🔔 개인 대시보드 알림 시험 — 이 메시지가 보이면 연결됐습니다.")
        return 0 if ok else 1

    report(a.job, a.failed, a.total or len(a.failed),
           path=pathlib.Path(a.state), threshold=a.threshold)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(cli())
