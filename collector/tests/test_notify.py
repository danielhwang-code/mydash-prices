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


class TestValidWebhook(unittest.TestCase):
    """붙여넣기 사고를 저장 전에 막는다.

    실제로 겪은 일: 입력이 보이지 않는 프롬프트에 시험 명령을 세 번 붙여넣어
    그 명령문이 웹훅 URL 로 저장됐다. 형식 검사가 있었으면 그 자리에서 걸렸다.
    """

    def ok(self, url):
        from notify import valid_webhook
        self.assertTrue(valid_webhook(url), f"거부되면 안 된다: {url[:40]}")

    def no(self, url):
        from notify import valid_webhook
        self.assertFalse(valid_webhook(url), f"통과하면 안 된다: {url[:40]}")

    def test_진짜_웹훅_형식을_받는다(self):
        self.ok("https://discord.com/api/webhooks/1234567890123456789/"
                "aBcD-efGh_ijKlMnOpQrStUvWxYz0123456789aBcDeFgHiJkLmNoPqRsTuVwXyZ01")

    def test_옛_도메인도_받는다(self):
        self.ok("https://discordapp.com/api/webhooks/123456789012345678/"
                "abcDEF-123_456ghiJKLmnoPQRstuVWXyz0123456789abcDEFghiJKLmnoPQRstu")

    def test_명령문은_거부한다(self):
        self.no(". ~/.mydash_env && python3 ~/mydash/collector/notify.py --test")

    def test_빈값과_공백은_거부한다(self):
        self.no("")
        self.no("   ")

    def test_다른_서비스_웹훅은_거부한다(self):
        self.no("https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXXXXXXXXXX")

    def test_주소는_맞지만_토큰이_없으면_거부한다(self):
        self.no("https://discord.com/api/webhooks/1234567890123456789")
        self.no("https://discord.com/api/webhooks/1234567890123456789/")

    def test_앞뒤_공백은_다듬어_받는다(self):
        # 붙여넣을 때 흔하다.
        self.ok("  https://discord.com/api/webhooks/1234567890123456789/"
                "aBcD-efGh_ijKlMnOpQrStUvWxYz0123456789aBcDeFgHiJkLmNoPqRsTuVwXyZ01  ")

    def test_뒤에_다른_말이_붙으면_거부한다(self):
        self.no("https://discord.com/api/webhooks/123456789012345678/"
                "abcDEFghiJKLmnoPQRstuVWXyz0123456789abcDEFghiJKLmnoPQRstuVWXyz01 && echo hi")


class TestUpsertEnv(unittest.TestCase):
    """~/.mydash_env 를 고칠 때 기존 키(ECOS_KEY)를 잃으면 안 된다."""

    def up(self, text, value="V"):
        from notify import upsert_env
        return upsert_env(text, "DISCORD_WEBHOOK", value)

    def test_없으면_덧붙인다(self):
        out = self.up('export ECOS_KEY="abc"\n')
        self.assertIn('export ECOS_KEY="abc"', out)
        self.assertIn('export DISCORD_WEBHOOK="V"', out)

    def test_있으면_바꿔친다_중복되지_않는다(self):
        out = self.up('export ECOS_KEY="abc"\nexport DISCORD_WEBHOOK="old"\n')
        self.assertEqual(out.count("DISCORD_WEBHOOK"), 1)
        self.assertNotIn("old", out)
        self.assertIn('export ECOS_KEY="abc"', out)

    def test_빈_파일에도_쓴다(self):
        self.assertIn('export DISCORD_WEBHOOK="V"', self.up(""))

    def test_줄바꿈으로_끝나지_않아도_줄이_붙지_않는다(self):
        out = self.up('export ECOS_KEY="abc"')
        self.assertIn('export ECOS_KEY="abc"\n', out)
        self.assertTrue(out.endswith("\n"))

    def test_비슷한_이름의_키는_건드리지_않는다(self):
        out = self.up('export DISCORD_WEBHOOK_OLD="keep"\n')
        self.assertIn('DISCORD_WEBHOOK_OLD="keep"', out)
        self.assertIn('export DISCORD_WEBHOOK="V"', out)


