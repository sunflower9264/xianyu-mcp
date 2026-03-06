"""Browser instance management with singleton pattern.

Architecture:
- Login-related tools use a dedicated "login page" that persists across calls.
- All other tools open a new tab (page), execute with injected cookies, then close.
"""

import asyncio
import atexit
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator, Any

from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page

from xianyu_mcp.config import get_settings
from xianyu_mcp.constants import BROWSER_ARGS, DEFAULT_VIEWPORT
from xianyu_mcp.errors import BrowserError, ErrorCode
from xianyu_mcp.infrastructure.browser.login_flow import LoginFlow
from xianyu_mcp.infrastructure.browser.stealth import (
    apply_stealth_to_context,
    get_stealth_context_options,
    get_random_user_agent,
)
from xianyu_mcp.infrastructure.storage.cookie_store import get_cookie_store
from xianyu_mcp.logging import get_logger

logger = get_logger("browser_manager")


class BrowserManager:
    """
    Singleton browser manager for Playwright.

    Provides:
    - get_login_page()  – persistent page for login flows
    - new_tab()         – async context manager that opens an ephemeral tab
                          with saved cookies and auto-closes it on exit
    """

    _instance: Optional["BrowserManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "BrowserManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.settings = get_settings()
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self._login_page: Optional[Page] = None
        self._lifecycle_lock = asyncio.Lock()
        self._cookie_sync_lock = asyncio.Lock()

        # Register cleanup on exit
        atexit.register(self._sync_close)

        self._initialized = True
        logger.info("BrowserManager initialized")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> BrowserContext:
        """Start the browser and return the shared context.

        On first call, also injects any saved cookies from disk so that
        an existing login session is picked up automatically.
        """
        if self.context is not None:
            logger.debug("Browser already started, returning existing context")
            return self.context

        async with self._lifecycle_lock:
            if self.context is not None:
                logger.debug("Browser already started, returning existing context")
                return self.context

            try:
                logger.info("Starting browser...")
                self.playwright = await async_playwright().start()

                stealth_options = get_stealth_context_options()

                self.browser = await self.playwright.chromium.launch(
                    headless=self.settings.headless,
                    args=BROWSER_ARGS,
                    slow_mo=self.settings.slow_mo,
                    ignore_default_args=["--enable-automation"],
                )
                self.context = await self.browser.new_context(
                    viewport=DEFAULT_VIEWPORT,
                    user_agent=get_random_user_agent(),
                    locale=stealth_options.get("locale", "zh-CN"),
                    timezone_id=stealth_options.get("timezone_id", "Asia/Shanghai"),
                    geolocation=stealth_options.get("geolocation"),
                    permissions=stealth_options.get("permissions", []),
                )

                await apply_stealth_to_context(self.context)

                # Inject saved cookies so existing sessions survive restarts
                cookie_store = get_cookie_store()
                cookies = cookie_store.load_valid()
                if cookies:
                    await self.context.add_cookies(cookies)
                    logger.info(f"Injected {len(cookies)} saved cookies into browser context")

                logger.info(
                    f"Browser started successfully (headless={self.settings.headless})"
                )
                return self.context

            except Exception as e:
                logger.error(f"Failed to start browser: {e}")
                await self._close_unlocked()
                raise BrowserError(
                    f"Failed to start browser: {e}",
                    code=ErrorCode.BROWSER_START_FAILED,
                    details={"error": str(e)},
                )

    async def close(self) -> None:
        """Close the browser and cleanup all resources."""
        async with self._lifecycle_lock:
            await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        """Close browser resources.

        Normally called with lifecycle lock held. During process shutdown
        (_sync_close), it may run without the lock as a best-effort cleanup.
        """
        if not any((self._login_page, self.context, self.browser, self.playwright)):
            return

        logger.info("Closing browser...")

        try:
            if self._login_page and not self._login_page.is_closed():
                await self._login_page.close()
        except Exception as e:
            logger.warning(f"Error closing login page: {e}")

        try:
            if self.context:
                await self.context.close()
        except Exception as e:
            logger.warning(f"Error closing context: {e}")

        try:
            if self.browser:
                await self.browser.close()
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")

        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.warning(f"Error stopping playwright: {e}")

        self._login_page = None
        self.context = None
        self.browser = None
        self.playwright = None

        logger.info("Browser closed")

    def _sync_close(self) -> None:
        """Synchronous close for atexit handler."""
        logger.info("Sync close called from atexit...")
        if not any((self._login_page, self.context, self.browser, self.playwright)):
            return

        try:
            # During process exit there should be no concurrent browser operations.
            asyncio.run(self._close_unlocked())
        except RuntimeError:
            # If there is an active event loop, schedule cleanup best-effort.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.close())
            except Exception as e:
                logger.warning(f"Failed to schedule async close during atexit: {e}")
                self._login_page = None
                self.context = None
                self.browser = None
                self.playwright = None
        except Exception as e:
            logger.warning(f"Unexpected error in sync close: {e}")
            self._login_page = None
            self.context = None
            self.browser = None
            self.playwright = None

    # ------------------------------------------------------------------
    # Login page (persistent, for login-related tools only)
    # ------------------------------------------------------------------

    async def get_login_page(self) -> Page:
        """Get or create the dedicated login page.

        This page is kept alive across login tool calls so QR code state,
        iframe state, etc. are preserved between get_qrcode / check_scan.
        """
        if self.context is None:
            await self.start()

        if self._login_page is None or self._login_page.is_closed():
            self._login_page = await self.context.new_page()
            logger.debug("Created new login page")

        return self._login_page

    # ------------------------------------------------------------------
    # Ephemeral tabs (for all non-login tools)
    # ------------------------------------------------------------------

    async def _create_tab(self) -> Page:
        """Create a new tab inside the shared context."""
        if self.context is None:
            await self.start()
        page = await self.context.new_page()
        logger.debug("Created new ephemeral tab")
        return page

    async def close_tab(self, page: Page) -> None:
        """Close a specific tab."""
        try:
            if page and not page.is_closed():
                await page.close()
                logger.debug("Closed ephemeral tab")
        except Exception as e:
            logger.warning(f"Error closing tab: {e}")

    @asynccontextmanager
    async def new_tab(self) -> AsyncGenerator[Page, None]:
        """Async context manager: open a new tab, auto-close on exit.

        Usage::

            async with browser_manager.new_tab() as page:
                await page.goto("https://...")
                ...
        """
        page = await self._create_tab()
        try:
            yield page
        finally:
            await self.close_tab(page)

    # ------------------------------------------------------------------
    # Cookie/session sync helpers
    # ------------------------------------------------------------------

    async def clear_in_memory_session(self) -> bool:
        """Clear in-memory session state without restarting the process."""
        async with self._lifecycle_lock:
            try:
                if self._login_page and not self._login_page.is_closed():
                    await self._login_page.close()
                self._login_page = None

                if self.context is not None:
                    await self.context.clear_cookies()
                logger.info("In-memory browser session cleared")
                return True
            except Exception as e:
                logger.warning(f"Failed to clear in-memory session: {e}")
                return False

    async def sync_cookies_once(self, timeout_seconds: Optional[float] = None) -> dict[str, Any]:
        """Run a single login-state check and sync cookies to disk.

        Rules:
        - logged in: save latest context cookies to local cookie file
        - logged out: clear local cookie file and clear in-memory session
        - check error/timeout: keep local cookie file unchanged
        """
        if self._cookie_sync_lock.locked():
            logger.warning("Cookie sync skipped: previous sync is still running")
            return {
                "status": "skipped",
                "is_logged_in": None,
                "message": "Previous cookie sync is still running",
            }

        timeout = timeout_seconds if timeout_seconds is not None else self.settings.cookie_sync_timeout_seconds

        async with self._cookie_sync_lock:
            async def _run_sync() -> dict[str, Any]:
                cookie_store = get_cookie_store()

                async with self.new_tab() as page:
                    login_flow = LoginFlow(page)
                    is_logged_in, message = await login_flow.check_login_status()
                    if is_logged_in:
                        cookies = await page.context.cookies()
                        if cookie_store.save(cookies):
                            logger.info(f"Cookie auto-sync success: saved {len(cookies)} cookies")
                            return {
                                "status": "synced",
                                "is_logged_in": True,
                                "cookie_count": len(cookies),
                                "message": message,
                            }
                        logger.warning("Cookie auto-sync failed: could not persist cookies to file")
                        return {
                            "status": "error",
                            "is_logged_in": True,
                            "message": "Failed to save cookies to local file",
                        }

                file_cleared = cookie_store.clear()
                session_cleared = await self.clear_in_memory_session()
                logger.warning(
                    "Cookie auto-sync detected logged-out state; "
                    f"cookie_file_cleared={file_cleared}, memory_session_cleared={session_cleared}"
                )
                return {
                    "status": "logged_out_cleared",
                    "is_logged_in": False,
                    "cookie_file_cleared": file_cleared,
                    "memory_session_cleared": session_cleared,
                    "message": "Not logged in; local and in-memory session cleared",
                }

            try:
                return await asyncio.wait_for(_run_sync(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Cookie auto-sync timed out after {timeout}s; local cookies kept")
                return {
                    "status": "error",
                    "is_logged_in": None,
                    "message": f"Cookie sync timeout after {timeout}s",
                }
            except Exception as e:
                logger.warning(f"Cookie auto-sync failed unexpectedly: {e}; local cookies kept")
                return {
                    "status": "error",
                    "is_logged_in": None,
                    "message": f"Cookie sync failed: {e}",
                }

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """Check if browser is running."""
        return self.context is not None

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()


def get_browser_manager() -> BrowserManager:
    """Get the singleton browser manager instance."""
    return BrowserManager()
