"""Shared primitives for Xianyu API clients."""

import hashlib
import json
import urllib.parse
from typing import Any, Optional

import httpx

from xianyu_mcp.infrastructure.storage.cookie_store import get_cookie_store
from xianyu_mcp.logging import get_logger

logger = get_logger("xianyu_api_client")


class XianyuApiClientBase:
    """Common request/signature helpers for Xianyu API mixins."""

    BASE_URL = "https://h5api.m.goofish.com/h5/"
    APP_KEY = "34839810"

    HEADERS = {
        "accept": "application/json",
        "accept-language": "zh-CN,zh;q=0.9",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.goofish.com",
        "priority": "u=1, i",
        "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24", "Microsoft Edge";v="125"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }

    def __init__(self, timeout: float = 20.0):
        """Initialize the API client.

        Args:
            timeout: Request timeout in seconds.
        """
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._cookie_store = get_cookie_store()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_cookies(self) -> dict[str, str]:
        """Get cookies from the cookie store.

        Returns:
            Dictionary of cookie name-value pairs.
        """
        cookies = {}
        stored_cookies = self._cookie_store.load_valid()
        for cookie in stored_cookies:
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            if name and value:
                cookies[name] = value
        return cookies

    def _build_cookie_header(self, cookies: dict[str, str]) -> str:
        """Build cookie header string from dict.

        Args:
            cookies: Dictionary of cookie name-value pairs.

        Returns:
            Cookie header string.
        """
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    def _extract_token(self, m_h5_tk: str) -> str:
        """Extract token from _m_h5_tk cookie.

        Args:
            m_h5_tk: The _m_h5_tk cookie value.

        Returns:
            The token part before the underscore.
        """
        pos = m_h5_tk.find("_")
        if pos > 0:
            return m_h5_tk[:pos]
        raise ValueError(f"Invalid _m_h5_tk format: {m_h5_tk}")

    def _calculate_sign(self, token: str, timestamp: int, payload: str) -> str:
        """Calculate request signature using MD5.

        The signature is: MD5(token + '&' + timestamp + '&' + APP_KEY + '&' + payload)

        Args:
            token: Token extracted from _m_h5_tk cookie.
            timestamp: Current timestamp in milliseconds.
            payload: The request payload (data parameter).

        Returns:
            MD5 signature string.
        """
        raw = f"{token}&{timestamp}&{self.APP_KEY}&{payload}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _build_query_string(
        self,
        api_name: str,
        sign: str,
        timestamp: int,
        extra_params: Optional[dict[str, str]] = None,
    ) -> str:
        """Build URL query string for API request.

        Args:
            api_name: API name.
            sign: Request signature.
            timestamp: Current timestamp.
            extra_params: Additional query parameters.

        Returns:
            URL-encoded query string.
        """
        params = {
            "jsv": "2.7.2",
            "appKey": self.APP_KEY,
            "t": str(timestamp),
            "sign": sign,
            "v": "1.0",
            "type": "originaljson",
            "accountSite": "xianyu",
            "dataType": "json",
            "timeout": "20000",
            "api": api_name,
            "sessionOption": "AutoLoginOnly",
            "spm_cnt": "a21ybx.search.0.0",
        }

        if extra_params:
            params.update(extra_params)

        return urllib.parse.urlencode(params)

    def _build_mobile_url(self, item_id: str) -> str:
        """Build mobile URL for item.

        Args:
            item_id: The item ID.

        Returns:
            Mobile URL string.
        """
        bfp_json = json.dumps({"id": item_id}, ensure_ascii=False)
        encoded = urllib.parse.quote(bfp_json, safe="")
        return (
            "https://pages.goofish.com/sharexy"
            "?loadingVisible=false"
            "&bft=item"
            "&bfs=idlepc.item"
            "&spm=a21ybx.item.0.0"
            f"&bfp={encoded}"
        )

    def _parse_api_response(
        self,
        response_text: str,
        context: str = "API",
    ) -> tuple[bool, dict[str, Any], str]:
        """Parse and validate API response with unified risk control check.

        Args:
            response_text: Raw API response text.
            context: Context name for logging (e.g., "search", "favorites", "detail").

        Returns:
            Tuple of (success, data, error_message).
            - success: True if response is valid and passed risk control.
            - data: The data dict from response, or empty dict on error.
            - error_message: Error message if failed, empty string on success.
        """
        if not response_text:
            logger.error(f"Empty response from {context} API")
            return False, {}, "Empty response from API"

        try:
            root = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse {context} response: {e}")
            return False, {}, f"Failed to parse response: {e}"

        # Unified risk control check
        ret = root.get("ret", [])
        if not ret or "SUCCESS" not in str(ret[0]):
            error_msg = f"API returned error (possible risk control): {ret}"
            logger.warning(f"{context} API returned non-success: {ret}")
            return False, {}, error_msg

        data = root.get("data")
        if data is None:
            return True, {}, ""  # Success but no data

        return True, data, ""

    def _extract_has_more(self, data: dict[str, Any]) -> Optional[bool]:
        """Extract has-more pagination flag from common response fields."""
        if not isinstance(data, dict):
            return None

        def _to_bool(value: Any) -> Optional[bool]:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "y"}:
                    return True
                if normalized in {"false", "0", "no", "n", ""}:
                    return False
            return None

        for key in ("has_more", "hasMore", "hasNext", "hasNextPage", "nextPage", "next_page"):
            parsed = _to_bool(data.get(key))
            if parsed is not None:
                return parsed

        for container_key in ("page", "pageInfo", "pagination", "pager", "pageData"):
            container = data.get(container_key)
            if not isinstance(container, dict):
                continue
            for key in ("has_more", "hasMore", "hasNext", "hasNextPage", "nextPage", "next_page"):
                parsed = _to_bool(container.get(key))
                if parsed is not None:
                    return parsed

        return None

    def _check_cookies_and_token(self) -> tuple[bool, dict[str, Any], str]:
        """Check cookies and token availability.

        Returns:
            Tuple of (success, error_response, token).
            - success: True if cookies and token are valid.
            - error_response: Error response dict if failed, empty dict on success.
            - token: The extracted token string.
        """
        cookies = self._get_cookies()
        if not cookies:
            return False, {
                "items": [],
                "total_count": 0,
                "page": 1,
                "has_more": False,
                "message": "No valid cookies available. Please login first.",
                "error": "NO_COOKIES",
            }, ""

        m_h5_tk = cookies.get("_m_h5_tk")
        if not m_h5_tk:
            return False, {
                "items": [],
                "total_count": 0,
                "page": 1,
                "has_more": False,
                "message": "Missing valid _m_h5_tk cookie. Please login first.",
                "error": "MISSING_TOKEN",
            }, ""

        try:
            token = self._extract_token(m_h5_tk)
        except ValueError as e:
            return False, {
                "items": [],
                "total_count": 0,
                "page": 1,
                "has_more": False,
                "message": f"Invalid token: {e}",
                "error": "INVALID_TOKEN",
            }, ""

        return True, {}, token

    def _get_cookies_dict(self) -> dict[str, str]:
        """Get cookies as dictionary.

        Returns:
            Dictionary of cookie name-value pairs.
        """
        return self._get_cookies()
