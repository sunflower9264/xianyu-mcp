"""Constants for Xianyu platform.

All CSS selectors are centralized here for easy maintenance.
When the website structure changes, only this file needs to be updated.
"""

# =============================================================================
# URLs
# =============================================================================

XIANYU_BASE_URL = "https://www.goofish.com"

# =============================================================================
# Browser Configuration
# =============================================================================

DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-gpu",
]


# =============================================================================
# Login Selectors - Only selectors needed for browser-based login
# =============================================================================

# Login page selectors
# Note: Login QR code and face verify QR code are inside an iframe (#alibaba-login-box)
LOGIN_SELECTORS = {
    # 登录按钮 - 在主页面
    "login_button": [
        ".btn--LjnfPVtt",
    ],
    # 登录成功指示器 - 在主页面
    "logged_in_indicator": [
        ".nick--RyNYtDXM",
    ],
    # 登录成功后页面内容（用于检测页面加载完成）
    "page_content_loaded": [
        ".feeds-item-wrap--rGdH_KoF",
    ],
    # iframe selector for login page elements
    "login_iframe": "#alibaba-login-box",
    # 登录二维码 - 在iframe内，使用canvas
    "qrcode_image": [
        ".qrcode-img canvas",
    ],
    # 二维码容器 - 在iframe内
    "qrcode_container": [
        ".qrcode-img",
    ],
    # 人脸识别二维码 - 在iframe内，使用canvas
    "face_verify_qrcode": [
        "#J_Qrcode canvas",
    ],
    # Which elements are inside the iframe
    "in_iframe": {
        "qrcode_image": True,
        "qrcode_container": True,
        "face_verify_qrcode": True,
    },
}


# =============================================================================
# Helper Functions
# =============================================================================

def get_selectors(selectors_dict: dict, key: str) -> list:
    """Get the full selector list for a key.

    Args:
        selectors_dict: Dictionary containing selector lists
        key: Key to look up

    Returns:
        List of selector strings, or empty list if not found
    """
    return selectors_dict.get(key, [])
