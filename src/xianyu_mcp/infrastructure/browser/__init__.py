"""Browser infrastructure module."""

from xianyu_mcp.infrastructure.browser.browser_manager import (
    BrowserManager,
    get_browser_manager,
)
from xianyu_mcp.infrastructure.browser.login_flow import LoginFlow
from xianyu_mcp.infrastructure.browser.page_utils import (
    take_screenshot,
    random_delay,
    scroll_page,
    scroll_to_bottom,
)
from xianyu_mcp.infrastructure.browser.stealth import (
    apply_stealth_to_context,
    get_random_user_agent,
    get_stealth_context_options,
)

__all__ = [
    "BrowserManager",
    "get_browser_manager",
    "LoginFlow",
    "take_screenshot",
    "random_delay",
    "scroll_page",
    "scroll_to_bottom",
    "apply_stealth_to_context",
    "get_random_user_agent",
    "get_stealth_context_options",
]
