"""Account-related MCP tools."""

import time
from pathlib import Path
from typing import Any

from mcp.types import TextContent

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
) -> list[TextContent]:
    """Build MCP text content with QR code file path.

    Args:
        text: The text message to display to user.
        image_path: The actual file path where the QR code image is saved.
    """
    if not image_path:
        return [TextContent(type="text", text=text)]

    try:
        file_path = Path(image_path)
        # Check if the file exists
        if not file_path.exists():
            return [TextContent(type="text", text=f"{text}\n\n二维码文件不存在: {file_path}")]

        # Build path hint - tell user to find the file in project's screenshots directory
        path_hint = f"\n\n请打开项目目录下 screenshots 文件夹中的图片并用闲鱼 App 扫码（二维码文件名：{file_path.name}）"

        return [TextContent(type="text", text=text + path_hint)]
    except Exception as e:
        logger.warning(f"Failed to get QR code path: {e}")
        return [TextContent(type="text", text=f"{text}\n\n获取二维码路径失败: {e}")]


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
    """获取闲鱼登录二维码，二维码图片会保存到文件并返回宿主机路径。请用户打开该路径的图片并用闲鱼 App 扫码。"""
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
            "请打开下方二维码图片并用闲鱼 App 扫码。\n\n"
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
    """检查扫码登录结果。若触发人脸识别，人脸二维码图片会保存到文件并返回宿主机路径。返回内容中的 qrcode_path 字段为人脸二维码的宿主机路径。"""
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
                "请打开项目目录下 screenshots 文件夹中的人脸验证二维码图片并完成验证。\n\n"
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
        "description": "登录流程第 1/3 步：获取闲鱼登录二维码。二维码图片会保存到项目目录的 screenshots 文件夹（Docker 环境请将此目录映射到宿主机）。请告知用户打开该图片并用闲鱼 App 扫码。用户明确回复“已确认扫码”后，再调用 check_login_scan_result(user_confirmed_scanned=true)。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": get_login_qrcode,
    },
    {
        "name": "check_login_scan_result",
        "description": "登录流程第 2/3 步与第 3/3 步共用本工具。用户在明确回复“已确认扫码”后调用它检查状态；若触发人脸验证，人脸二维码图片会保存到项目目录的 screenshots 文件夹（Docker 环境请将此目录映射到宿主机）。请告知用户打开该图片并完成验证。",
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
