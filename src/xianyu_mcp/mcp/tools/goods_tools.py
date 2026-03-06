"""Goods-related MCP tools."""

import re
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from xianyu_mcp.infrastructure.api import get_api_client
from xianyu_mcp.logging import get_logger

logger = get_logger("goods_tools")


def extract_item_id(url: str) -> Optional[str]:
    """Extract item ID from URL.

    Supports:
      - https://www.goofish.com/item?id=821040211708&categoryId=...
      - https://www.goofish.com/item/821040211708
      - https://h5.m.goofish.com/item?id=821040211708
      - Legacy: itemId=xxx
    """
    parsed = urlparse(url)

    # 1. Try query parameter: ?id=xxx or ?itemId=xxx
    qs = parse_qs(parsed.query)
    if "id" in qs:
        return qs["id"][0]
    if "itemId" in qs:
        return qs["itemId"][0]

    # 2. Try path: /item/xxx
    match = re.search(r"/item/(\w+)", parsed.path)
    if match:
        return match.group(1)

    return None


def _extract_item_id(url: str) -> Optional[str]:
    """Backward-compatible alias for extract_item_id."""
    return extract_item_id(url)


async def search_goods(
    keyword: str,
    page_num: int = 1,
    page_size: int = 20,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    sort_field: Optional[str] = None,
    sort_value: Optional[str] = None,
    quick_filters: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Search for goods on Xianyu by keyword using direct API.

    Args:
        keyword: Search keyword.
        page_num: Page number (default: 1).
        page_size: Number of items per page (default: 20, max: 50).
        price_min: Minimum price filter (optional).
        price_max: Maximum price filter (optional).
        sort_field: Sort field - "create"(最新), "modify"(最近活跃), "credit"(信用),
                    "reduce"(新降价), "price"(价格), or empty for default(综合).
        sort_value: Sort direction - "asc", "desc", "credit_desc".
        quick_filters: List of quick filters - "filterPersonal"(个人闲置),
                       "filterAppraise"(验货宝), "gameAccountInsurance"(验号担保),
                       "filterFreePostage"(包邮), "filterHighLevelYxpSeller"(超赞鱼小铺),
                       "filterNew"(全新), "inspectedPhone"(严选), "filterOneKeyResell"(转卖).

    Returns:
        dict with search results including items list, total count, and pagination info.
    """
    logger.info(f"Tool called: search_goods (keyword: {keyword}, page: {page_num})")

    if not keyword or not keyword.strip():
        return {
            "keyword": keyword,
            "items": [],
            "total_count": 0,
            "page": page_num,
            "has_more": False,
            "message": "Keyword is required",
        }

    page_size = min(page_size, 50)

    try:
        # Use singleton API client
        api_client = get_api_client()
        result = await api_client.search_goods(
            keyword=keyword,
            page_number=page_num,
            rows_per_page=page_size,
            price_min=price_min,
            price_max=price_max,
            sort_field=sort_field,
            sort_value=sort_value,
            quick_filters=quick_filters,
        )

        # Transform items to match expected format
        items = []
        for item in result.get("items", []):
            items.append({
                "item_id": item.get("item_id"),
                "title": item.get("title"),
                "price": item.get("price"),
                "link": item.get("url"),
                "mobile_url": item.get("mobile_url"),
                "image_url": item.get("image_url"),
                "location": item.get("location"),
                "seller_nickname": item.get("seller_nickname"),
                "detail": item.get("detail"),
            })

        return {
            "keyword": keyword,
            "items": items,
            "total_count": len(items),
            "page": page_num,
            "has_more": result.get("has_more", False),
            "message": result.get("message", f"Found {len(items)} items for '{keyword}'"),
        }

    except Exception as e:
        logger.error(f"Error in search_goods: {e}")
        return {
            "keyword": keyword,
            "items": [],
            "total_count": 0,
            "page": page_num,
            "has_more": False,
            "message": f"Error searching goods: {e}",
            "error": str(e),
        }


async def get_home_goods(
    page_num: int = 1,
    page_size: int = 30,
) -> dict[str, Any]:
    """
    Get home goods recommendations (猜你喜欢) from Xianyu.

    Args:
        page_num: Page number (default: 1).
        page_size: Number of items per page (default: 30, max: 50).

    Returns:
        dict with recommended items list, total count, and pagination info.
    """
    logger.info(f"Tool called: get_home_goods (page: {page_num})")

    page_size = min(page_size, 50)

    try:
        api_client = get_api_client()
        result = await api_client.get_home_goods(
            page_number=page_num,
            page_size=page_size,
        )

        # Transform items to match expected format
        items = []
        for item in result.get("items", []):
            item_dict = {
                "item_id": item.get("item_id"),
                "title": item.get("title"),
                "price": item.get("price"),
                "link": item.get("url"),
                "mobile_url": item.get("mobile_url"),
                "image_url": item.get("image_url"),
                "location": item.get("location"),
                "seller_nickname": item.get("seller_nickname"),
                "detail": item.get("detail"),
            }
            if item.get("original_price"):
                item_dict["original_price"] = item["original_price"]
            if item.get("want_count"):
                item_dict["want_count"] = item["want_count"]
            items.append(item_dict)

        return {
            "items": items,
            "total_count": len(items),
            "page": page_num,
            "has_more": result.get("has_more", False),
            "message": result.get("message", f"Got {len(items)} recommended items"),
        }

    except Exception as e:
        logger.error(f"Error in get_home_goods: {e}")
        return {
            "items": [],
            "total_count": 0,
            "page": page_num,
            "has_more": False,
            "message": f"Error getting home goods: {e}",
            "error": str(e),
        }


async def get_goods_detail(item_id: str) -> dict[str, Any]:
    """
    Get detailed information about a specific goods item using API.

    Args:
        item_id: The item ID or item URL.

    Returns:
        dict with detailed goods information including title, price, description,
        images, seller info, etc.
    """
    logger.info(f"Tool called: get_goods_detail (item_id: {item_id})")

    if not item_id:
        return {
            "item_id": None,
            "title": "",
            "message": "Item ID is required",
        }

    # Extract item ID from URL if full URL is provided
    if item_id.startswith("http"):
        extracted_id = extract_item_id(item_id)
        if extracted_id:
            item_id = extracted_id
        else:
            return {
                "item_id": item_id,
                "title": "",
                "message": "Invalid item URL: could not extract item ID",
                "error": "INVALID_PARAMETER",
            }

    try:
        api_client = get_api_client()
        result = await api_client.get_goods_detail(item_id)
        logger.info(f"Got goods detail: {result.get('title', 'No title')}")
        return result

    except Exception as e:
        logger.error(f"Error in get_goods_detail: {e}")
        return {
            "item_id": item_id,
            "title": "",
            "message": f"Error getting goods detail: {e}",
            "error": str(e),
        }


async def add_favorite(item_id: str) -> dict[str, Any]:
    """
    Add a goods item to favorites using API.

    Args:
        item_id: The item ID to favorite.

    Returns:
        dict with operation result.
    """
    logger.info(f"Tool called: add_favorite (item_id: {item_id})")

    if not item_id:
        return {
            "success": False,
            "message": "Item ID is required",
        }

    try:
        api_client = get_api_client()
        return await api_client.add_favorite(item_id)
    except Exception as e:
        logger.error(f"Error in add_favorite: {e}")
        return {
            "success": False,
            "item_id": item_id,
            "message": f"Error adding to favorites: {e}",
            "error": str(e),
        }


async def remove_favorite(item_id: str) -> dict[str, Any]:
    """
    Remove a goods item from favorites using API.

    Args:
        item_id: The item ID to unfavorite.

    Returns:
        dict with operation result.
    """
    logger.info(f"Tool called: remove_favorite (item_id: {item_id})")

    if not item_id:
        return {
            "success": False,
            "message": "Item ID is required",
        }

    try:
        api_client = get_api_client()
        return await api_client.remove_favorite(item_id)
    except Exception as e:
        logger.error(f"Error in remove_favorite: {e}")
        return {
            "success": False,
            "item_id": item_id,
            "message": f"Error removing from favorites: {e}",
            "error": str(e),
        }


async def get_favorites(
    page_num: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """
    Get user's favorite items list from Xianyu.

    Args:
        page_num: Page number (default: 1).
        page_size: Number of items per page (default: 20, max: 50).

    Returns:
        dict with favorite items list, total count, and pagination info.
    """
    logger.info(f"Tool called: get_favorites (page: {page_num})")

    page_size = min(page_size, 50)

    try:
        api_client = get_api_client()
        result = await api_client.get_favorites(
            page_number=page_num,
            rows_per_page=page_size,
        )

        # Transform items to match expected format
        items = []
        for item in result.get("items", []):
            items.append({
                "item_id": item.get("item_id"),
                "title": item.get("title"),
                "price": item.get("price"),
                "link": item.get("url"),
                "image_url": item.get("image_url"),
                "location": item.get("location"),
                "seller_nickname": item.get("seller_nickname"),
                "detail": item.get("detail"),
            })

        return {
            "items": items,
            "total_count": len(items),
            "page": page_num,
            "has_more": result.get("has_more", False),
            "message": result.get("message", f"Got {len(items)} favorite items"),
        }

    except Exception as e:
        logger.error(f"Error in get_favorites: {e}")
        return {
            "items": [],
            "total_count": 0,
            "page": page_num,
            "has_more": False,
            "message": f"Error getting favorites: {e}",
            "error": str(e),
        }


# Tool definitions for MCP registration
GOODS_TOOLS = [
    {
        "name": "search_goods",
        "description": "按关键词搜索闲鱼商品。支持价格区间筛选、排序和快速筛选（个人闲置、验货宝、包邮等）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "page_num": {
                    "type": "integer",
                    "default": 1,
                    "description": "页码（默认1）",
                },
                "page_size": {
                    "type": "integer",
                    "default": 20,
                    "description": "每页数量（默认20，最大50）",
                },
                "price_min": {
                    "type": "number",
                    "description": "最低价格",
                },
                "price_max": {
                    "type": "number",
                    "description": "最高价格",
                },
                "sort_field": {
                    "type": "string",
                    "description": "排序字段：create(最新)、modify(最近活跃)、credit(信用)、reduce(新降价)、price(价格)",
                },
                "sort_value": {
                    "type": "string",
                    "description": "排序方向：asc、desc、credit_desc",
                },
                "quick_filters": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "快速筛选：filterPersonal(个人闲置)、filterAppraise(验货宝)、filterFreePostage(包邮)、filterNew(全新)等",
                },
            },
            "required": ["keyword"],
        },
        "handler": search_goods,
    },
    {
        "name": "get_home_goods",
        "description": "获取闲鱼首页推荐商品（猜你喜欢）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_num": {
                    "type": "integer",
                    "default": 1,
                    "description": "页码（默认1）",
                },
                "page_size": {
                    "type": "integer",
                    "default": 30,
                    "description": "每页数量（默认30，最大50）",
                },
            },
            "required": [],
        },
        "handler": get_home_goods,
    },
    {
        "name": "get_goods_detail",
        "description": "获取指定商品的详细信息。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "商品 ID 或商品链接",
                },
            },
            "required": ["item_id"],
        },
        "handler": get_goods_detail,
    },
    {
        "name": "get_favorites",
        "description": "获取当前用户的收藏列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_num": {
                    "type": "integer",
                    "default": 1,
                    "description": "页码（默认1）",
                },
                "page_size": {
                    "type": "integer",
                    "default": 20,
                    "description": "每页数量（默认20）",
                },
            },
            "required": [],
        },
        "handler": get_favorites,
    },
    {
        "name": "add_favorite",
        "description": "将指定商品加入闲鱼收藏。主要返回字段：success、item_id、message（失败时可能包含 error）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "要加入收藏的商品 ID",
                },
            },
            "required": ["item_id"],
        },
        "handler": add_favorite,
    },
    {
        "name": "remove_favorite",
        "description": "将指定商品从闲鱼收藏中移除。主要返回字段：success、item_id、message（失败时可能包含 error）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "要移除收藏的商品 ID",
                },
            },
            "required": ["item_id"],
        },
        "handler": remove_favorite,
    },
]
