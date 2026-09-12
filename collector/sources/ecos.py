"""한국은행 ECOS 통계 API.

한 번의 호출로 받는 행 수에 상한이 있어(샘플키 10건) 페이지를 넘겨 받는다.
상한은 '총량'이 아니라 '한 번에 받는 행 수'다.

⚠️ 지금은 공개 샘플키(`sample`)를 쓴다. 동작하지만 호출당 10건 제한이 있고
   언제 막힐지 보장이 없다. 정식 키(무료)를 받으면 ECOS_KEY 로 바꾸면 된다.
"""

# 수집 대상. (내부이름, 통계코드, 주기, 항목코드, 표시이름, 단위)
SERIES = [
    ("kr_base_rate",   "722Y001", "M", "0101000", "한국 기준금리",           "연%"),
    ("us_policy_rate", "902Y006", "M", "US",      "미국 정책금리",           "연%"),
    ("cpi",            "901Y009", "M", "0",       "소비자물가지수",          "지수"),
    ("house_kr",       "901Y062", "M", "P63A",    "주택매매가격지수(전국)",  "지수"),
    ("house_seoul",    "901Y062", "M", "P63AD",   "주택매매가격지수(서울)",  "지수"),
    ("apt_seoul",      "901Y062", "M", "P63ACA",  "아파트매매가격지수(서울)", "지수"),
    ("unsold_kr",      "901Y074", "M", "I410A",   "미분양주택(전국)",        "호"),
    ("unsold_seoul",   "901Y074", "M", "I410B",   "미분양주택(서울)",        "호"),
]


class EcosError(Exception):
    """ECOS가 오류를 돌려줬다."""


def _body(payload):
    if "RESULT" in payload:
        r = payload["RESULT"]
        raise EcosError(f"{r.get('CODE')}: {r.get('MESSAGE', '')[:80]}")
    body = payload.get("StatisticSearch")
    if body is None:
        raise EcosError("StatisticSearch 없음")
    return body


def total_count(payload):
    """전체 건수. 페이지를 넘기려면 먼저 알아야 한다."""
    return int(_body(payload).get("list_total_count", 0))


def _iso(time_str):
    """ECOS TIME: 202501(월) · 20260101(일) · 2025(년) → ISO 표기."""
    t = str(time_str)
    if len(t) == 8:
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    if len(t) == 6:
        return f"{t[:4]}-{t[4:6]}"
    return t


def parse_series(payload):
    """[{date, value}] 오름차순. 값이 비어 있는 행은 버린다(결측을 0으로 만들지 않는다)."""
    rows = []
    for r in _body(payload).get("row", []):
        raw = r.get("DATA_VALUE")
        if raw in (None, "", "-"):
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        rows.append({"date": _iso(r.get("TIME")), "value": value})
    return sorted(rows, key=lambda x: x["date"])
