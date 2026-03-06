"""Seller profile MCP tools for scraping seller information from Xianyu."""

import asyncio
from typing import Any

from playwright.async_api import Page, Response

from xianyu_mcp.infrastructure.browser import get_browser_manager, random_delay
from xianyu_mcp.logging import get_logger

logger = get_logger("seller_tools")


# ============== Helper Functions ==============

def _safe_get(data: Any, *keys, default: Any = "暂无") -> Any:
    """Safely get nested dict/list values."""
    for key in keys:
        try:
            data = data[key]
        except (KeyError, TypeError, IndexError):
            return default
    return data


# ============== Data Parsing Functions ==============

def _parse_user_head_data(head_json: dict) -> dict:
    """Parse user header API JSON data."""
    data = head_json.get('data', {})
    ylz_tags = _safe_get(data, 'module', 'base', 'ylzTags', default=[])
    seller_credit, buyer_credit = {}, {}
    for tag in ylz_tags:
        if _safe_get(tag, 'attributes', 'role') == 'seller':
            seller_credit = {
                'level': _safe_get(tag, 'attributes', 'level'),
                'text': tag.get('text')
            }
        elif _safe_get(tag, 'attributes', 'role') == 'buyer':
            buyer_credit = {
                'level': _safe_get(tag, 'attributes', 'level'),
                'text': tag.get('text')
            }
    return {
        "卖家昵称": _safe_get(data, 'module', 'base', 'displayName'),
        "卖家头像链接": _safe_get(data, 'module', 'base', 'avatar', 'avatar'),
        "卖家个性签名": _safe_get(data, 'module', 'base', 'introduction', default=''),
        "卖家在售/已售商品数": _safe_get(data, 'module', 'tabs', 'item', 'number'),
        "卖家收到的评价总数": _safe_get(data, 'module', 'tabs', 'rate', 'number'),
        "卖家信用等级": seller_credit.get('text', '暂无'),
        "买家信用等级": buyer_credit.get('text', '暂无')
    }


def _parse_user_items_data(items_json: list) -> list:
    """Parse user's goods list API JSON data."""
    parsed_list = []
    for card in items_json:
        data = card.get('cardData', {})
        status_code = data.get('itemStatus')
        if status_code == 0:
            status_text = "在售"
        elif status_code == 1:
            status_text = "已售"
        else:
            status_text = f"未知状态 ({status_code})"

        parsed_list.append({
            "商品ID": data.get('id'),
            "商品标题": data.get('title'),
            "商品价格": data.get('priceInfo', {}).get('price'),
            "商品主图": data.get('picInfo', {}).get('picUrl'),
            "商品状态": status_text
        })
    return parsed_list


def _parse_ratings_data(ratings_json: list) -> list:
    """Parse ratings list API JSON data."""
    parsed_list = []
    for card in ratings_json:
        data = _safe_get(card, 'cardData', default={})
        rate_tag = _safe_get(data, 'rateTagList', 0, 'text', default='未知角色')
        rate_type = _safe_get(data, 'rate')
        if rate_type == 1:
            rate_text = "好评"
        elif rate_type == 0:
            rate_text = "中评"
        elif rate_type == -1:
            rate_text = "差评"
        else:
            rate_text = "未知"
        parsed_list.append({
            "评价ID": data.get('rateId'),
            "评价内容": data.get('feedback'),
            "评价类型": rate_text,
            "评价来源角色": rate_tag,
            "评价者昵称": data.get('raterUserNick'),
            "评价时间": data.get('gmtCreate'),
            "评价图片": _safe_get(data, 'pictCdnUrlList', default=[])
        })
    return parsed_list


def _calculate_reputation_from_ratings(ratings_json: list) -> dict:
    """Calculate seller and buyer positive rating stats from raw ratings data."""
    seller_total = 0
    seller_positive = 0
    buyer_total = 0
    buyer_positive = 0

    for card in ratings_json:
        data = _safe_get(card, 'cardData', default={})
        role_tag = _safe_get(data, 'rateTagList', 0, 'text', default='')
        rate_type = _safe_get(data, 'rate')  # 1=好评, 0=中评, -1=差评

        if "卖家" in role_tag:
            seller_total += 1
            if rate_type == 1:
                seller_positive += 1
        elif "买家" in role_tag:
            buyer_total += 1
            if rate_type == 1:
                buyer_positive += 1

    # Calculate rates, handle division by zero
    seller_rate = f"{(seller_positive / seller_total * 100):.2f}%" if seller_total > 0 else "N/A"
    buyer_rate = f"{(buyer_positive / buyer_total * 100):.2f}%" if buyer_total > 0 else "N/A"

    return {
        "作为卖家的好评数": f"{seller_positive}/{seller_total}",
        "作为卖家的好评率": seller_rate,
        "作为买家的好评数": f"{buyer_positive}/{buyer_total}",
        "作为买家的好评率": buyer_rate
    }


# ============== Core Scraping Functions ==============

async def _scroll_and_capture_items(page: Page, stop_event: asyncio.Event) -> None:
    """Scroll page to capture all items."""
    while not stop_event.is_set():
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=8)
        except asyncio.TimeoutError:
            logger.debug("Item scroll timeout - may have loaded all items")
            break


