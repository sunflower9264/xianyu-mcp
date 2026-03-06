"""Debug-related MCP tools."""

import base64
import mimetypes
from pathlib import Path
from typing import Any, Optional

from xianyu_mcp.config import get_settings
from xianyu_mcp.infrastructure.browser import (
    get_browser_manager,
    take_screenshot,
)
from xianyu_mcp.logging import get_logger

logger = get_logger("debug_tools")


def _attach_image_payload(payload: dict[str, Any], image_path: str | None) -> dict[str, Any]:
    """Attach structured image fields for clients without native image block support."""
    if not image_path:
        payload["has_image"] = False
        return payload

    try:
        file_path = Path(image_path)
        image_bytes = file_path.read_bytes()
        encoded_data = base64.b64encode(image_bytes).decode("ascii")
        mime_type = mimetypes.guess_type(file_path.name)[0] or "image/png"
        if not mime_type.startswith("image/"):
            mime_type = "image/png"

        payload["has_image"] = True
        payload["image_path"] = str(file_path.resolve())
        payload["image_mime_type"] = mime_type
        payload["image_base64"] = encoded_data
        payload["image_data_url"] = f"data:{mime_type};base64,{encoded_data}"
        return payload
    except Exception as e:
        logger.warning(f"Failed to attach screenshot image payload: {e}")
        payload["has_image"] = False
        payload["image_encode_error"] = str(e)
        return payload


async def screenshot(full_page: bool = False, url: Optional[str] = None) -> dict[str, Any]:
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
                return _attach_image_payload({
                    "image_path": image_path,
                    "message": f"Screenshot of {url} captured successfully",
                    "full_page": full_page,
                }, image_path)
        else:
            # Screenshot the persistent login page
            page = await browser_manager.get_login_page()
            image_path = await take_screenshot(page, full_page=full_page)
            return _attach_image_payload({
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
        "description": "截取浏览器页面并保存到本地文件。传入 url 则打开新标签页截图后关闭；不传 url 则截取登录页面（适用于查看二维码等状态）。",
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
