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
DEBUG_TOOLS = [
    {
        "name": "screenshot",
        "description": "截取浏览器页面截图并返回本地图片路径（image_path，不返回 base64 或 MCP ImageContent）。主要返回字段：message、full_page、has_image、image_path、image_file_note。请把 image_path 对应文件直接展示给用户。传入 url 则打开新标签页截图后关闭；不传 url 则截取登录页面（适用于查看二维码等状态）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "full_page": {
                    "type": "boolean",
                    "description": "为 true 时截取整页可滚动区域；为 false（默认）时仅截取当前可见视口。",
                    "default": False,
                },
                "url": {
                    "type": "string",
                    "description": "可选 URL，传入后将在新标签页中打开并截图，截图后自动关闭标签页。",
                },
            },
            "required": [],
        },
        "handler": screenshot,
    },
]
