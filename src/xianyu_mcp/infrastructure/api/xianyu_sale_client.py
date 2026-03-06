"""Sale-related Xianyu API mixin."""

import json
import time
import urllib.parse
from typing import Any, Optional

import httpx

from xianyu_mcp.logging import get_logger

logger = get_logger("xianyu_api_client")


class XianyuSaleApiMixin:
    """Sale/manage API operations: login user, my goods list, take down, delete."""

    # Get login user ID
    LOGIN_USER_API_NAME = "mtop.taobao.idlemessage.pc.loginuser.get"
    LOGIN_USER_ENDPOINT = f"https://h5api.m.goofish.com/h5/{LOGIN_USER_API_NAME}/1.0/"

    # My goods list
    MY_GOODS_API_NAME = "mtop.idle.web.xyh.item.list"
    MY_GOODS_ENDPOINT = f"https://h5api.m.goofish.com/h5/{MY_GOODS_API_NAME}/1.0/"

    # Take down (downshelf)
    DOWNSHELF_API_NAME = "mtop.taobao.idle.item.downshelf"
    DOWNSHELF_ENDPOINT = f"https://h5api.m.goofish.com/h5/{DOWNSHELF_API_NAME}/2.0/"

    # Delete
    DELETE_API_NAME = "com.taobao.idle.item.delete"
    DELETE_ENDPOINT = f"https://h5api.m.goofish.com/h5/{DELETE_API_NAME}/1.1/"

    async def get_login_user_id(self) -> dict[str, Any]:
        """Get the logged-in user's ID.

        API: mtop.taobao.idlemessage.pc.loginuser.get

        Returns:
            Dictionary with user_id or error info.
        """
        logger.info("Getting login user ID")

        success, error_response, token = self._check_cookies_and_token()
        if not success:
            return {
                "success": False,
                "user_id": None,
                "message": error_response.get("message", "Authentication error"),
                "error": error_response.get("error", "AUTH_ERROR"),
            }

        cookies = self._get_cookies_dict()

        # This API takes no meaningful payload
        payload = "{}"

        timestamp = int(time.time() * 1000)
        sign = self._calculate_sign(token, timestamp, payload)

        query_string = self._build_query_string(
            api_name=self.LOGIN_USER_API_NAME,
            sign=sign,
            timestamp=timestamp,
            extra_params={
                "spm_cnt": "a21ybx.personal.0.0",
            },
        )

        url = f"{self.LOGIN_USER_ENDPOINT}?{query_string}"
        form_body = f"data={urllib.parse.quote(payload, safe='')}"

        headers = self.HEADERS.copy()
        headers["referer"] = "https://www.goofish.com/personal"
        headers["cookie"] = self._build_cookie_header(cookies)

        try:
            client = await self._get_client()
            response = await client.post(url, content=form_body, headers=headers)

            if not response.is_success:
                return {
                    "success": False,
                    "user_id": None,
                    "message": f"HTTP error: {response.status_code}",
                    "error": "HTTP_ERROR",
                }

            ok, data, error_msg = self._parse_api_response(response.text, "login_user")
            if ok and data:
                user_id = data.get("userId")
                return {
                    "success": True,
                    "user_id": str(user_id) if user_id else None,
                }
            return {
                "success": False,
                "user_id": None,
                "message": error_msg or "Failed to get user ID",
                "error": "API_ERROR",
            }

        except httpx.TimeoutException:
            logger.error("Get login user request timed out")
            return {"success": False, "user_id": None, "message": "Request timed out", "error": "TIMEOUT"}
        except Exception as e:
            logger.error(f"Get login user request failed: {e}")
            return {"success": False, "user_id": None, "message": f"Request failed: {e}", "error": str(e)}

    async def get_my_goods_list(
        self,
        page_number: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get the logged-in user's goods list.

        API: mtop.idle.web.xyh.item.list

        Args:
            page_number: Page number (starts from 1).
            page_size: Number of items per page.
            status: Optional status filter (not yet supported upstream).

        Returns:
            Dictionary with goods list and metadata.
        """
        logger.info(f"Getting my goods: page={page_number}, size={page_size}, status={status}")

        # First, get logged-in user ID
        user_result = await self.get_login_user_id()
        if not user_result.get("success") or not user_result.get("user_id"):
            return {
                "success": False,
                "goods": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": user_result.get("message", "Failed to get user ID. Please login first."),
                "error": user_result.get("error", "AUTH_ERROR"),
            }

        user_id = user_result["user_id"]

        success, error_response, token = self._check_cookies_and_token()
        if not success:
            return {
                "success": False,
                "goods": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": error_response.get("message", "Authentication error"),
                "error": error_response.get("error", "AUTH_ERROR"),
            }

        cookies = self._get_cookies_dict()

        payload = json.dumps(
            {
                "needGroupInfo": True,
                "pageNumber": page_number,
                "userId": user_id,
                "pageSize": page_size,
            },
            ensure_ascii=False,
        )

        timestamp = int(time.time() * 1000)
        sign = self._calculate_sign(token, timestamp, payload)

        query_string = self._build_query_string(
            api_name=self.MY_GOODS_API_NAME,
            sign=sign,
            timestamp=timestamp,
            extra_params={
                "spm_cnt": "a21ybx.personal.0.0",
            },
        )

        url = f"{self.MY_GOODS_ENDPOINT}?{query_string}"
        form_body = f"data={urllib.parse.quote(payload, safe='')}"

        headers = self.HEADERS.copy()
        headers["referer"] = "https://www.goofish.com/personal"
        headers["cookie"] = self._build_cookie_header(cookies)

        try:
            client = await self._get_client()
            response = await client.post(url, content=form_body, headers=headers)

            if not response.is_success:
                return {
                    "success": False,
                    "goods": [],
                    "total_count": 0,
                    "page": page_number,
                    "has_more": False,
                    "message": f"HTTP error: {response.status_code}",
                    "error": "HTTP_ERROR",
                }

            return self._parse_my_goods_result(page_number, status, response.text)

        except httpx.TimeoutException:
            logger.error("Get my goods request timed out")
            return {
                "success": False,
                "goods": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": "Request timed out",
                "error": "TIMEOUT",
            }
        except Exception as e:
            logger.error(f"Get my goods request failed: {e}")
            return {
                "success": False,
                "goods": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": f"Request failed: {e}",
                "error": str(e),
            }

    def _parse_my_goods_result(
        self,
        page_number: int,
        status_filter: Optional[str],
        response_text: str,
    ) -> dict[str, Any]:
        """Parse my goods list API response.

        itemStatus mapping:
            0 = selling (在售)
            1 = sold (已卖出)
            2 = taken_down (已下架)

        Args:
            page_number: Current page number.
            status_filter: Optional status filter string.
            response_text: Raw API response text.

        Returns:
            Dictionary with goods list and metadata.
        """
        STATUS_MAP = {
            0: "selling",
            1: "sold",
            2: "taken_down",
        }

        FILTER_MAP = {
            "selling": 0,
            "sold": 1,
            "taken_down": 2,
        }

        ok, data, error_msg = self._parse_api_response(response_text, "my_goods")
        if not ok:
            return {
                "success": False,
                "goods": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": error_msg,
                "error": "API_ERROR",
            }

        if not data:
            return {
                "success": True,
                "goods": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": "No data in response",
            }

        card_list = data.get("cardList", [])
        next_page = data.get("nextPage", False)

        goods = []
        for card in card_list:
            try:
                card_data = card.get("cardData")
                if not card_data:
                    continue

                item_id = card_data.get("id")
                if not item_id:
                    continue

                item_status_code = card_data.get("itemStatus")
                item_status = STATUS_MAP.get(item_status_code, f"unknown({item_status_code})")

                # Apply status filter if provided
                if status_filter and status_filter in FILTER_MAP:
                    if item_status_code != FILTER_MAP[status_filter]:
                        continue

                detail_params = card_data.get("detailParams", {})
                price_info = card_data.get("priceInfo", {})
                pic_info = card_data.get("picInfo", {})

                item = {
                    "item_id": str(item_id),
                    "title": card_data.get("title", ""),
                    "status": item_status,
                    "url": f"https://www.goofish.com/item?id={item_id}",
                }

                # Price
                price_text = price_info.get("price")
                if price_text:
                    try:
                        item["price"] = float(price_text)
                    except (ValueError, TypeError):
                        item["price"] = price_text

                # Image
                item["image_url"] = pic_info.get("picUrl")

                # Category
                category_id = card_data.get("categoryId")
                if category_id:
                    item["category_id"] = category_id

                # Shipping info from detail params
                post_info = detail_params.get("postInfo")
                if post_info:
                    item["shipping"] = post_info

                goods.append(item)

            except Exception as e:
                logger.debug(f"Error parsing my goods item: {e}")
                continue

        logger.info(f"Parsed {len(goods)} goods from my goods list")
        return {
            "success": True,
            "goods": goods,
            "total_count": len(goods),
            "page": page_number,
            "has_more": next_page,
            "status_filter": status_filter,
            "message": f"Got {len(goods)} goods",
        }

    async def take_down_item(self, item_id: str) -> dict[str, Any]:
        """Take down (downshelf) a published item.

        API: mtop.taobao.idle.item.downshelf v2.0

        Args:
            item_id: The item ID to take down.

        Returns:
            Dictionary with operation result.
        """
        logger.info(f"Taking down item: {item_id}")

        success, error_response, token = self._check_cookies_and_token()
        if not success:
            return {
                "success": False,
                "item_id": item_id,
                "message": error_response.get("message", "Authentication error"),
                "error": error_response.get("error", "AUTH_ERROR"),
            }

        cookies = self._get_cookies_dict()

        payload = json.dumps({"itemId": item_id}, ensure_ascii=False)

        timestamp = int(time.time() * 1000)
        sign = self._calculate_sign(token, timestamp, payload)

        query_string = self._build_query_string(
            api_name=self.DOWNSHELF_API_NAME,
            sign=sign,
            timestamp=timestamp,
            extra_params={
                "v": "2.0",
                "spm_cnt": "a21ybx.item.0.0",
            },
        )

        url = f"{self.DOWNSHELF_ENDPOINT}?{query_string}"
        form_body = f"data={urllib.parse.quote(payload, safe='')}"

        headers = self.HEADERS.copy()
        headers["referer"] = f"https://www.goofish.com/item?id={item_id}"
        headers["cookie"] = self._build_cookie_header(cookies)

        try:
            client = await self._get_client()
            response = await client.post(url, content=form_body, headers=headers)

            if not response.is_success:
                return {
                    "success": False,
                    "item_id": item_id,
                    "message": f"HTTP error: {response.status_code}",
                    "error": "HTTP_ERROR",
                }

            ok, data, error_msg = self._parse_api_response(response.text, "downshelf")
            if ok:
                api_success = data.get("success", False) if data else True
                if api_success:
                    return {
                        "success": True,
                        "item_id": item_id,
                        "message": f"Item {item_id} has been taken down successfully",
                    }
                return {
                    "success": False,
                    "item_id": item_id,
                    "message": "API returned success=false for downshelf",
                    "error": "DOWNSHELF_FAILED",
                }
            return {
                "success": False,
                "item_id": item_id,
                "message": error_msg,
                "error": "API_ERROR",
            }

        except httpx.TimeoutException:
            logger.error("Downshelf request timed out")
            return {"success": False, "item_id": item_id, "message": "Request timed out", "error": "TIMEOUT"}
        except Exception as e:
            logger.error(f"Downshelf request failed: {e}")
            return {"success": False, "item_id": item_id, "message": f"Request failed: {e}", "error": str(e)}

    async def delete_item(self, item_id: str) -> dict[str, Any]:
        """Permanently delete a published item.

        API: com.taobao.idle.item.delete v1.1

        Args:
            item_id: The item ID to delete.

        Returns:
            Dictionary with operation result.
        """
        logger.info(f"Deleting item: {item_id}")

        success, error_response, token = self._check_cookies_and_token()
        if not success:
            return {
                "success": False,
                "item_id": item_id,
                "message": error_response.get("message", "Authentication error"),
                "error": error_response.get("error", "AUTH_ERROR"),
            }

        cookies = self._get_cookies_dict()

        payload = json.dumps({"itemId": item_id}, ensure_ascii=False)

        timestamp = int(time.time() * 1000)
        sign = self._calculate_sign(token, timestamp, payload)

        query_string = self._build_query_string(
            api_name=self.DELETE_API_NAME,
            sign=sign,
            timestamp=timestamp,
            extra_params={
                "v": "1.1",
                "spm_cnt": "a21ybx.item.0.0",
            },
        )

        url = f"{self.DELETE_ENDPOINT}?{query_string}"
        form_body = f"data={urllib.parse.quote(payload, safe='')}"

        headers = self.HEADERS.copy()
        headers["referer"] = f"https://www.goofish.com/item?id={item_id}"
        headers["cookie"] = self._build_cookie_header(cookies)

        try:
            client = await self._get_client()
            response = await client.post(url, content=form_body, headers=headers)

            if not response.is_success:
                return {
                    "success": False,
                    "item_id": item_id,
                    "message": f"HTTP error: {response.status_code}",
                    "error": "HTTP_ERROR",
                }

            ok, data, error_msg = self._parse_api_response(response.text, "delete")
            if ok:
                api_success = data.get("success", True) if isinstance(data, dict) else True
                if api_success is False:
                    return {
                        "success": False,
                        "item_id": item_id,
                        "message": "API returned success=false for delete",
                        "error": "DELETE_FAILED",
                    }
                return {
                    "success": True,
                    "item_id": item_id,
                    "message": f"Item {item_id} has been deleted permanently",
                }
            return {
                "success": False,
                "item_id": item_id,
                "message": error_msg,
                "error": "API_ERROR",
            }

        except httpx.TimeoutException:
            logger.error("Delete request timed out")
            return {"success": False, "item_id": item_id, "message": "Request timed out", "error": "TIMEOUT"}
        except Exception as e:
            logger.error(f"Delete request failed: {e}")
            return {"success": False, "item_id": item_id, "message": f"Request failed: {e}", "error": str(e)}
