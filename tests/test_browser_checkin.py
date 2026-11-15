"""Exercise the real browser click and API response against an isolated page."""
import json
import os
import unittest
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

    def run_fixture(self, payload, status=200):
        submissions = []
        real_new_context = self.browser.new_context

        def new_context(**options):
            context = real_new_context(**options)

            def route(request_route):
                request = request_route.request
                if request.url.endswith(browser_checkin.CHECKIN_PATH):
                    submissions.append(request.post_data_json)
                    request_route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))
                else:
                    html = '''<button class="ckb" onclick="fetch('/api/user/checkin', {
                      method:'POST', headers:{'Content-Type':'application/json'},
                      body:JSON.stringify({token:location.hostname,nonce:'fixture',proof:'fixture',tsState:'ok',turnstile:'fixture'})
                    })">Check in</button>'''
                    request_route.fulfill(status=200, content_type="text/html", body=html)

            context.route("**/*", route)
            return context

        with patch.object(self.browser, "new_context", side_effect=new_context):
            result = browser_checkin.perform_checkin(self.browser, COOKIE, timeout_ms=5000)
        self.assertEqual(len(submissions), 1)
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


class ResultTests(unittest.TestCase):
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
