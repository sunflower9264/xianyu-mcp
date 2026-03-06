"""Goods-related Xianyu API mixin."""

import json
import time
import urllib.parse
from typing import Any, Optional

import httpx

from xianyu_mcp.logging import get_logger

logger = get_logger("xianyu_api_client")


class XianyuGoodsApiMixin:
    """Goods/search/detail API operations."""

    SEARCH_API_NAME = "mtop.taobao.idlemtopsearch.pc.search"
    SEARCH_ENDPOINT = f"https://h5api.m.goofish.com/h5/{SEARCH_API_NAME}/1.0/"
    DETAIL_API_NAME = "mtop.taobao.idle.pc.detail"
    DETAIL_ENDPOINT = f"https://h5api.m.goofish.com/h5/{DETAIL_API_NAME}/1.0/"
    FEED_API_NAME = "mtop.taobao.idlehome.home.webpc.feed"
    FEED_ENDPOINT = f"https://h5api.m.goofish.com/h5/{FEED_API_NAME}/1.0/"

    def _build_search_payload(
        self,
        keyword: str,
        page_number: int = 1,
        rows_per_page: int = 30,
        price_min: Optional[str] = None,
        price_max: Optional[str] = None,
        sort_field: Optional[str] = None,
        sort_value: Optional[str] = None,
        quick_filters: Optional[list[str]] = None,
    ) -> str:
        """Build search request payload.

        Args:
            keyword: Search keyword.
            page_number: Page number (starts from 1).
            rows_per_page: Number of items per page.
            price_min: Minimum price filter.
            price_max: Maximum price filter.
            sort_field: Sort field (create, modify, credit, reduce, price, or empty for default).
            sort_value: Sort direction (asc, desc, credit_desc).
            quick_filters: List of quick filter types (e.g., ["filterPersonal", "filterAppraise"]).

        Returns:
            JSON payload string.
        """
        # Determine if we're using filters
        has_filters = bool(price_min or price_max or quick_filters)

        payload = {
            "pageNumber": page_number,
            "keyword": keyword,
            "fromFilter": has_filters or bool(sort_field),
            "rowsPerPage": rows_per_page,
            "sortValue": sort_value or "",
            "sortField": sort_field or "",
            "customDistance": "",
            "gps": "",
            "customGps": "",
            "searchReqFromPage": "pcSearch",
            "extraFilterValue": "{}",
            "userPositionJson": "{}",
        }

        # Build search filter
        search_filter_parts = []

        if price_min is not None or price_max is not None:
            min_val = price_min or "1"
            max_val = price_max or ""
            search_filter_parts.append(f"priceRange:{min_val},{max_val}")

        # Add quick filters
        if quick_filters:
            for qf in quick_filters:
                search_filter_parts.append(f"quickFilter:{qf}")

        if search_filter_parts:
            search_filter = ";".join(search_filter_parts) + ";"
            payload["propValueStr"] = json.dumps({"searchFilter": search_filter}, ensure_ascii=False)
        else:
            payload["propValueStr"] = json.dumps({"searchFilter": ""}, ensure_ascii=False)

        return json.dumps(payload, ensure_ascii=False)

    def _parse_search_result(self, response_text: str) -> tuple[list[dict[str, Any]], bool]:
        """Parse search API response.

        Args:
            response_text: Raw API response text.

        Returns:
            Tuple of (product list, has_more flag).
        """
        # Use unified response parsing
        success, data, _ = self._parse_api_response(response_text, "search")
        if not success or not data:
            return [], False

        result_list = data.get("resultList", [])
        if not result_list:
            logger.info("Search returned empty result list")
            return [], False

        products = []
        for item in result_list:
            try:
                item_data = item.get("data")
                if not item_data:
                    continue

                item_main = item_data.get("item")
                if not item_main:
                    continue

                main = item_main.get("main")
                if not main:
                    continue

                ex_content = main.get("exContent")
                if not ex_content:
                    continue

                product = {}

                # Item ID
                item_id = ex_content.get("itemId")
                if not item_id:
                    continue
                product["item_id"] = item_id

                # Image URL
                product["image_url"] = ex_content.get("picUrl")

                # Product URLs
                product["url"] = f"https://www.goofish.com/item?id={item_id}"
                product["mobile_url"] = self._build_mobile_url(item_id)

                # Price
                price_array = ex_content.get("price", [])
                if isinstance(price_array, list) and len(price_array) >= 2:
                    price_obj = price_array[1] if isinstance(price_array[1], dict) else {}
                    price_text = price_obj.get("text")
                    if price_text:
                        try:
                            product["price"] = float(price_text)
                        except (ValueError, TypeError):
                            product["price"] = price_text

                # Location
                product["location"] = ex_content.get("area")

                # Seller nickname
                product["seller_nickname"] = ex_content.get("userNickName")

                # Title
                detail_params = ex_content.get("detailParams", {})
                full_title = detail_params.get("title") or ex_content.get("title", "")
                if full_title:
                    product["detail"] = full_title
                    if len(full_title) > 50:
                        product["title"] = full_title[:50] + "..."
                    else:
                        product["title"] = full_title

                products.append(product)

            except Exception as e:
                logger.debug(f"Error parsing product item: {e}")
                continue

        has_more = self._extract_has_more(data)
        logger.info(f"Parsed {len(products)} products from search result")
        return products, bool(has_more) if has_more is not None else False

    async def search_goods(
        self,
        keyword: str,
        page_number: int = 1,
        rows_per_page: int = 30,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        sort_field: Optional[str] = None,
        sort_value: Optional[str] = None,
        quick_filters: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Search for products on Xianyu.

        Args:
            keyword: Search keyword.
            page_number: Page number (starts from 1).
            rows_per_page: Number of items per page.
            price_min: Minimum price filter.
            price_max: Maximum price filter.
            sort_field: Sort field (create, modify, credit, reduce, price, or empty for default).
            sort_value: Sort direction (asc, desc, credit_desc).
            quick_filters: List of quick filter types.

        Returns:
            Dictionary with search results and metadata.
        """
        logger.info(
            f"Searching products: keyword={keyword}, page={page_number}, "
            f"rows={rows_per_page}, price_range={price_min}-{price_max}, "
            f"sort_field={sort_field}, sort_value={sort_value}, "
            f"quick_filters={quick_filters}"
        )

        # Use unified cookie/token check
        success, error_response, token = self._check_cookies_and_token()
        if not success:
            error_response["keyword"] = keyword
            error_response["page"] = page_number
            return error_response

        cookies = self._get_cookies_dict()

        # Build payload
        price_min_str = str(int(price_min)) if price_min is not None else None
        price_max_str = str(int(price_max)) if price_max is not None else None

        payload = self._build_search_payload(
            keyword=keyword,
            page_number=page_number,
            rows_per_page=rows_per_page,
            price_min=price_min_str,
            price_max=price_max_str,
            sort_field=sort_field,
            sort_value=sort_value,
            quick_filters=quick_filters,
        )

        # Calculate signature
        timestamp = int(time.time() * 1000)
        sign = self._calculate_sign(token, timestamp, payload)

        # Build request
        query_string = self._build_query_string(
            api_name=self.SEARCH_API_NAME,
            sign=sign,
            timestamp=timestamp,
            extra_params={"spm_pre": "a21ybx.home.searchInput.0"},
        )

        url = f"{self.SEARCH_ENDPOINT}?{query_string}"
        form_body = f"data={urllib.parse.quote(payload, safe='')}"

        headers = self.HEADERS.copy()
        headers["referer"] = "https://www.goofish.com/"
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
                    "keyword": keyword,
                    "items": [],
                    "total_count": 0,
                    "page": page_number,
                    "has_more": False,
                    "message": f"HTTP error: {response.status_code}",
                    "error": "HTTP_ERROR",
                }

            products, has_more = self._parse_search_result(response.text)

            return {
                "keyword": keyword,
                "items": products,
                "total_count": len(products),
                "page": page_number,
                "has_more": has_more,
                "message": f"Found {len(products)} items for '{keyword}'",
            }

        except httpx.TimeoutException:
            logger.error("Search request timed out")
            return {
                "keyword": keyword,
                "items": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": "Request timed out",
                "error": "TIMEOUT",
            }
        except Exception as e:
            logger.error(f"Search request failed: {e}")
            return {
                "keyword": keyword,
                "items": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": f"Request failed: {e}",
                "error": str(e),
            }

    async def get_home_goods(
        self,
        page_number: int = 1,
        page_size: int = 30,
    ) -> dict[str, Any]:
        """Get home goods recommendations (猜你喜欢).

        Args:
            page_number: Page number (starts from 1).
            page_size: Number of items per page.

        Returns:
            Dictionary with home goods results and metadata.
        """
        logger.info(f"Getting home goods: page={page_number}, size={page_size}")

        # Use unified cookie/token check
        success, error_response, token = self._check_cookies_and_token()
        if not success:
            error_response["page"] = page_number
            return error_response

        cookies = self._get_cookies_dict()

        # Build payload for feed API
        payload = json.dumps(
            {
                "itemId": "",
                "pageSize": page_size,
                "pageNumber": page_number,
                "machId": "",
            },
            ensure_ascii=False,
        )

        # Calculate signature
        timestamp = int(time.time() * 1000)
        sign = self._calculate_sign(token, timestamp, payload)

        # Build request
        query_string = self._build_query_string(
            api_name=self.FEED_API_NAME,
            sign=sign,
            timestamp=timestamp,
            extra_params={
                "spm_pre": "a21ybx.search.logo.1",
                "spm_cnt": "a21ybx.home.0.0",
            },
        )

        url = f"{self.FEED_ENDPOINT}?{query_string}"
        form_body = f"data={urllib.parse.quote(payload, safe='')}"

        headers = self.HEADERS.copy()
        headers["referer"] = "https://www.goofish.com/"
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

            products, has_more = self._parse_home_goods_result(response.text)

            return {
                "items": products,
                "total_count": len(products),
                "page": page_number,
                "has_more": has_more,
                "message": f"Got {len(products)} recommended items",
            }

        except httpx.TimeoutException:
            logger.error("Home goods request timed out")
            return {
                "items": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": "Request timed out",
                "error": "TIMEOUT",
            }
        except Exception as e:
            logger.error(f"Home goods request failed: {e}")
            return {
                "items": [],
                "total_count": 0,
                "page": page_number,
                "has_more": False,
                "message": f"Request failed: {e}",
                "error": str(e),
            }

    def _parse_home_goods_result(self, response_text: str) -> tuple[list[dict[str, Any]], bool]:
        """Parse home goods (feed) API response.

        The feed API returns data in a different structure from search:
        - Search: data.resultList[].data.item.main.exContent
        - Feed:   data.cardList[].cardData

        Args:
            response_text: Raw API response text.

        Returns:
            Tuple of (product list, has_more flag).
        """
        # Use unified response parsing
        success, data, _ = self._parse_api_response(response_text, "home_goods")
        if not success or not data:
            return [], False

        card_list = data.get("cardList", [])
        if not card_list:
            logger.info("Home goods returned empty card list")
            return [], False

        products = []
        for card in card_list:
            try:
                card_data = card.get("cardData")
                if not card_data:
                    continue

                # Only process item-type cards
                biz_type = card_data.get("bizType")
                if biz_type and biz_type not in ("item", "resell"):
                    continue

                product = {}

                # Item ID
                item_id = card_data.get("itemId")
                if not item_id:
                    continue
                product["item_id"] = item_id

                # Image URL - from mainPicInfo
                main_pic = card_data.get("mainPicInfo", {})
                product["image_url"] = main_pic.get("url")

                # Product URLs
                product["url"] = f"https://www.goofish.com/item?id={item_id}"
                product["mobile_url"] = self._build_mobile_url(item_id)

                # Price - from priceInfo
                price_info = card_data.get("priceInfo", {})
                price_text = price_info.get("price")
                if price_text:
                    try:
                        product["price"] = float(price_text)
                    except (ValueError, TypeError):
                        product["price"] = price_text

                # Original price
                ori_price = price_info.get("oriPrice")
                if ori_price and ori_price != "0.00":
                    try:
                        product["original_price"] = float(ori_price)
                    except (ValueError, TypeError):
                        product["original_price"] = ori_price

                # Location - from city field
                product["location"] = card_data.get("city")

                # Seller nickname - from user field
                user_info = card_data.get("user", {})
                product["seller_nickname"] = user_info.get("userNick")

                # Title - from detailParams.title or titleSummary.text
                detail_params = card_data.get("detailParams", {})
                title_summary = card_data.get("titleSummary", {})
                full_title = detail_params.get("title") or title_summary.get("text", "")
                if full_title:
                    product["detail"] = full_title
                    if len(full_title) > 50:
                        product["title"] = full_title[:50] + "..."
                    else:
                        product["title"] = full_title

                # Want count - from hotPoint
                hot_point = card_data.get("hotPoint", {})
                hot_text = hot_point.get("text", "")
                if hot_text:
                    product["want_count"] = hot_text

                products.append(product)

            except Exception as e:
                logger.debug(f"Error parsing home goods item: {e}")
                continue

        has_more = self._extract_has_more(data)
        logger.info(f"Parsed {len(products)} products from home goods result")
        return products, bool(has_more) if has_more is not None else False

    async def get_goods_detail(self, item_id: str) -> dict[str, Any]:
        """Get detailed information about a product.

        Args:
            item_id: The product item ID.

        Returns:
            Dictionary with product details.
        """
        logger.info(f"Getting product detail: item_id={item_id}")

        # Use unified cookie/token check
        success, error_response, token = self._check_cookies_and_token()
        if not success:
            # Transform error response for detail format
            return {
                "item_id": item_id,
                "message": error_response.get("message", "Authentication error"),
                "error": error_response.get("error", "AUTH_ERROR"),
            }

        cookies = self._get_cookies_dict()

        # Build payload for detail API
        payload = json.dumps({"itemId": item_id}, ensure_ascii=False)

        # Calculate signature
        timestamp = int(time.time() * 1000)
        sign = self._calculate_sign(token, timestamp, payload)

        # Build request
        query_string = self._build_query_string(
            api_name=self.DETAIL_API_NAME,
            sign=sign,
            timestamp=timestamp,
            extra_params={"spm_cnt": "a21ybx.item.0.0"},
        )

        url = f"{self.DETAIL_ENDPOINT}?{query_string}"
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
                    "item_id": item_id,
                    "message": f"HTTP error: {response.status_code}",
                    "error": "HTTP_ERROR",
                }

            return self._parse_detail_result(item_id, response.text)

        except httpx.TimeoutException:
            logger.error("Detail request timed out")
            return {
                "item_id": item_id,
                "message": "Request timed out",
                "error": "TIMEOUT",
            }
        except Exception as e:
            logger.error(f"Detail request failed: {e}")
            return {
                "item_id": item_id,
                "message": f"Request failed: {e}",
                "error": str(e),
            }

    def _parse_detail_result(self, item_id: str, response_text: str) -> dict[str, Any]:
        """Parse detail API response.

        Args:
            item_id: The item ID.
            response_text: Raw API response text.

        Returns:
            Dictionary with product details.
        """
        # Use unified response parsing
        success, data, error_msg = self._parse_api_response(response_text, "detail")
        if not success:
            return {
                "item_id": item_id,
                "message": error_msg,
                "error": "API_ERROR" if "risk control" in error_msg.lower() else "PARSE_ERROR",
            }

        if not data:
            return {
                "item_id": item_id,
                "message": "No data in response",
                "error": "NO_DATA",
            }

        result = {
            "item_id": item_id,
            "url": f"https://www.goofish.com/item?id={item_id}",
        }

        # Compatible with both old detail schema (itemInfo) and current pc.detail schema (itemDO/sellerDO)
        item_info = data.get("itemInfo") or data.get("itemDO") or {}
        if item_info:
            # Basic info
            result["title"] = item_info.get("title", "")
            result["description"] = item_info.get("desc") or item_info.get("description", "")
            result["category"] = item_info.get("categoryName", "")
            if not result["category"]:
                item_cat = item_info.get("itemCatDTO", {})
                if isinstance(item_cat, dict):
                    result["category"] = item_cat.get("catName") or item_cat.get("name") or item_cat.get("catId", "")

            # Price
            price_info = item_info.get("priceInfo", {})
            if isinstance(price_info, dict) and price_info:
                result["price"] = price_info.get("price")
                result["original_price"] = price_info.get("originalPrice")
            if "price" not in result:
                result["price"] = item_info.get("soldPrice") or item_info.get("defaultPrice")
            if "original_price" not in result:
                result["original_price"] = item_info.get("originalPrice")

            # Location
            result["location"] = item_info.get("area", "") or item_info.get("city", "")

            # Publish time
            result["publish_time"] = item_info.get("GMT_CREATE_DATE_KEY") or item_info.get("gmtCreate", "")
            publish_ts = item_info.get("createTime", item_info.get("gmtCreate", 0))
            if isinstance(publish_ts, str) and publish_ts.isdigit():
                publish_ts = int(publish_ts)
            result["publish_timestamp"] = publish_ts

            # Status
            result["status"] = item_info.get("itemStatus", "")
            result["status_desc"] = item_info.get("itemStatusDesc") or item_info.get("itemStatusStr", "")

            # Images
            pics = item_info.get("picList", [])
            images: list[str] = []
            if isinstance(pics, list):
                images.extend([p.get("url", "") for p in pics if isinstance(p, dict) and p.get("url")])

            image_infos = item_info.get("imageInfos", [])
            if isinstance(image_infos, str):
                try:
                    image_infos = json.loads(image_infos)
                except json.JSONDecodeError:
                    image_infos = []
            if isinstance(image_infos, list):
                images.extend([p.get("url", "") for p in image_infos if isinstance(p, dict) and p.get("url")])

            if not images:
                default_picture = item_info.get("defaultPicture")
                if isinstance(default_picture, str) and default_picture:
                    images.append(default_picture)
                elif isinstance(default_picture, dict):
                    url = default_picture.get("url")
                    if url:
                        images.append(url)

            # Keep order while removing duplicates
            result["images"] = list(dict.fromkeys(images))

            # View/want count
            result["view_count"] = item_info.get("viewCount", item_info.get("browseCnt", 0))
            result["want_count"] = item_info.get("wantCount", item_info.get("wantCnt", 0))

            # Seller info
            seller = item_info.get("sellerInfo")
            if not seller:
                seller = data.get("sellerDO", {})
            if seller:
                result["seller_id"] = seller.get("userId") or seller.get("sellerId", "")
                result["seller_nickname"] = seller.get("userNickName") or seller.get("nick", "")
                result["seller_avatar"] = seller.get("avatar") or seller.get("portraitUrl", "")
                result["seller_credit"] = seller.get("creditScore", 0)
                if not result.get("location"):
                    result["location"] = seller.get("publishCity") or seller.get("city", "")
                if not result.get("seller_credit"):
                    credit_tag = seller.get("idleFishCreditTag", {})
                    if isinstance(credit_tag, dict):
                        track_params = credit_tag.get("trackParams", {})
                        if isinstance(track_params, dict):
                            result["seller_credit"] = track_params.get("sellerLevel", 0)

        result["message"] = "Product detail retrieved successfully"
        return result
