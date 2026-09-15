#!/usr/bin/env bash
# VPS 크론이 부르는 진입점. 수집 → prices.json 갱신 → 공개 레포에 push.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."

# 웹훅 URL 은 공개 저장소 밖(~/.mydash_env)에서만 온다.
[ -f "$HOME/.mydash_env" ] && . "$HOME/.mydash_env"
export DISCORD_WEBHOOK="${DISCORD_WEBHOOK:-}"

# 스크립트가 중간에 죽으면(대개 git push 실패) 조용히 끝난다 — 두 번 겪었다.
# 종료 코드가 0이 아니면 알린다. push 는 막히면 데이터가 아예 안 올라가므로 한 번만 실패해도 알린다.
fail_line=""
on_exit() {
  rc=$?
  if [ "$rc" -ne 0 ]; then
    python3 "$HERE/notify.py" --job "시세 반영" \
      --failed "${fail_line:-종료코드 $rc}" --threshold 1 || true
  else
    python3 "$HERE/notify.py" --job "시세 반영" --threshold 1 || true
  fi
}
trap on_exit EXIT

git pull --ff-only --quiet origin main

python3 collector/collect.py || echo "[warn] 일부 종목 수집 실패 — 직전 값 유지"

# 먼저 스테이징하고 인덱스를 본다.
# `git diff data/` 는 추적되지 않은 새 파일(연도별 이력 등)을 보지 못한다.
# 파일을 하나씩 적으면 새 출력이 생길 때마다 빠뜨린다(이력·전쟁 파일에서 실제로 겪음).
# 디렉터리 단위로 올리고 인덱스로 판정한다.
git add data/
if git diff --cached --quiet; then
  echo "변경 없음"
  exit 0
fi
git -c user.name="mydash-collector" -c user.email="mydash-bot@users.noreply.github.com" \
    commit -q -m "chore: 시세 갱신 $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')"
fail_line="git push"
git push -q origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  fail_line="push 후 origin/main 불일치"
  exit 1
fi
fail_line=""
echo "push 완료"
