"""Login flow management for Xianyu."""

import io
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple
from playwright.async_api import Page
from xianyu_mcp.config import get_settings
from xianyu_mcp.constants import (
    XIANYU_BASE_URL,
    LOGIN_SELECTORS,
    get_selectors,
)
from xianyu_mcp.errors import LoginError, ErrorCode
from xianyu_mcp.infrastructure.browser.page_utils import (
    random_delay,
)
from xianyu_mcp.infrastructure.storage.cookie_store import get_cookie_store
from xianyu_mcp.logging import get_logger

logger = get_logger("login_flow")

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency fallback
    Image = None


def _compress_image_bytes(image_bytes: bytes, max_edge: int = 360) -> bytes:
    """Best-effort image optimization for QR screenshots."""
    if Image is None:
        return image_bytes

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size
            longest_edge = max(width, height)
            if longest_edge > max_edge:
                scale = max_edge / float(longest_edge)
                new_size = (
                    max(1, int(width * scale)),
                    max(1, int(height * scale)),
                )
                resampling = getattr(Image, "Resampling", Image).NEAREST
                img = img.resize(new_size, resampling)

            if img.mode not in {"L", "1"}:
                img = img.convert("L")

            output = io.BytesIO()
            img.save(output, format="PNG", optimize=True, compress_level=9)
            optimized = output.getvalue()
            if optimized and len(optimized) < len(image_bytes):
                return optimized
    except Exception as e:
        logger.debug(f"Image compression skipped: {e}")

    return image_bytes


