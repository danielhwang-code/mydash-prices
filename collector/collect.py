#!/usr/bin/env python3
"""개인 대시보드 시세 수집기.

tickers.txt(시장,종목코드)를 읽어 네이버 공개 엔드포인트에서 시세와 환율을 받고,
SQLite에 일별로 쌓은 뒤 data/prices.json 으로 내보낸다.

이 저장소는 공개다. 여기서 다루는 것은 공개 시장 데이터와 종목코드뿐이고,
보유 수량·매수단가·평가액은 이 프로세스에 들어오지 않는다.
"""
import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from sources.naver import parse_domestic, parse_overseas, parse_fx, QuoteNotFound

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
DB_PATH = ROOT / "mydash.db"
TICKERS = REPO / "tickers.txt"
OUT = REPO / "data" / "prices.json"

FX_PAIRS = ["USDKRW", "JPYKRW"]
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
KST = dt.timezone(dt.timedelta(hours=9))


@dataclass
class Target:
    key: str
    kind: str  # domestic | overseas
    urls: list = field(default_factory=list)


def resolve_targets(text):
    """tickers.txt 본문 → 조회 대상 목록.

    미국은 거래소를 모르므로 .O(나스닥) → .K(NYSE·AMEX) 순으로 시도한다.
    """
    targets = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "," not in line:
            continue
        market, code = (p.strip() for p in line.split(",", 1))
        market = market.upper()
        if market == "KR":
            targets.append(Target(
                f"KR:{code}", "domestic",
                [f"https://m.stock.naver.com/api/stock/{code}/basic"]))
        elif market == "JP":
            targets.append(Target(
                f"JP:{code}", "overseas",
                [f"https://api.stock.naver.com/stock/{code}.T/basic"]))
        elif market == "US":
            targets.append(Target(
                f"US:{code}", "overseas",
                [f"https://api.stock.naver.com/stock/{code}.O/basic",
                 f"https://api.stock.naver.com/stock/{code}.K/basic"]))
        # 모르는 시장은 건너뛴다 (조용히 0을 만들지 않는다)
    return targets


def stale_days(last_ok, today):
    """마지막 수집 성공일로부터 지난 일수.

    가격이 안 변한 것은 stale이 아니다 — 휴장일에는 그게 정상이다.
    수집 자체가 실패한 날만 쌓인다.
    """
    if not last_ok:
        return None
    a = dt.date.fromisoformat(last_ok)
    b = dt.date.fromisoformat(today)
    return (b - a).days


def build_prices_json(quotes, fx, today, updated_at):
    """화면이 읽는 모양으로 만든다. 공개 저장소로 나가므로 시장 데이터만 담는다."""
    return {
        "updated_at": updated_at,
        "quotes": {
            key: {
                "close": q["close"],
                "date": q["date"],
                "currency": q["currency"],
                "name": q.get("name"),
                "stale_days": stale_days(q.get("last_ok"), today) or 0,
            }
            for key, q in sorted(quotes.items())
        },
        "fx": {
            pair: {"rate": v["rate"], "date": v.get("date"), "quote_unit": v.get("quote_unit", 1)}
            for pair, v in sorted(fx.items())
        },
    }


# ---------- 아래는 부작용이 있는 부분 (네트워크·DB) ----------

