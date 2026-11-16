"""Exercise the real browser click and API response against an isolated page."""
import json
import os
import unittest
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import browser_checkin
import checkin

COOKIE = "gld:sess=fake==; gld:sess.sig=signature"


class BrowserFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = sync_playwright().start()
        cls.browser = cls.engine.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.engine.stop()

    def run_fixture(self, payload, status=200, history=None, ledger_valid=True, verification_ready=True, expected_submissions=1):
        submissions = []
        real_new_context = self.browser.new_context

        def new_context(**options):
            context = real_new_context(**options)

            def route(request_route):
                request = request_route.request
                if request.url.endswith(browser_checkin.CHECKIN_PATH) and request.method == "POST":
                    submissions.append(request.post_data_json)
                    request_route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))
                elif request.url.endswith('/api/user/points'):
                    data = {"code": 0 if ledger_valid else 7, "history": history or []}
                    request_route.fulfill(content_type="application/json", body=json.dumps(data))
                elif request.url.endswith(browser_checkin.CHALLENGE_PATH):
                    request_route.fulfill(content_type="application/json", body=json.dumps({"code": 0, "nonce": "fixture", "turnstile": {"sitekey": "fixture"}}))
                else:
                    html = '''<script>
                      fetch('/api/user/checkin/challenge').then(r=>r.json()).then(()=>{
                        window.turnstile={getResponse:()=>READY ? 'fixture' : ''};
                      });
                    </script><button class="ckb" onclick="fetch('/api/user/checkin', {
                      method:'POST', headers:{'Content-Type':'application/json'},
                      body:JSON.stringify({token:location.hostname,nonce:'fixture',proof:'fixture',tsState:'ok',turnstile:'fixture'})
                    })">Check in</button>'''
                    request_route.fulfill(status=200, content_type="text/html", body=html.replace('READY', json.dumps(verification_ready)))

            context.route("**/*", route)
            return context

        with patch.object(self.browser, "new_context", side_effect=new_context):
            result = browser_checkin.perform_checkin(self.browser, COOKIE, timeout_ms=5000, verification_timeout_ms=600)
        self.assertEqual(len(submissions), expected_submissions)
        if submissions:
            self.assertEqual(submissions[0]["tsState"], "ok")
        self.assertEqual(len(self.browser.contexts), 0, "Account context must be closed")
        return result

    def test_success_preserves_api_result(self):
        result = self.run_fixture({"code": 0, "message": "Checkin success, got 2 points", "points": 2})
        self.assertEqual(result["points"], 2)

    def test_verification_failure_stays_failed(self):
        result = self.run_fixture({"code": 8, "reason": "turnstile", "message": "Cloudflare verification failed"})
        self.assertEqual(checkin.classify_checkin(result["code"], result["message"]), "fail")

    def test_device_mismatch_requires_login(self):
        result = self.run_fixture({"code": 4, "reason": "device-mismatch", "message": "mismatch"})
        self.assertEqual(result["reason"], "device-mismatch")
        self.assertEqual(checkin.classify_checkin(result["code"], result["message"]), "fail")

    def test_http_failure_not_misreported_as_success(self):
        result = self.run_fixture({"code": 0}, status=503)
        self.assertEqual(result["reason"], "http")

    def test_already_checked_in_skips_post_and_preserves_today_award(self):
        row = {"id": "1", "business": "checkin", "time": datetime.now(timezone.utc).isoformat(), "change": 7}
        result = self.run_fixture({"code": 0}, history=[row], expected_submissions=0)
        self.assertTrue(result["repeated"])
        self.assertEqual(result["today_points"], 7)

    def test_unverifiable_history_stops_without_submitting(self):
        result = self.run_fixture({"code": 0}, ledger_valid=False, expected_submissions=0)
        self.assertEqual(result["reason"], "precheck")

    def test_turnstile_must_be_ready_before_clicking(self):
        result = self.run_fixture({"code": 0}, verification_ready=False, expected_submissions=0)
        self.assertEqual(result["reason"], "verification-pending")


