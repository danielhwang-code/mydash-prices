#!/usr/bin/env python3
"""Wikidata에서 대통령 선거 날짜와 주요 전쟁 시작일을 받아 data/ 로 내보낸다.

선거는 자주 바뀌지 않으므로 주 1회로 충분하다.
Wikidata는 레이트리밋이 빡빡해(현재 1분당 1회 수준) 한 번의 쿼리로 두 나라를 함께 받는다.
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from collect import REPO
from sources.wikidata import parse_elections, parse_wars, MIN_WAR_SITELINKS

OUT = REPO / "data" / "elections.json"
OUT_WARS = REPO / "data" / "wars.json"
ENDPOINT = "https://query.wikidata.org/sparql"
UA = {
    "User-Agent": "mydash/1.0 (personal dashboard; contact via repo)",
    "Accept": "application/sparql-results+json",
}

QUERY = """
SELECT ?itemLabel ?date WHERE {
  ?item wdt:P31/wdt:P279* wd:Q40231 ;
        wdt:P17 ?country ;
        wdt:P585 ?date .
  VALUES ?country { wd:Q884 wd:Q30 }
  FILTER(?date >= "2005-01-01"^^xsd:dateTime)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ko,en". }
}
ORDER BY ?date
"""


WAR_QUERY = f"""
SELECT ?itemLabel ?start ?sitelinks WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q198 ;
        wdt:P580 ?start ;
        wikibase:sitelinks ?sitelinks .
  FILTER(?start >= "2005-01-01"^^xsd:dateTime)
  FILTER(?sitelinks >= {MIN_WAR_SITELINKS})
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }}
}}
ORDER BY ?start
"""


def fetch(query=None, tries=4):
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query or QUERY})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            # 429 는 레이트리밋. 기다렸다 다시 시도한다.
            if e.code == 429 and attempt < tries - 1:
                time.sleep(70)
                continue
            raise


def main():
    try:
        payload = fetch()
    except Exception as e:
        print(f"  ✗ Wikidata 조회 실패: {type(e).__name__}: {str(e)[:80]}")
        # 실패해도 기존 파일을 지우지 않는다 — 빈 파일이 나가면 화면에서 선거가 사라진다.
        return 1

    rows = parse_elections(payload)
    if not rows:
        print("  ✗ 걸러낸 결과가 0건 — 기존 파일을 유지한다 (라벨 형식이 바뀌었을 수 있음)")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"source": "wikidata", "elections": rows}, ensure_ascii=False, indent=None) + "\n",
        encoding="utf-8",
    )
    kr = sum(1 for r in rows if r["country"] == "KR")
    print(f"  ✓ 선거 {len(rows)}건 (한국 {kr} · 미국 {len(rows)-kr})  {rows[0]['date']} ~ {rows[-1]['date']}")

    # 전쟁 — Wikidata 는 분당 1회 수준으로 제한한다(자기네 장애 대응 중).
    # 선거 조회 직후에 던지면 반드시 429 다. 한 텀 쉬고 간다.
    time.sleep(70)
    try:
        wars = parse_wars(fetch(WAR_QUERY))
    except Exception as e:
        print(f"  ✗ 전쟁 조회 실패: {type(e).__name__}: {str(e)[:70]} — 기존 파일 유지")
        return 0
    if wars:
        OUT_WARS.write_text(
            json.dumps({"source": "wikidata", "min_sitelinks": MIN_WAR_SITELINKS, "wars": wars},
                       ensure_ascii=False, indent=None) + "\n", encoding="utf-8")
        print(f"  ✓ 전쟁 {len(wars)}건 (언어판 {MIN_WAR_SITELINKS}개 이상)  {wars[0]['date']} ~ {wars[-1]['date']}")
        for w in wars[-3:]:
            print(f"     {w['date']}  [{w['sitelinks']:>3}]  {w['label']}")
    else:
        print("  ✗ 전쟁 0건 — 기존 파일 유지")
    return 0


if __name__ == "__main__":
    sys.exit(main())