async def _scroll_and_capture_ratings(page: Page, stop_event: asyncio.Event) -> None:
    """Scroll page to capture all ratings."""
    while not stop_event.is_set():
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=8)
        except asyncio.TimeoutError:
            logger.debug("Rating scroll timeout - may have loaded all ratings")
            break


async def get_seller_profile(
    user_id: str,
    include_items: bool = True,
    include_ratings: bool = True,
    **_: Any,
) -> dict[str, Any]:
    """
    Scrape a seller's profile page to get their information, goods, and ratings.

    Args:
        user_id: The seller's user ID (sellerId).
        include_items: Whether to include the seller's goods list (default: True).
        include_ratings: Whether to include the seller's ratings list (default: True).
        Note: For stability and response speed, this tool always returns up to 10
        items and 10 ratings.

    Returns:
        Dictionary containing seller profile information.
    """
    logger.info(f"Tool called: get_seller_profile (user_id: {user_id})")

    if not user_id:
        return {"success": False, "message": "user_id 是必填参数"}

    max_items = 10
    max_ratings = 10

    browser_manager = get_browser_manager()
    profile_data = {"success": True, "user_id": user_id}

    try:
        async with browser_manager.new_tab() as page:
            # Prepare futures and containers
            head_api_future = asyncio.get_event_loop().create_future()
            all_items, all_ratings = [], []
            stop_item_scrolling, stop_rating_scrolling = asyncio.Event(), asyncio.Event()

            async def handle_response(response: Response):
                # Capture header summary API
                if "mtop.idle.web.user.page.head" in response.url and not head_api_future.done():
                    try:
                        head_api_future.set_result(await response.json())
                        logger.debug("Captured user header API response")
                    except Exception as e:
                        if not head_api_future.done():
                            head_api_future.set_exception(e)

                # Capture goods list API
                elif "mtop.idle.web.xyh.item.list" in response.url and include_items:
                    try:
                        data = await response.json()
                        items = data.get('data', {}).get('cardList', [])
                        all_items.extend(items)
                        logger.debug(f"Captured {len(items)} items, total: {len(all_items)}")
                        if not data.get('data', {}).get('nextPage', True) or len(all_items) >= max_items:
                            stop_item_scrolling.set()
                    except Exception:
                        stop_item_scrolling.set()

                # Capture ratings list API
                elif "mtop.idle.web.trade.rate.list" in response.url and include_ratings:
                    try:
                        data = await response.json()
                        ratings = data.get('data', {}).get('cardList', [])
                        all_ratings.extend(ratings)
                        logger.debug(f"Captured {len(ratings)} ratings, total: {len(all_ratings)}")
                        if not data.get('data', {}).get('nextPage', True) or len(all_ratings) >= max_ratings:
                            stop_rating_scrolling.set()
                    except Exception:
                        stop_rating_scrolling.set()

            page.on("response", handle_response)

            # Navigate to seller profile page
            logger.info(f"Navigating to seller profile: {user_id}")
            await page.goto(
                f"https://www.goofish.com/personal?userId={user_id}",
                wait_until="domcontentloaded",
                timeout=20000
            )

            # Wait for header API
            try:
                head_data = await asyncio.wait_for(head_api_future, timeout=15)
                profile_data.update(_parse_user_head_data(head_data))
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for header API")
                profile_data["warning"] = "未能获取卖家基本信息"

            # Scroll to capture items
            if include_items:
                logger.info("Scrolling to capture items...")
                await random_delay(2000, 4000)
                await _scroll_and_capture_items(page, stop_item_scrolling)
                profile_data["卖家发布的商品列表"] = _parse_user_items_data(all_items[:max_items])
                profile_data["商品总数"] = len(profile_data["卖家发布的商品列表"])

            # Click ratings tab and scroll to capture ratings
            if include_ratings:
                logger.info("Clicking ratings tab and scrolling...")
                rating_tab_locator = page.locator("li:has-text('信用及评价')")
                if await rating_tab_locator.count() > 0:
                    await rating_tab_locator.first.click()
                    await random_delay(3000, 5000)
                    await _scroll_and_capture_ratings(page, stop_rating_scrolling)
                    profile_data['卖家收到的评价列表'] = _parse_ratings_data(all_ratings[:max_ratings])
                    profile_data["评价总数"] = len(profile_data['卖家收到的评价列表'])
                    reputation_stats = _calculate_reputation_from_ratings(all_ratings)
                    profile_data.update(reputation_stats)
                else:
                    logger.warning("Ratings tab not found")
                    profile_data["评价警告"] = "未找到评价选项卡"

            page.remove_listener("response", handle_response)

    except Exception as e:
        logger.error(f"Error scraping seller profile: {e}")
        return {
            "success": False,
            "user_id": user_id,
            "message": f"采集卖家信息时出错: {e}",
            "error": str(e)
        }

    return profile_data


# Tool definitions for MCP registration
SELLER_TOOLS: list[dict[str, Any]] = []