def fetch_json(url, timeout=15, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # 네트워크·JSON 어느 쪽이든 재시도
            last = e
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise last


def fetch_quote(target):
    """URL 후보를 순서대로 시도한다. 하나라도 성공하면 그 값을 쓴다."""
    parse = parse_domestic if target.kind == "domestic" else parse_overseas
    errors = []
    for url in target.urls:
        try:
            return parse(fetch_json(url))
        except (QuoteNotFound, urllib.error.HTTPError) as e:
            errors.append(f"{url.rsplit('/', 2)[-2]}: {e}")
        except Exception as e:
            errors.append(f"{url.rsplit('/', 2)[-2]}: {type(e).__name__} {e}")
    raise QuoteNotFound("; ".join(errors))


def db_connect():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS price (
          key TEXT, date TEXT, close REAL, currency TEXT, name TEXT,
          PRIMARY KEY (key, date));
        CREATE TABLE IF NOT EXISTS fx (
          pair TEXT, date TEXT, rate REAL, quote_unit INTEGER,
          PRIMARY KEY (pair, date));
        CREATE TABLE IF NOT EXISTS quote_state (
          key TEXT PRIMARY KEY, last_ok TEXT, last_close REAL,
          currency TEXT, name TEXT, last_date TEXT, fail_streak INTEGER DEFAULT 0);
    """)
    return con


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="DB·파일을 쓰지 않고 조회만")
    args = ap.parse_args()

    now = dt.datetime.now(KST)
    today = now.date().isoformat()
    targets = resolve_targets(TICKERS.read_text(encoding="utf-8"))
    print(f"[{now:%Y-%m-%d %H:%M KST}] 대상 {len(targets)}종")

    con = db_connect()
    ok = fail = 0

    for t in targets:
        try:
            q = fetch_quote(t)
            ok += 1
            print(f"  ✓ {t.key:<12} {q['close']:>12,} {q['currency']}  {q['date']}  {q.get('name','')[:24]}")
            if not args.dry_run:
                con.execute("INSERT OR REPLACE INTO price VALUES (?,?,?,?,?)",
                            (t.key, q["date"], q["close"], q["currency"], q.get("name")))
                con.execute("""INSERT INTO quote_state (key,last_ok,last_close,currency,name,last_date,fail_streak)
                               VALUES (?,?,?,?,?,?,0)
                               ON CONFLICT(key) DO UPDATE SET
                                 last_ok=excluded.last_ok, last_close=excluded.last_close,
                                 currency=excluded.currency, name=excluded.name,
                                 last_date=excluded.last_date, fail_streak=0""",
                            (t.key, today, q["close"], q["currency"], q.get("name"), q["date"]))
        except Exception as e:
            fail += 1
            # 실패해도 0으로 때우지 않는다. 직전 값을 유지하고 stale만 올린다.
            print(f"  ✗ {t.key:<12} {e}")
            if not args.dry_run:
                con.execute("""INSERT INTO quote_state (key,fail_streak) VALUES (?,1)
                               ON CONFLICT(key) DO UPDATE SET fail_streak=fail_streak+1""",
                            (t.key,))

    fx_out = {}
    for pair in FX_PAIRS:
        try:
            v = parse_fx(fetch_json(f"https://api.stock.naver.com/marketindex/exchange/FX_{pair}"))
            fx_out[pair] = v
            unit = f" (100단위 고시 → 1단위 환산)" if v["quote_unit"] != 1 else ""
            print(f"  ✓ {pair:<12} {v['rate']:>12,.4f}{unit}")
            if not args.dry_run:
                con.execute("INSERT OR REPLACE INTO fx VALUES (?,?,?,?)",
                            (pair, today, v["rate"], v["quote_unit"]))
        except Exception as e:
            print(f"  ✗ {pair:<12} {e}")

    if args.dry_run:
        print(f"\n[dry-run] 성공 {ok} · 실패 {fail} — 저장하지 않음")
        return 0 if fail == 0 else 1

    con.commit()

    # 저장된 상태로 내보낸다 (이번에 실패한 종목도 직전 값이 남아 있다)
    quotes = {}
    for key, last_ok, close, cur, name, last_date in con.execute(
            "SELECT key,last_ok,last_close,currency,name,last_date FROM quote_state WHERE last_close IS NOT NULL"):
        quotes[key] = {"close": close, "date": last_date, "currency": cur,
                       "name": name, "last_ok": last_ok}
    if not fx_out:
        for pair, rate, unit, d in con.execute(
                "SELECT pair,rate,quote_unit,date FROM fx WHERE date=(SELECT MAX(date) FROM fx f2 WHERE f2.pair=fx.pair)"):
            fx_out[pair] = {"rate": rate, "quote_unit": unit, "date": d}

    payload = build_prices_json(quotes, fx_out, today, f"{now:%Y-%m-%d %H:%M KST}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    con.close()

    print(f"\n성공 {ok} · 실패 {fail} → {OUT.relative_to(REPO)} ({len(payload['quotes'])}종)")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
