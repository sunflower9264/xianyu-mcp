"""MCP tools module."""

from xianyu_mcp.mcp.tools.account_tools import ACCOUNT_TOOLS
from xianyu_mcp.mcp.tools.debug_tools import DEBUG_TOOLS
from xianyu_mcp.mcp.tools.goods_tools import GOODS_TOOLS
from xianyu_mcp.mcp.tools.ai_tools import AI_TOOLS
from xianyu_mcp.mcp.tools.sale_tools import SALE_TOOLS
from xianyu_mcp.mcp.tools.seller_tools import SELLER_TOOLS

# Combine all tools
ALL_TOOLS = (
    ACCOUNT_TOOLS +
    DEBUG_TOOLS +
    GOODS_TOOLS +
    AI_TOOLS +
    SALE_TOOLS +
    SELLER_TOOLS
)

__all__ = [
    "ACCOUNT_TOOLS",
    "DEBUG_TOOLS",
    "GOODS_TOOLS",
    "AI_TOOLS",
    "SALE_TOOLS",
    "SELLER_TOOLS",
    "ALL_TOOLS",
]
