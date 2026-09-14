"""Wikidata SPARQL — 선거 날짜.

구조화 데이터지만 분류 체계에 하위 항목이 전부 들어 있다.
'대통령 선거'로만 거르면 주(州)별 개표 50건, 당내 경선, 부족 선거가 딸려온다.
전국 단위 본선거만 남기는 게 이 모듈의 일이다.
"""
import re

# 전국 단위 본선거만 매칭한다.
PATTERNS = [
    # 대한민국 제19대 대통령 선거 / 2022년 제20대 대한민국 대통령 선거
    ("KR", re.compile(r"^(대한민국\s*제\d+대\s*대통령\s*선거|\d{4}년\s*제\d+대\s*대한민국\s*대통령\s*선거)$")),
    # 2024년 미국 대통령 선거 / 2024 United States presidential election
    ("US", re.compile(r"^(\d{4}년\s*미국\s*대통령\s*선거|\d{4}\s+United States presidential election)$")),
]

# 본선거가 아닌 것 — 패턴이 느슨해질 때를 대비한 이중 방어
EXCLUDE = re.compile(r"경선|예비선거|primary|재보궐|Navajo|Nation ", re.I)


def parse_elections(payload):
    """SPARQL 응답 → [{date, country, label}] 오름차순·중복 제거."""
    out, seen = [], set()
    for row in payload.get("results", {}).get("bindings", []):
        label = (row.get("itemLabel", {}) or {}).get("value", "").strip()
        date = (row.get("date", {}) or {}).get("value", "")[:10]
        if not label or len(date) != 10 or EXCLUDE.search(label):
            continue
        country = next((c for c, pat in PATTERNS if pat.match(label)), None)
        if country is None:
            continue
        if date in seen:
            continue
        seen.add(date)
        out.append({"date": date, "country": country, "label": label})
    return sorted(out, key=lambda e: e["date"])
