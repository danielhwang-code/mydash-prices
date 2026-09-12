"""ECOS(한국은행) 응답 파싱 — 저장된 실제 응답으로 검증한다."""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from sources.ecos import parse_series, total_count, EcosError

FIX = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class TestParseSeries(unittest.TestCase):
    def test_월간_지수를_날짜_값으로_바꾼다(self):
        rows = parse_series(load("ecos_house_seoul.json"))
        self.assertEqual(rows[0]["date"], "2025-01")
        self.assertAlmostEqual(rows[0]["value"], 89.164)

    def test_일간_시계열은_YYYYMMDD를_ISO로_바꾼다(self):
        rows = parse_series(load("ecos_base_rate.json"))
        self.assertEqual(rows[0]["date"], "2026-01-01")
        self.assertAlmostEqual(rows[0]["value"], 2.5)

    def test_날짜_오름차순으로_낸다(self):
        rows = parse_series(load("ecos_house_seoul.json"))
        self.assertEqual(rows, sorted(rows, key=lambda r: r["date"]))

    def test_전체_건수를_읽는다(self):
        # 샘플키는 호출당 10건이라 페이지를 넘기려면 총 건수를 알아야 한다.
        self.assertEqual(total_count(load("ecos_house_seoul.json")), 12)

    def test_오류_응답은_EcosError로_드러낸다(self):
        # 조용히 빈 배열을 돌려주면 지표가 사라진 걸 눈치채지 못한다.
        with self.assertRaises(EcosError):
            parse_series(load("ecos_error.json"))
        with self.assertRaises(EcosError):
            total_count(load("ecos_error.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
