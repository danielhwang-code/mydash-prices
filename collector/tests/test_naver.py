"""네이버 응답 파싱 — 저장된 실제 응답(골든 픽스처)으로 검증한다.

소스가 조용히 바뀌면 여기서 먼저 깨져야 한다.
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from sources.naver import parse_domestic, parse_overseas, parse_fx, QuoteNotFound

FIX = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class TestDomestic(unittest.TestCase):
    def test_콤마_섞인_문자열_종가를_숫자로_바꾼다(self):
        q = parse_domestic(load("domestic_005930.json"))
        self.assertEqual(q["close"], 269500)
        self.assertEqual(q["currency"], "KRW")
        self.assertEqual(q["name"], "삼성전자")

    def test_ETF도_같은_구조로_읽는다(self):
        q = parse_domestic(load("domestic_133690.json"))
        self.assertEqual(q["close"], 176020)
        self.assertEqual(q["currency"], "KRW")

    def test_거래일자를_남긴다(self):
        q = parse_domestic(load("domestic_005930.json"))
        self.assertEqual(q["date"], "2026-09-08")


class TestOverseas(unittest.TestCase):
    def test_미국_종목은_달러로_읽는다(self):
        # 해외 종가도 문자열('296.00')로 온다.
        q = parse_overseas(load("overseas_QQQM.json"))
        self.assertAlmostEqual(q["close"], 296.00)
        self.assertEqual(q["currency"], "USD")

    def test_일본_종목은_엔으로_읽는다(self):
        q = parse_overseas(load("overseas_2563.json"))
        self.assertAlmostEqual(q["close"], 405.7)
        self.assertEqual(q["currency"], "JPY")
        self.assertEqual(q["date"], "2026-09-08")

    def test_없는_종목은_QuoteNotFound(self):
        with self.assertRaises(QuoteNotFound):
            parse_overseas(load("overseas_missing.json"))


class TestFx(unittest.TestCase):
    def test_달러는_1단위당_원화_그대로(self):
        self.assertAlmostEqual(parse_fx(load("fx_usdkrw.json"))["rate"], 1341.3)

    def test_엔화는_100엔_고시를_1엔으로_환산한다(self):
        # 네이버는 엔화를 100엔당으로 고시한다(fullName='일본 JPY 100').
        # 그대로 쓰면 엔화 자산이 100배로 부풀어 포트폴리오 전체를 삼킨다.
        self.assertAlmostEqual(parse_fx(load("fx_jpykrw.json"))["rate"], 8.7143)

    def test_고시단위를_결과에_남긴다(self):
        # 나중에 값이 이상할 때 단위 때문인지 바로 확인할 수 있어야 한다.
        self.assertEqual(parse_fx(load("fx_jpykrw.json"))["quote_unit"], 100)
        self.assertEqual(parse_fx(load("fx_usdkrw.json"))["quote_unit"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
