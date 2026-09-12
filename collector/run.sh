#!/usr/bin/env bash
# VPS 크론이 부르는 진입점. 수집 → prices.json 갱신 → 공개 레포에 push.
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only --quiet origin main

python3 collector/collect.py || echo "[warn] 일부 종목 수집 실패 — 직전 값 유지"

# 먼저 스테이징하고 인덱스를 본다.
# `git diff data/` 는 추적되지 않은 새 파일(연도별 이력 등)을 보지 못한다.
git add data/prices.json data/history/
if git diff --cached --quiet; then
  echo "변경 없음"
  exit 0
fi
git -c user.name="mydash-collector" -c user.email="mydash-bot@users.noreply.github.com" \
    commit -q -m "chore: 시세 갱신 $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')"
git push -q origin main
echo "push 완료"
