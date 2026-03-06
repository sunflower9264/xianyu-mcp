"""Xianyu API client facade.

This module keeps a stable entrypoint while concrete API groups are split into
focused mixins by interface type.
"""

from typing import Optional

from xianyu_mcp.infrastructure.api.xianyu_client_base import XianyuApiClientBase
from xianyu_mcp.infrastructure.api.xianyu_favorite_client import XianyuFavoriteApiMixin
from xianyu_mcp.infrastructure.api.xianyu_goods_client import XianyuGoodsApiMixin
from xianyu_mcp.infrastructure.api.xianyu_sale_client import XianyuSaleApiMixin


class XianyuApiClient(XianyuGoodsApiMixin, XianyuFavoriteApiMixin, XianyuSaleApiMixin, XianyuApiClientBase):
    """Unified Xianyu API client assembled from type-specific mixins."""


# Singleton instance
_client: Optional[XianyuApiClient] = None


def get_api_client() -> XianyuApiClient:
    """Get the singleton API client instance."""
    global _client
    if _client is None:
        _client = XianyuApiClient()
    return _client


async def close_api_client() -> None:
    """Close and clear the singleton API client instance."""
    global _client
    if _client is None:
        return
    await _client.close()
    _client = None
