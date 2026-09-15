"""알림 판단 — 언제 보내고 언제 침묵할지.

매번 보내면 곧 무시하게 된다. 상태가 바뀔 때만 보낸다.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from notify import decide, build_message, FAIL_THRESHOLD


class TestDecide(unittest.TestCase):
    def test_처음_실패는_바로_알리지_않는다(self):
        # 일시적 네트워크 오류로 매번 울리면 곧 무시하게 된다.
        self.assertEqual(decide(prev_fails=0, cur_fails=1, notified=False), "quiet")

    def test_연속_실패가_기준을_넘으면_알린다(self):
        self.assertEqual(decide(prev_fails=FAIL_THRESHOLD - 1, cur_fails=FAIL_THRESHOLD,
                                notified=False), "alert")

    def test_이미_알린_뒤에는_계속_울리지_않는다(self):
        # 고칠 때까지 하루 두 번씩 영원히 오면 안 된다.
        self.assertEqual(decide(prev_fails=9, cur_fails=10, notified=True), "quiet")

    def test_복구되면_한_번_알린다(self):
        self.assertEqual(decide(prev_fails=5, cur_fails=0, notified=True), "recovered")

    def test_알린_적_없이_복구되면_조용히_넘어간다(self):
        self.assertEqual(decide(prev_fails=1, cur_fails=0, notified=False), "quiet")

    def test_계속_정상이면_조용하다(self):
        self.assertEqual(decide(prev_fails=0, cur_fails=0, notified=False), "quiet")


class TestMessage(unittest.TestCase):
    def test_실패_알림에_무엇이_실패했는지_담는다(self):
        m = build_message("alert", {"failed": ["KR:005930", "US:QQQM"], "total": 9, "streak": 3})
        self.assertIn("005930", m)
        self.assertIn("QQQM", m)
        self.assertIn("3", m)

    def test_복구_알림은_짧게(self):
        m = build_message("recovered", {"failed": [], "total": 9, "streak": 0})
        self.assertIn("복구", m)

    def test_실패가_많으면_전부_나열하지_않는다(self):
        # 디스코드 메시지 한도(2000자)를 넘기면 전송 자체가 실패한다.
        m = build_message("alert", {"failed": [f"US:T{i}" for i in range(60)], "total": 60, "streak": 3})
        self.assertLess(len(m), 1900)
        self.assertIn("60", m)

    def test_조용할_때는_메시지를_만들지_않는다(self):
        self.assertIsNone(build_message("quiet", {"failed": [], "total": 9, "streak": 0}))




class TestReport(unittest.TestCase):
    """상태 파일을 오가는 부분 — 여기가 틀리면 알림이 영영 안 오거나 매번 온다."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.dir.name) / "state.json"
        self.sent = []

    def tearDown(self):
        self.dir.cleanup()

    def run_once(self, failed, total=9, job="시세 수집"):
        import notify
        orig = notify.post
        notify.post = lambda text, webhook=None: (self.sent.append(text), True)[1]
        try:
            return notify.report(job, failed, total, path=self.path)
        finally:
            notify.post = orig

    def test_연속_실패가_쌓여야_한_번_알린다(self):
        for _ in range(FAIL_THRESHOLD - 1):
            self.assertFalse(self.run_once(["KR:005930"]))
        self.assertTrue(self.run_once(["KR:005930"]))
        self.assertEqual(len(self.sent), 1)

    def test_알린_뒤에는_계속_실패해도_조용하다(self):
        for _ in range(FAIL_THRESHOLD + 5):
            self.run_once(["KR:005930"])
        self.assertEqual(len(self.sent), 1, f"중복 발송: {self.sent}")

    def test_복구되면_한_번_알리고_다시_조용해진다(self):
        for _ in range(FAIL_THRESHOLD):
            self.run_once(["KR:005930"])
        self.assertTrue(self.run_once([]))
        self.assertIn("복구", self.sent[-1])
        self.assertFalse(self.run_once([]), "정상인데 또 보냈다")
        self.assertEqual(len(self.sent), 2)

    def test_복구_뒤_다시_망가지면_또_알린다(self):
        for _ in range(FAIL_THRESHOLD):
            self.run_once(["KR:005930"])
        self.run_once([])
        for _ in range(FAIL_THRESHOLD):
            self.run_once(["KR:005930"])
        self.assertEqual(len(self.sent), 3, "복구 뒤 재발을 놓쳤다")

    def test_중간에_한_번_성공하면_연속이_끊긴다(self):
        self.run_once(["KR:005930"])
        self.run_once(["KR:005930"])
        self.run_once([])           # 성공
        self.run_once(["KR:005930"])
        self.assertEqual(self.sent, [], "연속이 끊겼는데 알렸다")

    def test_전송이_실패하면_알린_것으로_치지_않는다(self):
        # 디스코드가 잠깐 죽었는데 '알림 완료'로 기록하면 영영 못 받는다.
        import notify
        orig = notify.post
        notify.post = lambda text, webhook=None: False
        try:
            for _ in range(FAIL_THRESHOLD):
                notify.report("시세 수집", ["KR:005930"], 9, path=self.path)
        finally:
            notify.post = orig
        self.assertTrue(self.run_once(["KR:005930"]), "전송 실패 뒤 재시도하지 않았다")

    def test_작업별로_상태가_섞이지_않는다(self):
        for _ in range(FAIL_THRESHOLD):
            self.run_once(["KR:005930"], job="시세 수집")
        self.run_once(["cpi"], total=10, job="지표 수집")
        self.assertEqual(len(self.sent), 1, "다른 작업 실패가 같은 카운터를 썼다")

    def test_상태_파일이_깨져도_돌아간다(self):
        self.path.write_text("{ 깨진 json", encoding="utf-8")
        self.run_once(["KR:005930"])
        self.assertTrue(self.path.read_text(encoding="utf-8").strip().startswith("{"))


