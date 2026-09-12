#!/usr/bin/env bash
# ECOS 거시·부동산 지표 수집. 월간 자료라 주 1회면 충분하다.
# 시세(run.sh)와 분리해 샘플키를 하루 두 번 두드리지 않게 한다.
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only --quiet origin main

python3 collector/indicators.py || { echo "[warn] 지표 수집 실패 — 직전 값 유지"; exit 0; }

git add data/indicators.json
if git diff --cached --quiet; then
  echo "변경 없음"
  exit 0
fi
git -c user.name="mydash-collector" -c user.email="mydash-bot@users.noreply.github.com" \
    commit -q -m "chore: 지표 갱신 $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')"
git push -q origin main
echo "push 완료"
