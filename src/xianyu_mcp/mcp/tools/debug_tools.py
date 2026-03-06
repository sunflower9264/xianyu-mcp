"""Debug-related MCP tools."""

from pathlib import Path
from typing import Any, Optional

from xianyu_mcp.config import get_settings
from xianyu_mcp.infrastructure.browser import (
    get_browser_manager,
    take_screenshot,
)
from xianyu_mcp.logging import get_logger

logger = get_logger("debug_tools")


def _build_image_response(
    payload: dict[str, Any],
    image_path: str | None,
) -> dict[str, Any]:
    """Attach local screenshot path to payload."""
    if not image_path:
        payload["has_image"] = False
        payload["image_path"] = None
        return payload

    try:
        file_path = Path(image_path).resolve()
        payload["has_image"] = file_path.exists()
        payload["image_path"] = str(file_path.resolve())
        payload["image_file_note"] = "请将 image_path 对应的本地图片文件直接展示给用户。"
        return payload
    except Exception as e:
        logger.warning(f"Failed to resolve screenshot path: {e}")
        payload["has_image"] = False
        payload["image_path"] = None
        payload["image_path_error"] = str(e)
        return payload


async def screenshot(
    full_page: bool = False,
    url: Optional[str] = None,
) -> dict[str, Any]:
    """
    Take a screenshot of a browser page.

    If *url* is provided, opens a new tab, navigates to the URL, takes a
    screenshot and closes the tab.  If *url* is omitted, screenshots the
    persistent login page (useful to see QR-code state, etc.).
    """
    logger.info(f"Tool called: screenshot (full_page: {full_page}, url: {url})")

    try:
        browser_manager = get_browser_manager()
        await browser_manager.start()

        if url:
            # Use an ephemeral tab for the given URL
            async with browser_manager.new_tab() as page:
                await page.goto(url, timeout=get_settings().page_timeout)
                await page.wait_for_load_state("networkidle", timeout=get_settings().page_timeout)
                image_path = await take_screenshot(page, full_page=full_page)
                return _build_image_response({
                    "image_path": image_path,
                    "message": f"Screenshot of {url} captured successfully",
                    "full_page": full_page,
                }, image_path)
        else:
            # Screenshot the persistent login page
            page = await browser_manager.get_login_page()
            image_path = await take_screenshot(page, full_page=full_page)
            return _build_image_response({
                "image_path": image_path,
                "message": "Screenshot of login page captured successfully",
                "full_page": full_page,
            }, image_path)

    except Exception as e:
        logger.error(f"Error in screenshot: {e}")
        return {
            "image_path": None,
            "message": f"Error taking screenshot: {e}",
            "error": str(e),
        }


# Tool definitions for MCP registration
# Keep screenshot implementation in this module, but do not expose it as an MCP tool.
DEBUG_TOOLS = []
