#!/usr/bin/env bash
# ECOS 거시·부동산 지표 수집. 월간 자료라 주 1회면 충분하다.
# 시세(run.sh)와 분리해 샘플키를 하루 두 번 두드리지 않게 한다.
set -euo pipefail
cd "$(dirname "$0")/.."

# 키는 공개 저장소 밖에 둔다. 없으면 샘플키로 동작한다.
[ -f "$HOME/.mydash_env" ] && . "$HOME/.mydash_env"

git pull --ff-only --quiet origin main

python3 collector/indicators.py || echo "[warn] 지표 수집 실패 — 직전 값 유지"

# 선거 날짜(Wikidata). 자주 바뀌지 않으므로 같은 주기로 충분하다.
python3 collector/elections.py || echo "[warn] 선거 수집 실패 — 직전 값 유지"

# 파일을 하나씩 적으면 새 출력이 생길 때마다 빠뜨린다(이력·전쟁 파일에서 실제로 겪음).
# 디렉터리 단위로 올리고 인덱스로 판정한다.
git add data/
if git diff --cached --quiet; then
  echo "변경 없음"
  exit 0
fi
git -c user.name="mydash-collector" -c user.email="mydash-bot@users.noreply.github.com" \
    commit -q -m "chore: 지표 갱신 $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')"
git push -q origin main
echo "push 완료"
