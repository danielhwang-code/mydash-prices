"""네이버 금융 공개 엔드포인트에서 시세와 환율을 읽는다.

국내·미국·일본·환율이 한 소스로 커버돼 어댑터가 하나면 된다.
파싱은 순수 함수로 두고 골든 픽스처로 검증한다 — 소스가 조용히 바뀌면 테스트가 먼저 깨진다.
"""
import re


class QuoteNotFound(Exception):
    """해당 종목의 시세를 찾지 못했다."""


def _to_number(value):
    """'269,500' 같은 콤마 섞인 문자열도 숫자로 만든다."""
    if isinstance(value, (int, float)):
        return value
    cleaned = str(value).replace(",", "").strip()
    number = float(cleaned)
    return int(number) if number.is_integer() else number


def _date_of(payload):
    # localTradedAt: '2026-09-08T16:10:20+09:00' — 거래소 현지 날짜를 그대로 쓴다.
    traded = payload.get("localTradedAt") or ""
    return traded[:10] or None


def parse_domestic(payload):
    """m.stock.naver.com/api/stock/{code}/basic 응답."""
    if "closePrice" not in payload:
        raise QuoteNotFound(payload.get("message") or "closePrice 없음")
    return {
        "close": _to_number(payload["closePrice"]),
        "currency": "KRW",
        "date": _date_of(payload),
        "name": payload.get("stockName"),
        "market_status": payload.get("marketStatus"),
    }


def parse_overseas(payload):
    """api.stock.naver.com/stock/{reutersCode}/basic 응답 (미국·일본)."""
    if "closePrice" not in payload:
        raise QuoteNotFound(payload.get("message") or "closePrice 없음")
    return {
        "close": _to_number(payload["closePrice"]),
        "currency": (payload.get("currencyType") or {}).get("code"),
        "date": _date_of(payload),
        "name": payload.get("stockNameEng") or payload.get("stockName"),
        "market_status": payload.get("marketStatus"),
    }


def parse_fx(payload):
    """api.stock.naver.com/marketindex/exchange/FX_{PAIR} 응답.

    엔화는 100엔당으로 고시된다(fullName='일본 JPY 100'). 1단위 기준으로 환산해서
    돌려주지 않으면 엔화 자산이 100배로 부풀어 포트폴리오 전체를 삼킨다.
    """
    info = payload.get("exchangeInfo")
    if not info or "calcPrice" not in info:
        raise QuoteNotFound("exchangeInfo 없음")

    # fullName 끝의 숫자가 고시 단위. 없으면 1단위 고시.
    match = re.search(r"(\d+)\s*$", info.get("fullName") or "")
    quote_unit = int(match.group(1)) if match else 1

    return {
        "rate": _to_number(info["calcPrice"]) / quote_unit,
        "quote_unit": quote_unit,
        "date": _date_of(info) or None,
        "source": (info.get("stockExchangeType") or {}).get("nameKor"),
    }


def parse_price_history(payload):
    """일봉 응답 → [{date, close}] 오름차순.

    국내 chart/domestic/item/{code}/day, 해외 chart/foreign/item/{code}.{X}/day
    둘 다 같은 모양으로 온다.
    """
    rows = payload if isinstance(payload, list) else payload.get("result") or []
    out = []
    for r in rows:
        raw = r.get("localDate") or ""
        if len(raw) != 8 or "closePrice" not in r:
            continue
        out.append({
            "date": f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}",
            "close": _to_number(r["closePrice"]),
        })
    return sorted(out, key=lambda x: x["date"])


def parse_fx_history(payload, quote_unit=1):
    """환율 이력 응답 → [{date, rate}] 오름차순.

    이력 응답에는 고시 단위 표시가 없다. 현재 시세(parse_fx)에서 확인한
    quote_unit 을 반드시 넘겨야 한다 — 엔화를 100으로 안 나누면 차트가 100배 튄다.
    """
    rows = payload if isinstance(payload, list) else payload.get("result") or []
    out = []
    for r in rows:
        date = r.get("localTradedAt")
        if not date or "closePrice" not in r:
            continue
        out.append({"date": date, "rate": _to_number(r["closePrice"]) / quote_unit})
    return sorted(out, key=lambda x: x["date"])
