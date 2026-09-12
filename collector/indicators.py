#!/usr/bin/env python3
"""ECOS 거시·부동산 지표 수집기.

월간 시계열을 SQLite에 쌓고 data/indicators.json 으로 내보낸다.
시세 수집기(collect.py)와 같은 DB를 쓰되 테이블만 다르다.
"""
import argparse
import datetime as dt
import json
import sys

from collect import db_connect, fetch_json, REPO, KST
from sources.ecos import SERIES, parse_series, total_count, EcosError

KEY = "sample"  # 정식 키를 받으면 여기만 바꾸면 된다
BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
PAGE = 10  # 샘플키 상한. 정식 키면 더 키울 수 있다
OUT = REPO / "data" / "indicators.json"


def fetch_all(stat, cycle, item, start, end):
    """페이지를 넘겨 전 구간을 받는다. 상한은 총량이 아니라 한 번에 받는 행 수다."""
    rows, pos, total = [], 1, None
    while True:
        url = f"{BASE}/{KEY}/json/kr/{pos}/{pos + PAGE - 1}/{stat}/{cycle}/{start}/{end}/{item}"
        payload = fetch_json(url)
        if total is None:
            total = total_count(payload)
            if total == 0:
                return []
        rows += parse_series(payload)
        pos += PAGE
        if pos > total or pos > 5000:
            break
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10, help="초기 수집 구간(년)")
    args = ap.parse_args()

    now = dt.datetime.now(KST)
    end = now.strftime("%Y%m")
    con = db_connect()
    con.execute("""CREATE TABLE IF NOT EXISTS indicator (
        series TEXT, date TEXT, value REAL, PRIMARY KEY (series, date))""")

    meta = {}
    for name, stat, cycle, item, label, unit in SERIES:
        meta[name] = {"label": label, "unit": unit, "stat": stat}
        # 이미 있는 마지막 시점부터만 받는다 (매일 전 구간을 다시 받지 않는다)
        last = con.execute("SELECT MAX(date) FROM indicator WHERE series=?", (name,)).fetchone()[0]
        if last:
            start = (dt.date.fromisoformat(last + "-01") - dt.timedelta(days=1)).strftime("%Y%m")
        else:
            start = (now - dt.timedelta(days=365 * args.years)).strftime("%Y%m")
        try:
            rows = fetch_all(stat, cycle, item, start, end)
        except EcosError as e:
            print(f"  ✗ {name:<16} {e}")
            continue
        except Exception as e:
            print(f"  ✗ {name:<16} {type(e).__name__}: {e}")
            continue
        if not rows:
            print(f"  – {name:<16} 새 자료 없음")
            continue
        con.executemany("INSERT OR REPLACE INTO indicator VALUES (?,?,?)",
                        [(name, r["date"], r["value"]) for r in rows])
        print(f"  ✓ {name:<16} {len(rows):>4}건  {rows[0]['date']} ~ {rows[-1]['date']}  ({label})")

    con.commit()

    out = {"updated_at": f"{now:%Y-%m-%d %H:%M KST}", "meta": meta, "series": {}}
    for (name,) in con.execute("SELECT DISTINCT series FROM indicator").fetchall():
        out["series"][name] = [
            [d, v] for d, v in
            con.execute("SELECT date, value FROM indicator WHERE series=? ORDER BY date", (name,))
        ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    n = sum(len(v) for v in out["series"].values())
    con.close()
    print(f"\n지표 {len(out['series'])}종 {n:,}건 → {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