class TestThreshold(unittest.TestCase):
    """작업마다 참을 횟수가 다르다. 종목 하나 빠지는 것과 push 가 막히는 것은 급이 다르다."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.dir.name) / "state.json"
        self.sent = []

    def tearDown(self):
        self.dir.cleanup()

    def run_once(self, threshold):
        import notify
        orig = notify.post
        notify.post = lambda text, webhook=None: (self.sent.append(text), True)[1]
        try:
            return notify.report("push", ["git push"], 1, path=self.path, threshold=threshold)
        finally:
            notify.post = orig

    def test_임계값_1이면_첫_실패에_알린다(self):
        self.assertTrue(self.run_once(1))

    def test_임계값을_넘겨도_기본값은_그대로다(self):
        self.assertEqual(decide(prev_fails=0, cur_fails=1, notified=False), "quiet")

    def test_임계값_2는_두_번째에_알린다(self):
        self.assertFalse(self.run_once(2))
        self.assertTrue(self.run_once(2))
        self.assertEqual(len(self.sent), 1)


class TestCli(unittest.TestCase):
    """웹훅이 실제로 연결됐는지 사람이 직접 확인할 방법이 있어야 한다."""

    def test_test_옵션은_시험_메시지를_보낸다(self):
        import notify
        sent, orig = [], notify.post
        notify.post = lambda text, webhook=None: (sent.append(text), True)[1]
        try:
            rc = notify.cli(["--test"])
        finally:
            notify.post = orig
        self.assertEqual(rc, 0)
        self.assertEqual(len(sent), 1)
        self.assertIn("시험", sent[0])

    def test_전송_실패하면_0이_아닌_값을_돌려준다(self):
        # 크론/셸에서 성공으로 오인하면 연결 안 된 걸 모른다.
        import notify
        orig = notify.post
        notify.post = lambda text, webhook=None: False
        try:
            self.assertNotEqual(notify.cli(["--test"]), 0)
        finally:
            notify.post = orig

    def test_실패_보고를_셸에서_넘길_수_있다(self):
        # run.sh 의 push 실패처럼 파이썬 밖에서 생긴 실패도 같은 통로로 보낸다.
        import tempfile
        import notify
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "s.json"
            sent, orig = [], notify.post
            notify.post = lambda text, webhook=None: (sent.append(text), True)[1]
            try:
                notify.cli(["--job", "시세 push", "--failed", "git push",
                            "--threshold", "1", "--state", str(path)])
            finally:
                notify.post = orig
        self.assertEqual(len(sent), 1)
        self.assertIn("시세 push", sent[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