def _save_image_to_file(image_bytes: bytes, filename: str) -> str:
    """Save image bytes to file and return the file path."""
    settings = get_settings()
    save_dir = Path(settings.screenshot_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / filename
    optimized_bytes = _compress_image_bytes(image_bytes)
    file_path.write_bytes(optimized_bytes)
    logger.info(f"Image saved to: {file_path}")
    return str(file_path.absolute())


class LoginStatus(Enum):
    """Login status enumeration."""
    WAITING_SCAN = "waiting_scan"           # 等待扫码
    WAITING_AUTO_LOGIN = "waiting_auto_login"  # 已扫码，等待自动登录
    NEED_FACE_VERIFY = "need_face_verify"   # 需要人脸识别
    LOGIN_SUCCESS = "login_success"         # 登录成功
    QR_EXPIRED = "qr_expired"               # 二维码过期
    TIMEOUT = "timeout"                     # 超时
    ERROR = "error"                         # 出错


class LoginFlow:
    """Manages the login flow for Xianyu."""
    def __init__(self, page: Page):
        self.page = page
        self.settings = get_settings()

    def _get_iframe_selector(self) -> Optional[str]:
        """Get the iframe selector for login elements."""
        return LOGIN_SELECTORS.get("login_iframe")

    async def check_login_status(self) -> Tuple[bool, str]:
        """
        Check if the user is logged in.
        Returns (is_logged_in, message).

        Detection logic:
        1. Check if nickname element exists and has valid text - if yes, user IS logged in
        2. Otherwise, not logged in
        """
        page = self.page
        try:
            logger.info("Checking login status...")
            await page.goto(XIANYU_BASE_URL, timeout=self.settings.page_timeout)
            await random_delay(500, 1000)
            # Wait for page to load
            await page.wait_for_load_state("networkidle", timeout=self.settings.page_timeout)

            # First check: verify nickname element has valid content
            for selector in get_selectors(LOGIN_SELECTORS, "logged_in_indicator"):
                try:
                    locator = page.locator(selector)
                    if await locator.count() > 0 and await locator.first.is_visible():
                        # Get the text content and verify it's not empty
                        text_content = await locator.first.text_content()
                        if text_content and text_content.strip():
                            # Additional check: text should not be default/placeholder
                            stripped_text = text_content.strip()
                            if stripped_text and stripped_text not in ["登录", "Login", ""]:
                                logger.info(f"User is logged in, nickname: {stripped_text}")
                                return True, f"User is logged in ({stripped_text})"
                except Exception:
                    continue

            logger.info("User is not logged in")
            return False, "User is not logged in"
        except Exception as e:
            logger.error(f"Error checking login status: {e}")
            return False, f"Error checking login status: {e}"

    async def get_login_qrcode(self) -> Tuple[Optional[str], str]:
        """
        Get the login QR code.
        Flow:
        1. Open homepage
        2. Check if login iframe already exists
        3. If not, click login button
        4. Wait for iframe and QR code canvas
        5. Screenshot the canvas and save to file

        Returns (file_path, message).
        """
        page = self.page
        try:
            logger.info("Getting login QR code...")
            # Step 1: Open homepage
            await page.goto(XIANYU_BASE_URL, timeout=self.settings.page_timeout)
            await random_delay(500, 1000)
            await page.wait_for_load_state("domcontentloaded", timeout=self.settings.page_timeout)
            iframe_selector = self._get_iframe_selector()
            iframe_exists = False
            # Step 2: Check if login iframe already exists
            try:
                await page.wait_for_selector(iframe_selector, timeout=5000)
                iframe_exists = True
                logger.info("Login iframe already exists")
            except Exception:
                logger.info("Login iframe not found, will click login button")
            # Step 3: If iframe doesn't exist, click login button
            if not iframe_exists:
                login_btn_selectors = get_selectors(LOGIN_SELECTORS, "login_button")
                for selector in login_btn_selectors:
                    try:
                        await page.wait_for_selector(selector, timeout=self.settings.page_timeout)
                        await page.click(selector)
                        logger.info(f"Clicked login button: {selector}")
                        break
                    except Exception:
                        continue
                # Wait for iframe to appear
                await page.wait_for_selector(iframe_selector, timeout=self.settings.page_timeout)
                logger.info("Login iframe appeared")
            # Step 4: Get frame locator and wait for QR code
            frame_locator = page.frame_locator(iframe_selector)
            # Wait for QR code container
            qrcode_container_selectors = get_selectors(LOGIN_SELECTORS, "qrcode_container")
            for selector in qrcode_container_selectors:
                try:
                    await frame_locator.locator(selector).wait_for(timeout=self.settings.page_timeout)
                    logger.info(f"QR code container found: {selector}")
                    break
                except Exception:
                    continue
            # Step 5: Screenshot the canvas and save to file
            qrcode_selectors = get_selectors(LOGIN_SELECTORS, "qrcode_image")
            for selector in qrcode_selectors:
                try:
                    canvas_locator = frame_locator.locator(selector)
                    await canvas_locator.wait_for(timeout=self.settings.page_timeout)
                    screenshot_bytes = await canvas_locator.screenshot()
                    if screenshot_bytes:
                        filename = f"login_qrcode_{int(time.time())}.png"
                        file_path = _save_image_to_file(screenshot_bytes, filename)
                        logger.info(f"QR code saved, original size: {len(screenshot_bytes)} bytes")
                        return (
                            file_path,
                            "Login QR code saved. Ask user to scan with Xianyu app, "
                            "wait for explicit '已扫码', then run status check once."
                        )
                except Exception as e:
                    logger.debug(f"Failed to get QR code with selector {selector}: {e}")
                    continue
            raise LoginError(
                "Failed to get login QR code",
                code=ErrorCode.QRCODE_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error getting login QR code: {e}")
            raise LoginError(
                f"Failed to get login QR code: {e}",
                code=ErrorCode.QRCODE_NOT_FOUND
            )

    async def check_login_scan_status(self) -> Tuple[LoginStatus, Optional[str], Optional[str]]:
        """
        Single-shot check of login scan result.

        Three scenarios:
        1. No risk control + scanned: iframe still present (keep-login choice)
           → waiting_confirm (auto-dismisses, iframe disappears soon)
        2. No risk control + scanned: iframe disappeared → login_success
        3. Risk control triggered: face verify QR code appears in iframe
           → need_face_verify with screenshot

        Returns (status, image_path, message).
        """
        if self.page is None or self.page.is_closed():
            return LoginStatus.QR_EXPIRED, None, "Session expired"

        page = self.page
        iframe_selector = self._get_iframe_selector()

        try:
            # --- Case 2: iframe disappeared → login success ---
            login_box = page.locator(iframe_selector)
            iframe_exists = await login_box.count() > 0
            if not iframe_exists:
                logger.info("Login iframe disappeared, login should be successful")
                return await self._extract_login_success()

            # iframe still exists, inspect its content
            frame_locator = page.frame_locator(iframe_selector)

            # --- Case 3: face verify QR code visible → need_face_verify ---
            face_qr_selectors = get_selectors(LOGIN_SELECTORS, "face_verify_qrcode")
            for selector in face_qr_selectors:
                try:
                    face_qr_locator = frame_locator.locator(selector)
                    if await face_qr_locator.count() > 0 and await face_qr_locator.first.is_visible():
                        logger.info("Face verification QR code detected")
                        screenshot_bytes = await face_qr_locator.first.screenshot()
                        if screenshot_bytes:
                            filename = f"face_verify_qrcode_{int(time.time())}.png"
                            file_path = _save_image_to_file(screenshot_bytes, filename)
                            return (
                                LoginStatus.NEED_FACE_VERIFY,
                                file_path,
                                "Face verification QR saved. Ask user to scan it, "
                                "wait for explicit '已扫码', then check again.",
                            )
                except Exception as e:
                    logger.debug(f"Face verify check failed for {selector}: {e}")
                    continue

            # --- Login QR code still visible → waiting_scan ---
            qrcode_selectors = get_selectors(LOGIN_SELECTORS, "qrcode_image")
            for selector in qrcode_selectors:
                try:
                    qr_locator = frame_locator.locator(selector)
                    if await qr_locator.count() > 0 and await qr_locator.first.is_visible():
                        return (
                            LoginStatus.WAITING_SCAN,
                            None,
                            "QR code still visible, user has not scanned yet. "
                            "Ask user to scan and reply '已扫码'.",
                        )
                except Exception:
                    continue

            # --- Case 1: iframe exists but no QR codes → keep-login choice screen ---
            # Auto-wait 5 seconds for confirmation to complete, then re-check
            logger.info("iframe present but no QR codes visible, likely keep-login confirmation. Auto-waiting 5s...")
            import asyncio
            await asyncio.sleep(5)

            # Re-check: iframe should have disappeared after confirmation
            iframe_exists_after_wait = await login_box.count() > 0
            if not iframe_exists_after_wait:
                logger.info("Login iframe disappeared after 5s wait, login successful")
                return await self._extract_login_success()

            # Still present — return waiting_auto_login as fallback
            logger.info("iframe still present after 5s wait")
            return (
                LoginStatus.WAITING_AUTO_LOGIN,
                None,
                "User has scanned, auto login is taking longer than expected. "
                "Try checking again in a few seconds.",
            )

        except Exception as e:
            logger.error(f"Error checking login scan status: {e}")
            return LoginStatus.ERROR, None, f"Error: {e}"

    async def _extract_login_success(self) -> Tuple[LoginStatus, Optional[str], Optional[str]]:
        """Extract login success information."""
        page = self.page
        try:
            # Wait for page content to load
            content_selectors = get_selectors(LOGIN_SELECTORS, "page_content_loaded")
            for selector in content_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=self.settings.page_timeout)
                    break
                except Exception:
                    continue
            # Extract username
            username = None
            nickname_selectors = get_selectors(LOGIN_SELECTORS, "logged_in_indicator")
            for selector in nickname_selectors:
                try:
                    nick_locator = page.locator(selector)
                    if await nick_locator.count() > 0:
                        username = await nick_locator.first.text_content()
                        if username:
                            username = username.strip()
                            break
                except Exception:
                    continue
            if not username:
                username = f"闲鱼用户_{int(time.time())}"
            logger.info(f"Login successful, username: {username}")
            # Call the keep-login API to maintain login state
            await self._try_set_login_settings()
            # Save cookies to file for reuse across tabs
            await self._save_cookies()
            return LoginStatus.LOGIN_SUCCESS, None, f"Login successful: {username}"
        except Exception as e:
            logger.error(f"Failed to extract login info: {e}")
            return LoginStatus.ERROR, None, f"Failed to extract login info: {e}"

    async def _save_cookies(self) -> None:
        """Save current browser cookies to file for reuse across tabs."""
        try:
            context = self.page.context
            cookies = await context.cookies()
            cookie_store = get_cookie_store()
            cookie_store.save(cookies)
            logger.info(f"Saved {len(cookies)} cookies after login")
        except Exception as e:
            logger.warning(f"Failed to save cookies: {e}")

    async def _try_set_login_settings(self) -> bool:
        """
        Call the keep-login API to maintain login state across sessions.
        POST https://passport.goofish.com/ac/account/setLoginSettings.do?fromSite=77&appName=xianyu&bizEntrance=web
        Form: status=0
        Returns True if successful, False otherwise.
        """
        page = self.page
        if page is None:
            return False
        try:
            # Use page.evaluate to send the request with credentials
            result = await page.evaluate("""
                async () => {
                    try {
                        const response = await fetch(
                            'https://passport.goofish.com/ac/account/setLoginSettings.do?fromSite=77&appName=xianyu&bizEntrance=web',
                            {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/x-www-form-urlencoded',
                                    'Referer': 'https://www.goofish.com/'
                                },
                                body: 'status=0',
                                credentials: 'include'
                            }
                        );
                        return {
                            ok: response.ok,
                            status: response.status,
                            text: await response.text()
                        };
                    } catch (e) {
                        return { ok: false, error: e.message };
                    }
                }
            """)
            if result.get("ok"):
                logger.info(f"setLoginSettings API called successfully, status={result.get('status')}, body={result.get('text')}")
                return True
            else:
                logger.warning(f"setLoginSettings API call failed: {result}")
                return False
        except Exception as e:
            logger.warning(f"setLoginSettings API call exception: {e}")
            return False