class ResultTests(unittest.TestCase):
    def test_checkin_post_is_never_retried_when_its_response_is_lost(self):
        with patch.dict(os.environ, {"GLADOS_CHECKIN_MODE": "http"}), patch.object(checkin.time, "sleep"), patch.object(checkin.requests.Session, "post", side_effect=checkin.requests.exceptions.Timeout("test")) as post:
            with checkin.requests.Session() as session, self.assertRaises(checkin.requests.exceptions.Timeout):
                checkin.checkin_request(session, {"cookie": COOKIE})
            self.assertEqual(post.call_count, 1)

    def test_ledger_uses_utc_plus_eight_and_excludes_other_credits(self):
        now = datetime(2026, 11, 16, 0, 1, tzinfo=browser_checkin.SITE_TIMEZONE)
        row = {"id": 1, "business": "checkin", "time": "2026-11-15T16:00:30Z", "change": 5}
        rows = [row, row, {"id": 2, "business": "exchange", "time": row["time"], "change": -500},
                {"id": 3, "business": "checkin", "time": "2026-11-15T15:59:59Z", "change": 100}]
        self.assertEqual(browser_checkin.today_checkin({"code": 0, "history": rows}, now), {"checked": True, "earned": 5})
        self.assertIsNone(browser_checkin.today_checkin({"code": None, "history": rows}, now))
        self.assertIsNone(browser_checkin.today_checkin({"code": 0, "history": [{**row, "time": "2026-11-16T00:00:00"}]}, now))
        milliseconds = datetime(2026, 11, 15, 16, 0, 30, tzinfo=timezone.utc).timestamp() * 1000
        self.assertEqual(browser_checkin.today_checkin({"code": 0, "history": [{**row, "time": milliseconds}]}, now), {"checked": True, "earned": 5})

    def test_failure_wording_cannot_be_misclassified_as_completed(self):
        for code, message in [(-2, "无法核对今日签到记录，本次未提交，避免重复签到"), (8, "Cloudflare failed; already checked?"), (None, "got 2 points"), (False, "success"), (0.5, "success")]:
            self.assertEqual(checkin.classify_checkin(code, message), "fail")
        with patch.object(checkin, "checkin_request", return_value={"code": -2, "message": "避免重复签到", "reason": "precheck"}), patch.object(checkin, "api_get", return_value={"data": {}}):
            with checkin.requests.Session() as session:
                result = checkin.checkin_account(session, COOKIE, 1)
        self.assertEqual(result["result"], "fail")

    def test_diagnostics_do_not_export_tokens_or_urls(self):
        page = SimpleNamespace(on=lambda *args: None, frames=[])
        diagnostic = browser_checkin.VerificationDiagnostics(page, "test-browser")
        diagnostic.on_response(SimpleNamespace(
            url="https://challenges.cloudflare.com/turnstile/v0/api.js?secret=never-export",
            status=200, ok=True, request=SimpleNamespace(url="https://challenges.cloudflare.com/turnstile/v0/api.js", redirected_from=None)))
        diagnostic.on_response(SimpleNamespace(
            url="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/pat/never-export",
            status=401, ok=False, request=SimpleNamespace(url="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/pat/never-export", redirected_from=None)))
        diagnostic.on_console(SimpleNamespace(text="[Cloudflare Turnstile] Error: 600010; token=123456; secret=never-export"))
        diagnostic.on_request_failed(SimpleNamespace(
            url="https://challenges.cloudflare.com/private/never-export",
            failure="net::ERR_CONNECTION_RESET"))
        snapshot = diagnostic.snapshot()
        self.assertTrue(snapshot["verification_script_loaded"])
        self.assertEqual(snapshot["turnstile_error_codes"], ["600010"])
        self.assertEqual(snapshot["cloudflare_http_statuses"]["401"], 1)
        self.assertNotIn("never-export", json.dumps(snapshot))
        self.assertNotIn("https://", json.dumps(snapshot))

    def test_diagnostics_follow_verification_script_redirect(self):
        page = SimpleNamespace(on=lambda *args: None, frames=[])
        diagnostic = browser_checkin.VerificationDiagnostics(page, "test-browser")
        original = SimpleNamespace(url="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit", redirected_from=None)
        redirected = SimpleNamespace(url="https://challenges.cloudflare.com/turnstile/v0/versioned/api.js", redirected_from=original)
        diagnostic.on_response(SimpleNamespace(url=redirected.url, status=200, ok=True, request=redirected))
        self.assertTrue(diagnostic.snapshot()["verification_script_loaded"])

    def test_cookie_values_and_prefixes_preserved(self):
        values = browser_checkin.browser_cookies(COOKIE)
        self.assertEqual(values[0]["name"], "gld:sess")
        self.assertEqual(values[0]["value"], "fake==")

    def test_verify_run_never_sends_notifications(self):
        with patch.dict(os.environ, {"GLADOS_VERIFY_ONLY": "1", "SERVERCHAN_KEY": "fake"}), patch.object(checkin.requests, "post") as post:
            self.assertEqual(checkin.push_all("test", "test"), (0, 0))
            post.assert_not_called()

    def test_repeated_flag_is_not_new_points(self):
        with patch.object(checkin, "checkin_request", return_value={"code": 0, "message": "already", "repeated": True}), patch.object(checkin, "api_get", return_value={"data": {}}):
            with checkin.requests.Session() as session:
                result = checkin.checkin_account(session, COOKIE, 1)
        self.assertEqual(result["result"], "repeat")


if __name__ == "__main__":
    unittest.main()
