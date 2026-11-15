"""Use the site's own check-in page and its normal verification flow."""
import logging
import os
import json
import re
import time
from collections import Counter
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as BrowserTimeout, sync_playwright

logger = logging.getLogger("GLaDOS")
BASE_URL = "https://glados.cloud"
CHECKIN_PAGE = BASE_URL + "/console/checkin"
CHECKIN_PATH = "/api/user/checkin"


class VerificationDiagnostics:
    """Collect bounded metadata; never record URLs, headers, bodies or tokens."""
    def __init__(self, page, browser_version):
        self.page = page
        self.browser_version = browser_version
        self.statuses = Counter()
        self.failures = Counter()
        self.error_codes = set()
        self.api_loaded = False
        self.page_date_delta_seconds = None
        page.on("response", self.on_response)
        page.on("requestfailed", self.on_request_failed)
        page.on("console", self.on_console)

    def on_response(self, response):
        location = urlsplit(response.url)
        if location.hostname == "challenges.cloudflare.com":
            self.statuses[str(response.status)] += 1
            request = response.request
            # api.js can redirect to a versioned URL. Match its redirect chain
            # rather than marking a successfully loaded widget as missing.
            for _ in range(8):
                source = urlsplit(request.url)
                if source.hostname == "challenges.cloudflare.com" and source.path == "/turnstile/v0/api.js":
                    self.api_loaded = self.api_loaded or response.ok
                    break
                request = request.redirected_from
                if request is None:
                    break
        elif location.hostname == "glados.cloud" and location.path == "/console/checkin":
            try:
                server_time = parsedate_to_datetime(response.headers["date"]).timestamp()
                self.page_date_delta_seconds = round(time.time() - server_time)
            except (KeyError, ValueError, TypeError, OverflowError):
                pass

    def on_request_failed(self, request):
        if urlsplit(request.url).hostname == "challenges.cloudflare.com":
            match = re.search(r"net::ERR_[A-Z_]+", request.failure or "")
            self.failures[match.group() if match else "other"] += 1

    def on_console(self, message):
        # Cloudflare's six-digit public error codes only, never raw console text.
        content = message.text
        if "turnstile" in content.lower():
            self.error_codes.update(re.findall(r"(?:error|code)\s*[:=]?\s*([1-6]\d{5})\b", content, re.I))

    def snapshot(self):
        frames = [frame for frame in self.page.frames
                  if urlsplit(frame.url).hostname == "challenges.cloudflare.com"]
        interactive_checkbox_visible = False
        for frame in frames:
            try:
                checkbox = frame.get_by_role("checkbox")
                if checkbox.count() and checkbox.first.is_visible():
                    interactive_checkbox_visible = True
            except Exception:
                pass
        return {
            "browser_version": self.browser_version,
            "verification_script_loaded": self.api_loaded,
            "cloudflare_http_statuses": dict(self.statuses),
            "cloudflare_network_errors": dict(self.failures),
            "turnstile_error_codes": sorted(self.error_codes),
            "challenge_frame_count": len(frames),
            "interactive_checkbox_visible": interactive_checkbox_visible,
            # A cached response Date is not an authoritative clock check.
            "page_date_delta_seconds": self.page_date_delta_seconds,
        }


def browser_cookies(cookie):
    """Preserve cookie names and values, including '=' in session values."""
    pairs = []
    for field in cookie.split(";"):
        name, separator, value = field.strip().partition("=")
        if separator and name:
            pairs.append({"name": name, "value": value, "url": BASE_URL + "/"})
    return pairs


def failure(message, reason):
    return {"code": -2, "message": message, "reason": reason}


def perform_checkin(browser, cookie, timeout_ms=120000):
    """One isolated context and at most one submission per account.

    Interactive verification and device/login failures are reported, not bypassed.
    No screenshots, traces, cookies or verification tokens are saved to logs.
    """
    context = browser.new_context(locale="en-US", timezone_id="Asia/Shanghai")
    diagnostic = None
    try:
        context.add_cookies(browser_cookies(cookie))
        page = context.new_page()
        diagnostic = VerificationDiagnostics(page, browser.version)
        response = page.goto(CHECKIN_PAGE, wait_until="domcontentloaded", timeout=45000)
        if response is None or response.status >= 400:
            status = response.status if response else "no response"
            return failure(f"签到页面加载失败 (HTTP {status})", "page-load")
        button = page.locator("button.ckb")
        try:
            button.wait_for(state="visible", timeout=30000)
        except BrowserTimeout:
            if not urlsplit(page.url).path.startswith("/console"):
                return failure("浏览器登录态失效，请重新登录并更新 COOKIES", "login")
            return failure("签到按钮未出现：页面或验证状态需要人工检查", "page-load")

        # The frontend refreshes its challenge and waits for Turnstile itself.
        page.wait_for_timeout(3000)
        with page.expect_response(
            lambda item: urlsplit(item.url).netloc == "glados.cloud"
            and urlsplit(item.url).path == CHECKIN_PATH
            and item.request.method == "POST",
            timeout=timeout_ms,
        ) as pending:
            button.click(timeout=15000)
        checkin_response = pending.value
        if not checkin_response.ok:
            return failure(f"签到接口返回 HTTP {checkin_response.status}", "http")
        try:
            payload = checkin_response.json()
        except Exception:
            return failure("签到接口没有返回 JSON，请检查网站验证状态", "response")
        if not isinstance(payload, dict) or "code" not in payload:
            return failure("签到接口返回结构已变化，未确认签到成功", "response")

        request_data = checkin_response.request.post_data_json
        state = request_data.get("tsState", "not-provided") if isinstance(request_data, dict) else "unknown"
        logger.info("浏览器签到 HTTP %d，验证状态: %s，结果原因: %s",
                    checkin_response.status, state, payload.get("reason", "-"))
        if payload.get("reason") == "device-mismatch":
            for key in ("loginDevice", "currentDevice"):
                description = payload.get(key)
                if isinstance(description, str):
                    logger.info("%s: %s", key, description.replace("\n", " ")[:120])
            payload["message"] = "登录设备与运行设备不一致，请在运行环境重新登录；原始会话不能直接迁移"
        elif payload.get("reason") == "turnstile":
            payload["message"] = "Cloudflare 验证未完成，本次未签到；请查看 Verification diagnostics"
        return payload
    except BrowserTimeout:
        return failure("浏览器签到等待超时，可能需要人工验证；未确认签到成功", "timeout")
    finally:
        if diagnostic is not None:
            try:
                logger.info("Verification diagnostics: %s", json.dumps(diagnostic.snapshot(), ensure_ascii=True))
            except Exception:
                logger.info("Verification diagnostics: unavailable")
        context.close()


def checkin(cookie):
    with sync_playwright() as engine:
        options = {"headless": os.getenv("GLADOS_HEADLESS", "0") == "1"}
        channel = os.getenv("GLADOS_BROWSER_CHANNEL")
        if channel:
            options["channel"] = channel
        browser = engine.chromium.launch(**options)
        try:
            return perform_checkin(browser, cookie)
        finally:
            browser.close()
