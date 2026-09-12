"""티커 해석과 prices.json 생성 — 네트워크 없이 검증한다."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from collect import resolve_targets, build_prices_json, stale_days, build_history_json


class TestResolveTargets(unittest.TestCase):
    def test_국내는_모바일_엔드포인트로_간다(self):
        (t,) = resolve_targets("KR,005930\n")
        self.assertEqual(t.key, "KR:005930")
        self.assertEqual(t.urls, ["https://m.stock.naver.com/api/stock/005930/basic"])
        self.assertEqual(t.kind, "domestic")

    def test_일본은_T_접미사를_붙인다(self):
        (t,) = resolve_targets("JP,2563\n")
        self.assertEqual(t.urls, ["https://api.stock.naver.com/stock/2563.T/basic"])
        self.assertEqual(t.kind, "overseas")

    def test_미국은_나스닥_먼저_NYSE를_폴백으로_둔다(self):
        # 거래소를 모르므로 .O(나스닥) → .K(NYSE·AMEX) 순으로 시도한다.
        (t,) = resolve_targets("US,SCHD\n")
        self.assertEqual(
            t.urls,
            [
                "https://api.stock.naver.com/stock/SCHD.O/basic",
                "https://api.stock.naver.com/stock/SCHD.K/basic",
            ],
        )

    def test_빈_줄과_주석을_건너뛴다(self):
        targets = resolve_targets("# 주석\nKR,005930\n\n  \nUS,QQQM\n")
        self.assertEqual([t.key for t in targets], ["KR:005930", "US:QQQM"])

    def test_모르는_시장은_건너뛴다(self):
        self.assertEqual(resolve_targets("XX,FOO\nKR,005930\n")[0].key, "KR:005930")
        self.assertEqual(len(resolve_targets("XX,FOO\nKR,005930\n")), 1)


class TestStaleDays(unittest.TestCase):
    def test_오늘_성공했으면_0(self):
        self.assertEqual(stale_days("2026-09-09", "2026-09-09"), 0)

    def test_마지막_성공일로부터의_일수(self):
        self.assertEqual(stale_days("2026-09-05", "2026-09-09"), 4)

    def test_기록이_없으면_None(self):
        self.assertIsNone(stale_days(None, "2026-09-09"))


class TestBuildPricesJson(unittest.TestCase):
    def test_시세와_환율을_화면이_읽는_모양으로_만든다(self):
        out = build_prices_json(
            quotes={
                "US:QQQM": {"close": 296.0, "date": "2026-09-08", "currency": "USD",
                            "last_ok": "2026-09-09", "name": "Invesco NASDAQ 100 ETF"},
            },
            fx={"USDKRW": {"rate": 1341.3, "date": "2026-09-08", "quote_unit": 1}},
            today="2026-09-09",
            updated_at="2026-09-09 06:30 KST",
        )
        self.assertEqual(out["quotes"]["US:QQQM"]["close"], 296.0)
        self.assertEqual(out["quotes"]["US:QQQM"]["stale_days"], 0)
        self.assertEqual(out["fx"]["USDKRW"]["rate"], 1341.3)
        self.assertEqual(out["updated_at"], "2026-09-09 06:30 KST")

    def test_수집에_실패한_종목은_직전_값을_유지하고_stale을_올린다(self):
        # 0으로 때우면 총자산이 조용히 줄어든 화면이 된다.
        out = build_prices_json(
            quotes={
                "KR:005930": {"close": 269500, "date": "2026-09-05", "currency": "KRW",
                              "last_ok": "2026-09-05", "name": "삼성전자"},
            },
            fx={},
            today="2026-09-09",
            updated_at="2026-09-09 06:30 KST",
        )
        self.assertEqual(out["quotes"]["KR:005930"]["close"], 269500)
        self.assertEqual(out["quotes"]["KR:005930"]["stale_days"], 4)

    def test_수량이나_금액은_절대_담지_않는다(self):
        # 이 파일은 공개 저장소로 나간다.
        out = build_prices_json(
            quotes={"US:QQQM": {"close": 296.0, "date": "2026-09-08", "currency": "USD",
                                "last_ok": "2026-09-09", "name": "x"}},
            fx={},
            today="2026-09-09",
            updated_at="t",
        )
        allowed = {"close", "date", "currency", "stale_days", "name"}
        self.assertEqual(set(out["quotes"]["US:QQQM"]) - allowed, set())



class TestHistoryExport(unittest.TestCase):
    def test_연도별로_나눠_담는다(self):
        # 한 파일로 쌓으면 모바일이 전 기간을 통째로 내려받는다.
        out = build_history_json(
            price_rows=[("US:QQQM", "2025-12-31", 288.0), ("US:QQQM", "2026-01-02", 291.5)],
            fx_rows=[("USDKRW", "2025-12-31", 1400.0), ("USDKRW", "2026-01-02", 1410.0)],
            year="2026",
        )
        self.assertEqual(out["year"], "2026")
        self.assertEqual(out["quotes"]["US:QQQM"], [["2026-01-02", 291.5]])
        self.assertEqual(out["fx"]["USDKRW"], [["2026-01-02", 1410.0]])

    def test_날짜_오름차순으로_담는다(self):
        out = build_history_json(
            price_rows=[("KR:005930", "2026-03-02", 2.0), ("KR:005930", "2026-01-02", 1.0)],
            fx_rows=[], year="2026")
        self.assertEqual([d for d, _ in out["quotes"]["KR:005930"]], ["2026-01-02", "2026-03-02"])

    def test_해당_연도에_자료가_없으면_빈_묶음(self):
        out = build_history_json(price_rows=[], fx_rows=[], year="2024")
        self.assertEqual(out["quotes"], {})
        self.assertEqual(out["fx"], {})

if __name__ == "__main__":
    unittest.main(verbosity=2)