class TestSetWebhook(unittest.TestCase):
    """파일을 실제로 쓰는 부분. 이번에 깨진 지점이다."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.env = pathlib.Path(self.dir.name) / ".mydash_env"
        self.env.write_text('export ECOS_KEY="abc"\n', encoding="utf-8")
        self.sent = []

    def tearDown(self):
        self.dir.cleanup()

    GOOD = ("https://discord.com/api/webhooks/1234567890123456789/"
            "aBcD-efGh_ijKlMnOpQrStUvWxYz0123456789aBcDeFgHiJkLmNoPqRsTuVwXyZ01")

    def run_with(self, typed, ok=True):
        import notify
        orig = notify.post
        notify.post = lambda text, webhook=None: (self.sent.append((text, webhook)), ok)[1]
        try:
            return notify.set_webhook(str(self.env), prompt=lambda _: typed)
        finally:
            notify.post = orig

    def test_형식이_틀리면_파일을_건드리지_않는다(self):
        # 실제 사고: 시험 명령문이 그대로 저장됐다.
        rc = self.run_with(". ~/.mydash_env && python3 ~/mydash/collector/notify.py --test")
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.env.read_text(encoding="utf-8"), 'export ECOS_KEY="abc"\n')
        self.assertEqual(self.sent, [], "저장도 안 했는데 발송했다")

    def test_올바른_입력은_저장하고_시험_발송한다(self):
        self.assertEqual(self.run_with(self.GOOD), 0)
        body = self.env.read_text(encoding="utf-8")
        self.assertIn(f'export DISCORD_WEBHOOK="{self.GOOD}"', body)
        self.assertIn('export ECOS_KEY="abc"', body, "기존 키를 잃었다")
        self.assertEqual(len(self.sent), 1)

    def test_방금_넣은_URL_로_발송한다(self):
        # 파일에 쓴 뒤 환경변수를 다시 읽지 않으므로, 값을 직접 넘겨야 한다.
        self.run_with(self.GOOD)
        self.assertEqual(self.sent[0][1], self.GOOD)

    def test_권한을_600_으로_조인다(self):
        import stat
        self.env.chmod(0o644)
        self.run_with(self.GOOD)
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)

    def test_두_번_넣어도_한_줄이다(self):
        self.run_with(self.GOOD)
        self.run_with(self.GOOD)
        body = self.env.read_text(encoding="utf-8")
        self.assertEqual(body.count("DISCORD_WEBHOOK"), 1)

    def test_파일이_없어도_만든다(self):
        self.env.unlink()
        self.assertEqual(self.run_with(self.GOOD), 0)
        self.assertTrue(self.env.exists())

    def test_발송이_실패하면_0이_아니다(self):
        # 저장은 됐지만 URL 이 폐기됐을 수 있다. 성공으로 보이면 안 된다.
        rc = self.run_with(self.GOOD, ok=False)
        self.assertNotEqual(rc, 0)
        self.assertIn("DISCORD_WEBHOOK", self.env.read_text(encoding="utf-8"))

    def test_앞뒤_공백은_다듬어_저장한다(self):
        self.run_with("  " + self.GOOD + "  ")
        self.assertIn(f'"{self.GOOD}"', self.env.read_text(encoding="utf-8"))

    def test_입력을_중단해도_트레이스백을_내지_않는다(self):
        # Ctrl+C 나 파이프 입력으로 흔히 일어난다.
        for exc in (EOFError, KeyboardInterrupt):
            with self.subTest(exc=exc):
                def boom(_):
                    raise exc()
                import notify
                rc = notify.set_webhook(str(self.env), prompt=boom)
                self.assertNotEqual(rc, 0)
                self.assertEqual(self.env.read_text(encoding="utf-8"),
                                 'export ECOS_KEY="abc"\n')


class TestPasteMarkers(unittest.TestCase):
    """붙여넣기 표시문자(bracketed paste)를 흘리는 터미널이 있다.

    실제로 겪음: VPS 셸에 붙여넣으면 앞에 `[200~`, 뒤에 `[201~` 가 그대로 들어온다.
    사람 눈에는 URL 만 보이는데 값은 오염돼 있다.
    """

    GOOD = ("https://discord.com/api/webhooks/1234567890123456789/"
            "aBcD-efGh_ijKlMnOpQrStUvWxYz0123456789aBcDeFgHiJkLmNoPqRsTuVwXyZ01")

    def test_ESC_가_살아있는_형태를_받는다(self):
        from notify import valid_webhook
        self.assertTrue(valid_webhook("\x1b[200~" + self.GOOD + "\x1b[201~"))

    def test_ESC_가_먹힌_형태도_받는다(self):
        # 터미널이 ESC 만 삼키면 화면·값에 `[200~` 라는 글자가 남는다.
        from notify import valid_webhook
        self.assertTrue(valid_webhook("[200~" + self.GOOD + "[201~"))

    def test_앞쪽만_붙어도_받는다(self):
        from notify import valid_webhook
        self.assertTrue(valid_webhook("[200~" + self.GOOD))

    def test_저장될_때는_표시문자가_빠진다(self):
        import tempfile
        import notify
        with tempfile.TemporaryDirectory() as d:
            env = pathlib.Path(d) / ".mydash_env"
            env.write_text('export ECOS_KEY="abc"\n', encoding="utf-8")
            orig, sent = notify.post, []
            notify.post = lambda text, webhook=None: (sent.append(webhook), True)[1]
            try:
                notify.set_webhook(str(env), prompt=lambda _: "[200~" + self.GOOD + "[201~")
            finally:
                notify.post = orig
            body = env.read_text(encoding="utf-8")
        self.assertIn(f'export DISCORD_WEBHOOK="{self.GOOD}"', body)
        self.assertNotIn("200~", body)
        self.assertEqual(sent[0], self.GOOD, "발송도 깨끗한 값으로 해야 한다")

    def test_표시문자를_벗겨도_명령문은_여전히_거부한다(self):
        from notify import valid_webhook
        self.assertFalse(valid_webhook("[200~. ~/.mydash_env && python3 notify.py --test[201~"))


class TestRequest(unittest.TestCase):
    """디스코드 앞단 Cloudflare 는 파이썬 기본 User-Agent 를 막는다.

    실측(2026-09-15 VPS): 기본 UA → HTTP 403 `error code: 1010`,
    브라우저 UA → 204. 헤더 하나가 빠지면 알림 전체가 죽는다.
    """

    URL = ("https://discord.com/api/webhooks/1234567890123456789/"
           "aBcD-efGh_ijKlMnOpQrStUvWxYz0123456789aBcDeFgHiJkLmNoPqRsTuVwXyZ01")

    def req(self):
        from notify import build_request
        return build_request(self.URL, "안녕")

    def test_User_Agent_를_보낸다(self):
        ua = self.req().get_header("User-agent")
        self.assertTrue(ua, "User-Agent 가 없으면 Cloudflare 가 1010 으로 막는다")
        self.assertNotIn("urllib", ua.lower())
        self.assertNotIn("python", ua.lower())

    def test_JSON_으로_보낸다(self):
        import json
        r = self.req()
        self.assertEqual(r.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(r.data.decode("utf-8"))["content"], "안녕")

    def test_주소는_그대로_쓴다(self):
        self.assertEqual(self.req().full_url, self.URL)

    def test_한글도_깨지지_않는다(self):
        import json
        from notify import build_request
        r = build_request(self.URL, "⚠️ 시세 수집 실패 — 연속 3회")
        self.assertIn("연속 3회", json.loads(r.data.decode("utf-8"))["content"])


class TestPostErrors(unittest.TestCase):
    """실패했을 때 원인을 화면에 남긴다.

    403 의 본문이 `error code: 1010`(Cloudflare 차단)인지 디스코드가 준
    `Invalid Webhook Token` 인지에 따라 대응이 완전히 다르다.
    실제로 본문이 안 보여 진단을 한 번 더 돌려야 했다.
    """

    URL = ("https://discord.com/api/webhooks/1234567890123456789/"
           "aBcD-efGh_ijKlMnOpQrStUvWxYz0123456789aBcDeFgHiJkLmNoPqRsTuVwXyZ01")

    def post_with(self, exc):
        import contextlib
        import io
        import notify
        import urllib.request
        orig = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(exc)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                ok = notify.post("테스트", webhook=self.URL)
        finally:
            urllib.request.urlopen = orig
        return ok, buf.getvalue()

    def test_HTTP_오류는_상태코드와_본문을_남긴다(self):
        import io
        import urllib.error
        exc = urllib.error.HTTPError(self.URL, 403, "Forbidden", {},
                                     io.BytesIO(b"error code: 1010"))
        ok, out = self.post_with(exc)
        self.assertFalse(ok)
        self.assertIn("403", out)
        self.assertIn("1010", out, "본문이 없으면 Cloudflare 차단인지 알 수 없다")

    def test_연결_오류도_삼키지_않는다(self):
        import urllib.error
        ok, out = self.post_with(urllib.error.URLError("연결 거부"))
        self.assertFalse(ok)
        self.assertIn("연결 거부", out)

    def test_예상못한_예외에도_수집이_멈추지_않는다(self):
        # 알림 때문에 수집 전체가 죽으면 본말전도다.
        ok, out = self.post_with(TimeoutError("시간 초과"))
        self.assertFalse(ok)
        self.assertTrue(out.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
