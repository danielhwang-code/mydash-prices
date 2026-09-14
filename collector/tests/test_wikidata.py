"""Wikidata 선거 결과 걸러내기 — 저장된 실제 응답으로 검증한다.

구조화 데이터라도 분류 체계에 하위 항목이 다 들어 있다.
주(州)별 개표·당내 경선·부족 선거까지 섞여 있어 필터가 핵심이다.
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from sources.wikidata import parse_elections

FIX = pathlib.Path(__file__).parent / "fixtures"
ROWS = json.loads((FIX / "wikidata_elections.json").read_text(encoding="utf-8"))


class TestParseElections(unittest.TestCase):
    def setUp(self):
        self.got = parse_elections(ROWS)
        self.by_date = {e["date"]: e for e in self.got}

    def test_한국_대선을_전부_찾는다(self):
        for date in ("2012-12-19", "2017-05-09", "2022-03-09", "2025-06-03"):
            self.assertIn(date, self.by_date, f"{date} 한국 대선이 빠졌다")

    def test_라벨_형식이_달라도_찾는다(self):
        # '대한민국 제19대 대통령 선거' 와 '2022년 제20대 대한민국 대통령 선거' 둘 다 쓰인다.
        self.assertEqual(self.by_date["2022-03-09"]["country"], "KR")
        self.assertEqual(self.by_date["2017-05-09"]["country"], "KR")

    def test_미국_대선을_찾는다(self):
        for date in ("2016-11-08", "2020-11-03", "2024-11-05"):
            self.assertIn(date, self.by_date, f"{date} 미국 대선이 빠졌다")
        self.assertEqual(self.by_date["2024-11-05"]["country"], "US")

    def test_주별_개표_항목을_버린다(self):
        # '2024년 미국 대통령 선거 캘리포니아주' 같은 항목이 50개씩 있다.
        for e in self.got:
            self.assertNotIn("주", e["label"].replace("대한민국", ""),
                             f"주 단위 항목이 남았다: {e['label']}")
            self.assertNotIn("D.C.", e["label"])

    def test_당내_경선을_버린다(self):
        for e in self.got:
            for bad in ("경선", "예비선거", "primary"):
                self.assertNotIn(bad, e["label"].lower() if bad == "primary" else e["label"],
                                 f"경선이 남았다: {e['label']}")

    def test_그밖의_대통령_선거를_버린다(self):
        # Navajo Nation presidential election 같은 것.
        for e in self.got:
            self.assertIn(e["country"], ("KR", "US"))

    def test_같은_선거가_중복되지_않는다(self):
        dates = [e["date"] for e in self.got]
        self.assertEqual(len(dates), len(set(dates)), "같은 날짜가 두 번 나왔다")

    def test_날짜_오름차순(self):
        self.assertEqual(self.got, sorted(self.got, key=lambda e: e["date"]))

    def test_미래_선거도_포함한다(self):
        # 다가오는 선거를 미리 표시할 수 있어야 한다.
        self.assertTrue(any(e["date"] >= "2028-01-01" for e in self.got))


if __name__ == "__main__":
    unittest.main(verbosity=2)
