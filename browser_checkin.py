"""Use the site's own check-in page and its normal verification flow."""
import logging
import os
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as BrowserTimeout, sync_playwright

logger = logging.getLogger("GLaDOS")
BASE_URL = "https://glados.cloud"
CHECKIN_PAGE = BASE_URL + "/console/checkin"
CHECKIN_PATH = "/api/user/checkin"


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
    try:
        context.add_cookies(browser_cookies(cookie))
        page = context.new_page()
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
            payload["message"] = "Cloudflare 验证未通过，需在运行环境完成人工验证；本次未签到"
        return payload
    except BrowserTimeout:
        return failure("浏览器签到等待超时，可能需要人工验证；未确认签到成功", "timeout")
    finally:
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
