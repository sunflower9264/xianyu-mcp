"""Account-related MCP tools."""

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any

from mcp.types import ImageContent, TextContent

from xianyu_mcp.infrastructure.browser import (
    get_browser_manager,
    LoginFlow,
)
from xianyu_mcp.logging import get_logger

logger = get_logger("account_tools")

# Timestamp of when the login QR code was generated (for 5-min timeout)
_qrcode_generated_at: float | None = None

# Login flow timeout in seconds
LOGIN_TIMEOUT_SECONDS = 300  # 5 minutes


def _build_qrcode_response(
    text: str,
    image_path: str | None,
) -> list[TextContent | ImageContent]:
    """Build MCP text/image content blocks for QR-code style responses."""
    if not image_path:
        return [TextContent(type="text", text=text)]

    try:
        file_path = Path(image_path).resolve()
        if not file_path.exists():
            return [TextContent(type="text", text=f"{text}\n\n二维码文件不存在，无法返回图片内容。")]

        image_bytes = file_path.read_bytes()
        encoded_data = base64.b64encode(image_bytes).decode("ascii")
        mime_type = mimetypes.guess_type(file_path.name)[0] or "image/png"
        return [
            TextContent(type="text", text=text),
            ImageContent(type="image", data=encoded_data, mimeType=mime_type),
        ]
    except Exception as e:
        logger.warning(f"Failed to encode QR code image for MCP response: {e}")
        return [TextContent(type="text", text=f"{text}\n\n图片编码失败: {e}")]


async def check_login_status() -> dict[str, Any]:
    """
    Check if the user is currently logged in to Xianyu.

    Returns:
        dict with 'is_logged_in' (bool) and 'message' (str) fields.
    """
    logger.info("Tool called: check_login_status")

    browser_manager = get_browser_manager()
    try:
        async with browser_manager.new_tab() as page:
            login_flow = LoginFlow(page)
            is_logged_in, message = await login_flow.check_login_status()

        return {
            "is_logged_in": is_logged_in,
            "message": message,
        }

    except Exception as e:
        logger.error(f"Error in check_login_status: {e}")
        return {
            "is_logged_in": False,
            "message": f"Error checking login status: {e}",
            "error": str(e),
        }


async def get_login_qrcode() -> Any:
    """获取闲鱼登录二维码，返回 MCP 文本和图片内容块。"""
    global _qrcode_generated_at
    logger.info("Tool called: get_login_qrcode")

    try:
        browser_manager = get_browser_manager()
        await browser_manager.start()
        page = await browser_manager.get_login_page()

        login_flow = LoginFlow(page)
        image_path, message = await login_flow.get_login_qrcode()

        # Record QR code generation time for timeout tracking
        _qrcode_generated_at = time.monotonic()

        result_text = (
            "请使用闲鱼 App 在 5 分钟内扫码登录。\n\n"
            "请直接展示当前工具返回的二维码图片，不要手动做 base64 解码或落盘。\n\n"
            "当用户明确回复“已确认扫码”后，调用 "
            "check_login_scan_result(user_confirmed_scanned=true)。"
        )
        return _build_qrcode_response(result_text, image_path)

    except Exception as e:
        logger.error(f"Error in get_login_qrcode: {e}")
        return {
            "message": f"Error getting QR code: {e}",
            "error": str(e),
        }


