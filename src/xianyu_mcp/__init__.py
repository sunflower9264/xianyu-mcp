"""
Xianyu MCP - MCP service for Xianyu (闲鱼) with Playwright browser automation.

This package provides a Model Context Protocol (MCP) server that enables
AI agents to interact with the Xianyu platform through browser automation.
"""

__version__ = "0.3.0"

from xianyu_mcp.config import get_settings, Settings
from xianyu_mcp.errors import XianyuMCPError
from xianyu_mcp.infrastructure.browser import get_browser_manager, BrowserManager

__all__ = [
    "__version__",
    "get_settings",
    "Settings",
    "XianyuMCPError",
    "get_browser_manager",
    "BrowserManager",
]
