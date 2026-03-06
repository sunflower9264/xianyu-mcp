"""Cookie persistence for browser sessions.

Saves and loads browser cookies to/from a JSON file,
enabling session reuse across operations without re-login.
"""

import json
import time
from pathlib import Path
from typing import Optional

from xianyu_mcp.config import get_settings
from xianyu_mcp.logging import get_logger

logger = get_logger("cookie_store")

COOKIE_FILENAME = "cookies.json"


class CookieStore:
    """Manages cookie persistence to/from a JSON file."""

    def __init__(self, store_dir: Optional[Path] = None):
        settings = get_settings()
        self.store_dir = store_dir or Path(settings.user_data_dir)
        self.cookie_file = self.store_dir / COOKIE_FILENAME

    def save(self, cookies: list[dict]) -> bool:
        """Save cookies to file."""
        try:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            self.cookie_file.write_text(
                json.dumps(cookies, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"Saved {len(cookies)} cookies to {self.cookie_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}")
            return False

    def load(self) -> list[dict]:
        """Load cookies from file. Returns empty list if file doesn't exist."""
        try:
            if not self.cookie_file.exists():
                logger.debug("No cookie file found")
                return []
            cookies = json.loads(self.cookie_file.read_text(encoding="utf-8"))
            logger.info(f"Loaded {len(cookies)} cookies from {self.cookie_file}")
            return cookies
        except Exception as e:
            logger.error(f"Failed to load cookies: {e}")
            return []

    @staticmethod
    def _is_cookie_expired(cookie: dict, now_ts: Optional[float] = None) -> bool:
        """Check whether one cookie is expired."""
        expires = cookie.get("expires")
        if expires is None:
            return False

        try:
            expires_value = float(expires)
        except (TypeError, ValueError):
            return False

        # Session cookies are usually represented as -1 or 0.
        if expires_value <= 0:
            return False

        now = now_ts if now_ts is not None else time.time()
        return expires_value <= now

    def load_valid(self, now_ts: Optional[float] = None) -> list[dict]:
        """Load cookies and filter out expired ones."""
        cookies = self.load()
        if not cookies:
            return []

        now = now_ts if now_ts is not None else time.time()
        valid = [c for c in cookies if not self._is_cookie_expired(c, now)]
        filtered = len(cookies) - len(valid)
        if filtered > 0:
            logger.info(f"Filtered out {filtered} expired cookies from cookie store")
        return valid

    def exists(self) -> bool:
        """Check if cookie file exists and is non-empty."""
        return self.cookie_file.exists() and self.cookie_file.stat().st_size > 2

    def clear(self) -> bool:
        """Delete the cookie file."""
        try:
            if self.cookie_file.exists():
                self.cookie_file.unlink()
                logger.info("Cookie file deleted")
            return True
        except Exception as e:
            logger.error(f"Failed to delete cookie file: {e}")
            return False


_cookie_store: Optional[CookieStore] = None


def get_cookie_store() -> CookieStore:
    """Get the singleton cookie store instance."""
    global _cookie_store
    if _cookie_store is None:
        _cookie_store = CookieStore()
    return _cookie_store
