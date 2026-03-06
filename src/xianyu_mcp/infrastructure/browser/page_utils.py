"""Page utilities for common operations."""

import asyncio
import random
import time
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from xianyu_mcp.config import get_settings
from xianyu_mcp.errors import OperationError, ErrorCode
from xianyu_mcp.logging import get_logger

logger = get_logger("page_utils")


async def random_delay(min_ms: int = 100, max_ms: int = 500) -> None:
    """Add a random delay to simulate human behavior."""
    delay = random.uniform(min_ms / 1000, max_ms / 1000)
    await asyncio.sleep(delay)


async def take_screenshot(
    page: Page,
    full_page: bool = False,
    save_path: Optional[Path] = None
) -> str:
    """Take a screenshot and save to file.

    Args:
        page: Playwright page object
        full_page: Whether to capture full page
        save_path: Optional custom save path. If not provided, saves to screenshot_dir.

    Returns:
        Path to the saved screenshot file.
    """
    try:
        screenshot_bytes = await page.screenshot(full_page=full_page)

        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(screenshot_bytes)
            logger.info(f"Screenshot saved to {save_path}")
            return str(save_path.absolute())
        else:
            # Save to default screenshot directory
            settings = get_settings()
            save_dir = Path(settings.screenshot_dir)
            save_dir.mkdir(parents=True, exist_ok=True)
            filename = f"screenshot_{int(time.time() * 1000)}.png"
            file_path = save_dir / filename
            file_path.write_bytes(screenshot_bytes)
            logger.info(f"Screenshot saved to {file_path}")
            return str(file_path.absolute())

    except Exception as e:
        logger.error(f"Failed to take screenshot: {e}")
        raise OperationError(
            f"Failed to take screenshot: {e}",
            code=ErrorCode.SCREENSHOT_FAILED
        )


async def scroll_page(page: Page, direction: str = "down", distance: int = 500) -> None:
    """Scroll the page in the specified direction."""
    if direction == "down":
        await page.evaluate(f"window.scrollBy(0, {distance})")
    elif direction == "up":
        await page.evaluate(f"window.scrollBy(0, -{distance})")
    await random_delay(100, 300)


async def scroll_to_bottom(page: Page, max_scrolls: int = 10) -> None:
    """Scroll to the bottom of the page with human-like behavior."""
    for _ in range(max_scrolls):
        old_height = await page.evaluate("document.body.scrollHeight")
        await scroll_page(page, "down")
        await random_delay(300, 800)
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == old_height:
            break

