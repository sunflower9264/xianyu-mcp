"""Favorite-related Xianyu API mixin."""

import json
import time
import urllib.parse
from typing import Any

import httpx

from xianyu_mcp.logging import get_logger

logger = get_logger("xianyu_api_client")


class XianyuFavoriteApiMixin:
    """Favorite and unfavorite API operations."""

    FAVORITE_API_NAME = "mtop.taobao.idle.collect.item"
    FAVORITE_ENDPOINT = f"https://h5api.m.goofish.com/h5/{FAVORITE_API_NAME}/1.0/"
    UNFAVORITE_API_NAME = "com.taobao.idle.unfavor.item"
    UNFAVORITE_ENDPOINT = f"https://h5api.m.goofish.com/h5/{UNFAVORITE_API_NAME}/1.0/"
    FAVORITE_LIST_API_NAME = "mtop.taobao.idle.web.favor.item.list"
    FAVORITE_LIST_ENDPOINT = f"https://h5api.m.goofish.com/h5/{FAVORITE_LIST_API_NAME}/1.0/"

    async def add_favorite(self, item_id: str) -> dict[str, Any]:
        """Add a product to favorites.

        API: mtop.taobao.idle.collect.item

        Args:
            item_id: The product item ID.

        Returns:
            Dictionary with operation result.
        """
        logger.info(f"Adding favorite: item_id={item_id}")
        return await self._favorite_operation(
            item_id=item_id,
            api_name=self.FAVORITE_API_NAME,
            endpoint=self.FAVORITE_ENDPOINT,
            action="add",
        )

    async def remove_favorite(self, item_id: str) -> dict[str, Any]:
        """Remove a product from favorites.

        API: com.taobao.idle.unfavor.item

        Args:
            item_id: The product item ID.

        Returns:
            Dictionary with operation result.
        """
        logger.info(f"Removing favorite: item_id={item_id}")
        return await self._favorite_operation(
            item_id=item_id,
            api_name=self.UNFAVORITE_API_NAME,
            endpoint=self.UNFAVORITE_ENDPOINT,
            action="remove",
        )

    async def get_favorites(
        self,
        page_number: int = 1,
        rows_per_page: int = 20,
        favorite_type: str = "DEFAULT",
    ) -> dict[str, Any]:
        """Get user's favorite items list.

        API: mtop.taobao.idle.web.favor.item.list

        Args:
            page_number: Page number (starts from 1).
            rows_per_page: Number of items per page.
            favorite_type: Type of favorites - "DEFAULT" for normal favorites.

        Returns:
            Dictionary with favorite items list and metadata.
        """
        logger.info(f"Getting favorites: page={page_number}, rows={rows_per_page}")

        # Use unified cookie/token check
        success, error_response, token = self._check_cookies_and_token()
        if not success:
            error_response["page"] = page_number
            return error_response

        cookies = self._get_cookies_dict()

        # Build payload
        payload = json.dumps(
            {
                "pageNumber": page_number,
                "rowsPerPage": rows_per_page,
                "type": favorite_type,
            },
            ensure_ascii=False,
        )

        # Calculate signature
        timestamp = int(time.time() * 1000)
        sign = self._calculate_sign(token, timestamp, payload)

        # Build request
        query_string = self._build_query_string(
            api_name=self.FAVORITE_LIST_API_NAME,
            sign=sign,
            timestamp=timestamp,
            extra_params={
                "spm_cnt": "a21ybx.collection.0.0",
                "spm_pre": "a21ybx.bought.menu.4",
            },
        )

        url = f"{self.FAVORITE_LIST_ENDPOINT}?{query_string}"
        form_body = f"data={urllib.parse.quote(payload, safe='')}"

        headers = self.HEADERS.copy()
        headers["referer"] = "https://www.goofish.com/collection"
        headers["cookie"] = self._build_cookie_header(cookies)

        try:
            client = await self._get_client()
            response = await client.post(
                url,
                content=form_body,
                headers=headers,
            )

            if not response.is_success:
                return {
                    "items": [],
                    "total_count": 0,
                    "page": page_number,
                    "has_more": False,
                    "message": f"HTTP error: {response.status_code}",
                    "error": "HTTP_ERROR",
                }

            return self._parse_favorites_result(page_number, rows_per_page, response.text)

        except httpx.TimeoutException:
            logger.error("Get favorites request timed out")
            return {
                "items": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": "Request timed out",
                "error": "TIMEOUT",
            }
        except Exception as e:
            logger.error(f"Get favorites request failed: {e}")
            return {
                "items": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": f"Request failed: {e}",
                "error": str(e),
            }

    def _parse_favorites_result(
        self, page_number: int, rows_per_page: int, response_text: str
    ) -> dict[str, Any]:
        """Parse favorites list API response.

        Response structure:
        {
            "data": {
                "items": [
                    {
                        "id": "703178076102",
                        "title": "...",
                        "price": "8",
                        "picUrl": "...",
                        "area": "澄海区",
                        "userNick": "模***后",
                        "favorTime": "2026-03-03 15:50:31",
                        ...
                    }
                ]
            }
        }

        Args:
            page_number: Current page number.
            rows_per_page: Number of items per page.
            response_text: Raw API response text.

        Returns:
            Dictionary with favorite items list and metadata.
        """
        # Use unified response parsing
        success, data, error_msg = self._parse_api_response(response_text, "favorites")
        if not success:
            return {
                "items": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": error_msg,
                "error": "API_ERROR" if "risk control" in error_msg.lower() else "PARSE_ERROR",
            }

        if not data:
            return {
                "items": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": "No data in response",
            }

        # Parse items list (direct array, not nested like search results)
        raw_items = data.get("items", [])
        if not raw_items:
            return {
                "items": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": "No favorite items found",
            }

        items = []
        for raw_item in raw_items:
            try:
                # Item ID
                item_id = raw_item.get("id")
                if not item_id:
                    continue

                favorite_item = {
                    "item_id": str(item_id),
                    "url": f"https://www.goofish.com/item?id={item_id}",
                }

                # Image URL
                favorite_item["image_url"] = raw_item.get("picUrl")

                # Title
                full_title = raw_item.get("title", "")
                if full_title:
                    favorite_item["detail"] = full_title
                    if len(full_title) > 50:
                        favorite_item["title"] = full_title[:50] + "..."
                    else:
                        favorite_item["title"] = full_title

                # Price (string format, e.g., "8", "5900")
                price_text = raw_item.get("price")
                if price_text:
                    try:
                        favorite_item["price"] = float(price_text)
                    except (ValueError, TypeError):
                        favorite_item["price"] = price_text

                # Location (area field)
                favorite_item["location"] = raw_item.get("area")

                # Seller nickname
                favorite_item["seller_nickname"] = raw_item.get("userNick")

                # Favor time
                if raw_item.get("favorTime"):
                    favorite_item["favor_time"] = raw_item.get("favorTime")

                # User avatar
                if raw_item.get("userAvatar"):
                    favorite_item["seller_avatar"] = raw_item.get("userAvatar")

                items.append(favorite_item)

            except Exception as e:
                logger.debug(f"Error parsing favorite item: {e}")
                continue

        logger.info(f"Parsed {len(items)} favorite items")
        has_more = self._extract_has_more(data)
        return {
            "items": items,
            "total_count": len(items),
            "page": page_number,
            "has_more": bool(has_more) if has_more is not None else False,
            "message": f"Got {len(items)} favorite items",
        }

    async def _favorite_operation(
        self,
        item_id: str,
        api_name: str,
        endpoint: str,
        action: str,
    ) -> dict[str, Any]:
        """Perform a favorite/unfavorite operation.

        Args:
            item_id: The product item ID.
            api_name: The API name for the operation.
            endpoint: The API endpoint URL.
            action: "add" or "remove".

        Returns:
            Dictionary with operation result.
        """
        # Use unified cookie/token check
        success, error_response, token = self._check_cookies_and_token()
        if not success:
            error_response["item_id"] = item_id
            error_response["success"] = False
            return {k: v for k, v in error_response.items() if k not in ["items", "total_count", "has_more"]}

        cookies = self._get_cookies_dict()

        # Build payload
        payload = json.dumps({"itemId": item_id}, ensure_ascii=False)

        # Calculate signature
        timestamp = int(time.time() * 1000)
        sign = self._calculate_sign(token, timestamp, payload)

        # Build request
        query_string = self._build_query_string(
            api_name=api_name,
            sign=sign,
            timestamp=timestamp,
            extra_params={
                "needLoginPC": "true",
                "spm_cnt": "a21ybx.item.0.0",
            },
        )

        url = f"{endpoint}?{query_string}"
        form_body = f"data={urllib.parse.quote(payload, safe='')}"

        headers = self.HEADERS.copy()
        headers["referer"] = f"https://www.goofish.com/item?id={item_id}"
        headers["cookie"] = self._build_cookie_header(cookies)

        try:
            client = await self._get_client()
            response = await client.post(
                url,
                content=form_body,
                headers=headers,
            )

            if not response.is_success:
                return {
                    "success": False,
                    "item_id": item_id,
                    "message": f"HTTP error: {response.status_code}",
                    "error": "HTTP_ERROR",
                }

            # Use unified response parsing
            success, data, error_msg = self._parse_api_response(response.text, f"favorite_{action}")
            if success:
                action_label = "added to" if action == "add" else "removed from"
                return {
                    "success": True,
                    "item_id": item_id,
                    "message": f"Item {item_id} {action_label} favorites",
                }
            return {
                "success": False,
                "item_id": item_id,
                "message": error_msg,
                "error": "API_ERROR",
            }

        except httpx.TimeoutException:
            logger.error(f"Favorite {action} request timed out")
            return {
                "success": False,
                "item_id": item_id,
                "message": "Request timed out",
                "error": "TIMEOUT",
            }
        except Exception as e:
            logger.error(f"Favorite {action} request failed: {e}")
            return {
                "success": False,
                "item_id": item_id,
                "message": f"Request failed: {e}",
                "error": str(e),
            }
