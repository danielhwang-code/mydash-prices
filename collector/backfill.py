#!/usr/bin/env python3
"""과거 일봉·환율 이력을 SQLite에 채운다.

수집기를 켠 날부터 기다릴 필요 없이 추이 차트를 바로 그릴 수 있게 한다.
한 번 돌리면 되고, 이후는 collect.py가 매일 이어 붙인다.
"""
import argparse
import datetime as dt
import sys

from collect import db_connect, fetch_json, resolve_targets, TICKERS, FX_PAIRS, KST
from sources.naver import parse_price_history, parse_fx_history, parse_fx

HIST_DOMESTIC = "https://api.stock.naver.com/chart/domestic/item/{code}/day?startDateTime={s}&endDateTime={e}"
HIST_FOREIGN = "https://api.stock.naver.com/chart/foreign/item/{code}/day?startDateTime={s}&endDateTime={e}"
# pageSize 상한이 50이라 페이지를 넘기며 받는다(100 이상은 400).
HIST_FX = "https://api.stock.naver.com/marketindex/exchange/FX_{pair}/prices?page={p}&pageSize=50"


def history_urls(target, start, end):
    """collect.resolve_targets 가 만든 조회 URL에서 일봉 URL을 만든다."""
    s, e = start.strftime("%Y%m%d0000"), end.strftime("%Y%m%d0000")
    out = []
    for url in target.urls:
        code = url.rsplit("/stock/", 1)[-1].split("/basic")[0] if "/stock/" in url else None
        if target.kind == "domestic":
            out.append(HIST_DOMESTIC.format(code=target.key.split(":", 1)[1], s=s, e=e))
        elif code:
            out.append(HIST_FOREIGN.format(code=code, s=s, e=e))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365, help="며칠치를 받을지 (기본 1년)")
    args = ap.parse_args()

    end = dt.datetime.now(KST).date()
    start = end - dt.timedelta(days=args.days)
    print(f"백필 구간 {start} ~ {end}")

    con = db_connect()
    targets = resolve_targets(TICKERS.read_text(encoding="utf-8"))

    for t in targets:
        rows = []
        for url in history_urls(t, start, end):
            try:
                rows = parse_price_history(fetch_json(url))
                if rows:
                    break
            except Exception as e:
                print(f"    ({url.split('/item/')[-1][:18]} 실패: {type(e).__name__})")
        if not rows:
            print(f"  ✗ {t.key:<12} 이력 없음")
            continue
        cur = con.execute("SELECT currency, name FROM quote_state WHERE key=?", (t.key,)).fetchone()
        currency, name = cur if cur else (None, None)
        con.executemany(
            "INSERT OR IGNORE INTO price (key,date,close,currency,name) VALUES (?,?,?,?,?)",
            [(t.key, r["date"], r["close"], currency, name) for r in rows])
        print(f"  ✓ {t.key:<12} {len(rows):>4}일  {rows[0]['date']} ~ {rows[-1]['date']}")

    for pair in FX_PAIRS:
        try:
            unit = parse_fx(fetch_json(
                f"https://api.stock.naver.com/marketindex/exchange/FX_{pair}"))["quote_unit"]
            rows, seen = [], set()
            for page in range(1, max(1, args.days // 50 + 2)):
                chunk = parse_fx_history(
                    fetch_json(HIST_FX.format(pair=pair, p=page)), quote_unit=unit)
                fresh = [r for r in chunk if r["date"] not in seen]
                if not fresh:
                    break
                seen.update(r["date"] for r in fresh)
                rows.extend(fresh)
            rows.sort(key=lambda r: r["date"])
            con.executemany(
                "INSERT OR IGNORE INTO fx (pair,date,rate,quote_unit) VALUES (?,?,?,?)",
                [(pair, r["date"], r["rate"], unit) for r in rows])
            note = f" (100단위 고시 → 1단위 환산)" if unit != 1 else ""
            print(f"  ✓ {pair:<12} {len(rows):>4}일  {rows[0]['date']} ~ {rows[-1]['date']}{note}")
        except Exception as e:
            print(f"  ✗ {pair:<12} {type(e).__name__}: {e}")

    con.commit()
    n_price = con.execute("SELECT COUNT(*) FROM price").fetchone()[0]
    n_fx = con.execute("SELECT COUNT(*) FROM fx").fetchone()[0]
    con.close()
    print(f"\n적재 완료 — price {n_price:,}행 · fx {n_fx:,}행")
    return 0


if __name__ == "__main__":
    sys.exit(main())
