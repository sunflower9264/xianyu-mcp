"""Account-related MCP tools."""

import time
from pathlib import Path
from typing import Any

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


def _build_image_response(
    payload: dict[str, Any],
    image_path: str | None,
) -> dict[str, Any]:
    """Attach local image path metadata to payload."""
    if not image_path:
        payload["has_image"] = False
        payload["image_path"] = None
        return payload

    try:
        file_path = Path(image_path).resolve()
        payload["has_image"] = file_path.exists()
        payload["image_path"] = str(file_path)
        payload["image_file_note"] = "请将 image_path 对应的本地图片文件直接展示给用户。"
        return payload
    except Exception as e:
        logger.warning(f"Failed to resolve image path: {e}")
        payload["has_image"] = False
        payload["image_path"] = None
        payload["image_path_error"] = str(e)
        return payload


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
    """获取闲鱼登录二维码，返回本地二维码图片路径。"""
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

        result = {
            "message": message,
            "status": "qrcode_ready",
            "next_step": (
                "请直接向用户展示 image_path 对应的二维码图片文件。"
                "当用户明确回复“已确认扫码”后，调用 check_login_scan_result(user_confirmed_scanned=true)。"
            ),
        }
        return _build_image_response(result, image_path)

    except Exception as e:
        logger.error(f"Error in get_login_qrcode: {e}")
        return {
            "message": f"Error getting QR code: {e}",
            "error": str(e),
        }


async def check_login_scan_result(user_confirmed_scanned: bool = False) -> Any:
    """检查扫码登录结果，若触发人脸识别则返回本地图片路径。"""
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

        result = {
            "status": status.value if status else "error",
            "message": message,
        }
        if warning_prefix and result["status"] != "login_success":
            result["message"] = f"{warning_prefix}{result['message']}"

        if result["status"] == "need_face_verify":
            result["next_step"] = (
                "登录流程第 3/3 步：请直接向用户展示 image_path 对应的人脸识别二维码图片文件。"
                "当用户明确回复“已确认扫码”后，再次调用 check_login_scan_result(user_confirmed_scanned=true) 复查。"
            )
        elif result["status"] in {"waiting_scan", "waiting_auto_login"}:
            result["next_step"] = (
                "等待用户明确回复“已确认扫码”后，"
                "再次调用 check_login_scan_result(user_confirmed_scanned=true)。"
            )
        elif result["status"] == "login_success":
            result["next_step"] = "登录已完成，可继续调用其他业务工具。"
        elif result["status"] in {"qr_expired", "timeout"}:
            result["next_step"] = "请重新调用 get_login_qrcode 获取新的二维码。"

        # Close browser on login success
        if result["status"] == "login_success":
            _qrcode_generated_at = None
            await browser_manager.close()
            logger.info("Browser closed after successful login")

        return _build_image_response(result, image_path)

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
        "description": "登录流程第 1/3 步：获取闲鱼登录二维码并返回本地图片路径（image_path，不返回 base64 或 MCP ImageContent）。主要返回字段：status、message、has_image、image_path、image_file_note。请把 image_path 对应文件直接展示给用户。仅当用户明确回复“已确认扫码”后，进入第 2/3 步并调用 check_login_scan_result(user_confirmed_scanned=true)。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": get_login_qrcode,
    },
    {
        "name": "check_login_scan_result",
        "description": "登录流程第 2/3 步与第 3/3 步共用本工具。第 2/3 步：用户首次扫码并明确回复“已确认扫码”后调用，检查登录状态。第 3/3 步：若返回 status=need_face_verify 且带 image_path，需展示 image_path 对应二维码文件并等待用户再次回复“已确认扫码”，然后再次调用本工具复查，直到 login_success 或超时/过期。主要返回字段：status、message、next_step、has_image、image_path。本工具不返回 base64 或 MCP ImageContent。",
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