async def check_login_scan_result(user_confirmed_scanned: bool = False) -> Any:
    """检查扫码登录结果，若触发人脸识别则返回 MCP 文本和图片内容块。"""
    logger.info(
        "Tool called: check_login_scan_result "
        f"(user_confirmed_scanned={user_confirmed_scanned})"
    )
    warning_prefix = None
    if not user_confirmed_scanned:
        logger.warning(
            "check_login_scan_result called without user_confirmed_scanned=true; "
            "will still run a real status check to avoid false waiting_scan."
        )
        warning_prefix = (
            "User has not explicitly confirmed scan yet. "
            "If status is not login_success, ask user to scan QR code and reply '已扫码' "
            "before checking again. "
        )

    global _qrcode_generated_at
    browser_manager = get_browser_manager()

    # Check 5-minute timeout since QR code was generated
    if _qrcode_generated_at is not None:
        elapsed = time.monotonic() - _qrcode_generated_at
        if elapsed > LOGIN_TIMEOUT_SECONDS:
            logger.warning(f"Login timeout: {elapsed:.0f}s elapsed since QR code generation")
            _qrcode_generated_at = None
            await browser_manager.close()
            return {
                "status": "timeout",
                "message": "Login timed out (exceeded 5 minutes). "
                           "Please call get_login_qrcode to get a new QR code.",
            }

    try:
        await browser_manager.start()
        page = await browser_manager.get_login_page()

        login_flow = LoginFlow(page)
        status, image_path, message = await login_flow.check_login_scan_status()

        status_value = status.value if status else "error"
        result_message = message or "登录状态未知。"
        if warning_prefix and status_value != "login_success":
            result_message = f"{warning_prefix}{result_message}"

        if status_value == "need_face_verify":
            result_text = (
                f"当前状态：{status_value}\n{result_message}\n\n"
                "请直接展示当前工具返回的人脸识别二维码图片，不要手动做 base64 解码或落盘。\n\n"
                "当用户明确回复“已确认扫码”后，再次调用 "
                "check_login_scan_result(user_confirmed_scanned=true)。"
            )
        elif status_value in {"waiting_scan", "waiting_auto_login"}:
            result_text = (
                f"当前状态：{status_value}\n{result_message}\n\n"
                "等待用户明确回复“已确认扫码”后，再次调用 "
                "check_login_scan_result(user_confirmed_scanned=true)。"
            )
        elif status_value == "login_success":
            result_text = f"当前状态：{status_value}\n{result_message}\n\n登录已完成，可继续调用其他业务工具。"
        elif status_value in {"qr_expired", "timeout"}:
            result_text = (
                f"当前状态：{status_value}\n{result_message}\n\n"
                "请重新调用 get_login_qrcode 获取新的二维码。"
            )
        else:
            result_text = f"当前状态：{status_value}\n{result_message}"

        # Close browser on login success
        if status_value == "login_success":
            _qrcode_generated_at = None
            await browser_manager.close()
            logger.info("Browser closed after successful login")

        return _build_qrcode_response(result_text, image_path)

    except Exception as e:
        logger.error(f"Error in check_login_scan_result: {e}")
        return {
            "status": "error",
            "message": f"Error checking login scan result: {e}",
            "error": str(e),
        }


async def logout() -> dict[str, Any]:
    """
    Logout from Xianyu by deleting local cookies.

    No browser needed — simply removes the saved cookie file.
    Next login-dependent operation will require re-login.

    Returns:
        dict with 'success' (bool) and 'message' (str).
    """
    logger.info("Tool called: logout")

    try:
        from xianyu_mcp.infrastructure.storage.cookie_store import get_cookie_store

        # Delete local cookies
        cookie_store = get_cookie_store()
        cookie_store.clear()

        # Also close browser if it's running, to drop in-memory session
        browser_manager = get_browser_manager()
        if browser_manager.is_running():
            await browser_manager.close()
            logger.info("Browser closed during logout")

        return {
            "success": True,
            "message": "Logged out successfully. Local cookies deleted.",
        }

    except Exception as e:
        logger.error(f"Error in logout: {e}")
        return {
            "success": False,
            "message": f"Error during logout: {e}",
            "error": str(e),
        }


# Tool definitions for MCP registration
ACCOUNT_TOOLS = [
    {
        "name": "check_login_status",
        "description": "检查当前用户是否已登录闲鱼。返回字段：is_logged_in、message（失败时可能包含 error）。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": check_login_status,
    },
    {
        "name": "get_login_qrcode",
        "description": "登录流程第 1/3 步：获取闲鱼登录二维码。返回一段文字说明和一个可直接展示的 MCP image 内容块，不返回 qrcode_base64 文本。用户明确回复“已确认扫码”后，再调用 check_login_scan_result(user_confirmed_scanned=true)。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": get_login_qrcode,
    },
    {
        "name": "check_login_scan_result",
        "description": "登录流程第 2/3 步与第 3/3 步共用本工具。用户在明确回复“已确认扫码”后调用它检查状态；若触发人脸验证，会返回一段文字说明和一个 MCP image 内容块。返回内容不包含 qrcode_base64 文本。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_confirmed_scanned": {
                    "type": "boolean",
                    "default": False,
                    "description": '建议在用户明确回复“已确认扫码”后设为 true。为 false 时也会执行真实检查，但可能附带提醒信息。',
                },
            },
            "required": [],
        },
        "handler": check_login_scan_result,
    },
    {
        "name": "logout",
        "description": "退出闲鱼登录状态（清理浏览器会话数据），下次使用需重新登录。返回字段：success、message（失败时可能包含 error）。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": logout,
    },
]
