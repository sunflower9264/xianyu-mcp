"""Sale-related MCP tools for publishing and managing goods."""

import asyncio
import base64
import os
import re
import tempfile
import time
from urllib.parse import urlparse
from typing import Any, Optional, List

import httpx

from xianyu_mcp.infrastructure.api import get_api_client
from xianyu_mcp.infrastructure.browser import (
    get_browser_manager,
    random_delay,
    scroll_to_bottom,
    take_screenshot,
)
from xianyu_mcp.logging import get_logger

logger = get_logger("sale_tools")

# Publish page URL
PUBLISH_URL = "https://www.goofish.com/publish"

# Publish page selectors
PUBLISH_SELECTORS = {
    # Upload image button
    "upload_input": 'input[type="file"]',
    # Description editor (contenteditable div)
    "description_editor": 'div[contenteditable="true"]',
    # Price input (use more specific selector to distinguish from original price)
    "price_input": 'label[title="价格"] ~ * input[placeholder="0.00"], label[title="价格"] + div input[placeholder="0.00"]',
    # Shipping type radio option by display text
    "shipping_option_by_text": "label:has-text('{text}')",
    # Shipping type radio option by value
    "shipping_option_by_value": "label:has(input[type='radio'][value='{value}'])",
    # Pickup switch (near '支持自提')
    "pickup_switch": "xpath=//*[contains(normalize-space(text()), '支持自提')]/following::button[@role='switch'][1]",
    # Publish/submit button
    "submit_button": "button:has-text('发布')",
}
SUBMIT_BUTTON_FALLBACK_SELECTORS = [
    "[role='button']:has-text('发布')",
]
PUBLISH_PAGE_SETTLE_QUIET_SECONDS = 2.5
PUBLISH_PAGE_SETTLE_MAX_WAIT_SECONDS = 15.0
SHIPPING_TYPE_LABELS = {
    "0": "包邮",
    "1": "按距离计费",
    "2": "一口价",
    "3": "无需邮寄",
}


async def _read_upload_widget_state(page) -> dict[str, Any]:
    """Read upload-widget text markers used to detect first-upload reload behavior."""
    try:
        return await page.evaluate(
            """
() => {
  const input = document.querySelector('input[type="file"]');
  const wrapper = input ? input.closest('.ant-upload-wrapper') : null;
  const panel = wrapper ? (wrapper.parentElement || wrapper) : null;
  const textRaw = panel ? (panel.textContent || '') : '';
  const textCompact = textRaw.replace(/\\s+/g, '');
  return {
    text_compact: textCompact.slice(0, 200),
    has_add_primary: textCompact.includes('添加首图'),
    has_add_detail: textCompact.includes('添加细节图'),
  };
}
"""
        )
    except Exception:
        return {}


async def _wait_publish_page_settled(page, nav_events: list[str]) -> dict[str, Any]:
    """Wait for the publish page's self-reload to settle before interacting."""
    start = time.monotonic()
    previous_count = len(nav_events)
    last_change = time.monotonic()

    while (time.monotonic() - start) < PUBLISH_PAGE_SETTLE_MAX_WAIT_SECONDS:
        await asyncio.sleep(0.25)
        current_count = len(nav_events)
        if current_count != previous_count:
            previous_count = current_count
            last_change = time.monotonic()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
        if (time.monotonic() - last_change) >= PUBLISH_PAGE_SETTLE_QUIET_SECONDS:
            break

    return {
        "wait_seconds": round(time.monotonic() - start, 2),
        "main_nav_count": len(nav_events),
    }


def _is_http_image_url(value: str) -> bool:
    """Check whether a value is a valid HTTP/HTTPS URL."""
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _compact_image_ref(value: str, max_len: int = 80) -> str:
    """Compact long image inputs for error output."""
    text = value.strip()
    if len(text) <= max_len:
        return text
    return f"{text[:40]}...{text[-20:]}"


def _extract_base64_payload(value: str) -> tuple[str, str]:
    """Extract base64 payload and mime from data URL or raw base64 string."""
    data_url_match = re.match(r"^data:(image/[\w.+-]+);base64,(.+)$", value.strip(), flags=re.IGNORECASE | re.DOTALL)
    if data_url_match:
        mime = data_url_match.group(1).lower()
        payload = re.sub(r"\s+", "", data_url_match.group(2))
        return payload, mime

    # Raw base64 input
    return re.sub(r"\s+", "", value.strip()), ""


def _guess_suffix_from_mime_or_bytes(mime: str, content: bytes) -> str:
    """Guess file suffix from mime first, then by content signature."""
    mime_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    if mime.lower() in mime_map:
        return mime_map[mime.lower()]

    if content.startswith(b"\xFF\xD8\xFF"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return ".gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def _decode_base64_images(image_values: List[str]) -> tuple[list[str], list[str]]:
    """Decode base64 image strings and write to temp files.

    Returns:
        temp_files: Temp file paths ready for upload.
        failed_values: Inputs that are not valid base64 image data.
    """
    temp_files: list[str] = []
    failed_values: list[str] = []

    for value in image_values:
        try:
            payload, mime = _extract_base64_payload(value)
            image_bytes = base64.b64decode(payload, validate=True)
            if not image_bytes:
                raise ValueError("empty image bytes")

            suffix = _guess_suffix_from_mime_or_bytes(mime, image_bytes)
            with tempfile.NamedTemporaryFile(prefix="xianyu_img_", suffix=suffix, delete=False) as tmp:
                tmp.write(image_bytes)
                temp_files.append(tmp.name)
        except Exception:
            failed_values.append(value)

    return temp_files, failed_values


def _guess_suffix_from_url_or_content_type(url: str, content_type: str) -> str:
    """Guess file suffix for temporary image file."""
    content_type = (content_type or "").lower()
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    if "gif" in content_type:
        return ".gif"

    path = urlparse(url).path.lower()
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


async def _download_image_urls(image_urls: List[str]) -> tuple[list[str], list[str], list[str]]:
    """Download image URLs to temporary files for browser upload.

    Returns:
        upload_files: Local temp files that can be used by set_input_files.
        temp_files: All temp files to cleanup.
        failed_urls: URLs that failed to download.
    """
    upload_files: list[str] = []
    temp_files: list[str] = []
    failed_urls: list[str] = []

    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for image_url in image_urls:
            try:
                response = await client.get(image_url)
                if not response.is_success:
                    logger.warning(f"Failed to download image URL: {image_url}, status={response.status_code}")
                    failed_urls.append(image_url)
                    continue

                suffix = _guess_suffix_from_url_or_content_type(
                    image_url,
                    response.headers.get("content-type", ""),
                )
                with tempfile.NamedTemporaryFile(prefix="xianyu_img_", suffix=suffix, delete=False) as tmp:
                    tmp.write(response.content)
                    temp_path = tmp.name

                upload_files.append(temp_path)
                temp_files.append(temp_path)
            except Exception as e:
                logger.warning(f"Failed to download image URL: {image_url}, error={e}")
                failed_urls.append(image_url)

    return upload_files, temp_files, failed_urls


def _normalize_shipping_type(value: Any) -> str:
    """Normalize shipping type to canonical string values."""
    if value is None:
        return ""
    return str(value).strip()


def _normalize_bool(value: Any, default: bool = False) -> bool:
    """Normalize common bool-like values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    return default


async def _set_shipping_settings(page, shipping_type: str, support_pickup: bool) -> dict[str, Any]:
    """Set shipping radio and pickup switch on publish page."""
    shipping_label = SHIPPING_TYPE_LABELS.get(shipping_type)
    if not shipping_label:
        return {
            "success": False,
            "message": "shipping_type 仅支持 0/1/2/3。",
            "shipping_type": shipping_type,
        }

    result: dict[str, Any] = {
        "success": True,
        "shipping_type": shipping_type,
        "shipping_type_label": shipping_label,
        "support_pickup": support_pickup,
    }

    try:
        option_selector_by_text = PUBLISH_SELECTORS["shipping_option_by_text"].format(text=shipping_label)
        option_selector_by_value = PUBLISH_SELECTORS["shipping_option_by_value"].format(value=shipping_type)

        shipping_option = page.locator(option_selector_by_text)
        if await shipping_option.count() == 0:
            shipping_option = page.locator(option_selector_by_value)

        if await shipping_option.count() == 0:
            return {
                **result,
                "success": False,
                "message": f"未找到发货类型选项：{shipping_label}",
                "failed_reason": "shipping_option_not_found",
            }

        await shipping_option.first.scroll_into_view_if_needed()
        await random_delay(150, 300)
        await shipping_option.first.click(force=True)
        await random_delay(250, 450)

        shipping_checked = await page.evaluate(
            """
(labelText) => {
  const labels = Array.from(document.querySelectorAll('label'));
  const target = labels.find((label) => (label.textContent || '').replace(/\\s+/g, '').includes(labelText));
  if (!target) return false;
  const input = target.querySelector('input[type="radio"]');
  return Boolean(input && input.checked);
}
""",
            shipping_label,
        )
        result["shipping_type_set"] = bool(shipping_checked)
        if not shipping_checked:
            return {
                **result,
                "success": False,
                "message": f"发货类型设置失败：{shipping_label}",
                "failed_reason": "shipping_option_unchecked",
            }

        pickup_switch = page.locator(PUBLISH_SELECTORS["pickup_switch"])
        if await pickup_switch.count() == 0:
            return {
                **result,
                "success": False,
                "message": "未找到“支持自提”开关。",
                "failed_reason": "pickup_switch_not_found",
            }

        current_checked = (await pickup_switch.first.get_attribute("aria-checked")) == "true"
        if current_checked != support_pickup:
            await pickup_switch.first.scroll_into_view_if_needed()
            await random_delay(120, 240)
            await pickup_switch.first.click(force=True)
            await random_delay(250, 450)

        pickup_checked = (await pickup_switch.first.get_attribute("aria-checked")) == "true"
        result["pickup_checked"] = pickup_checked
        if pickup_checked != support_pickup:
            return {
                **result,
                "success": False,
                "message": "“支持自提”开关状态设置失败。",
                "failed_reason": "pickup_switch_state_mismatch",
            }

        return result
    except Exception as e:
        return {
            **result,
            "success": False,
            "message": f"发货设置失败: {e}",
            "failed_reason": "shipping_setting_exception",
            "error": str(e),
        }


async def publish_goods(
    description: str,
    price: str,
    images: List[str],
    shipping_type: str,
    support_pickup: Optional[bool] = None,
) -> dict[str, Any]:
    """Publish goods on Xianyu using browser automation.

    This tool navigates to the publish page and fills in the form fields.

    Args:
        description: Product description.
        price: Product price.
        images: List of image URLs (http/https) or base64 image strings.
        shipping_type: Shipping type.
        support_pickup: Pickup toggle.

    Returns:
        Dictionary with publish result.
    """
    logger.info("Tool called: publish_goods")

    if not description or not description.strip():
        return {"success": False, "message": "Description is required"}
    if not price:
        return {"success": False, "message": "Price is required"}
    if not isinstance(images, list):
        return {"success": False, "message": "Images must be an array"}
    if not images or not any(isinstance(img, str) and img.strip() for img in images):
        return {"success": False, "message": "Images is required"}

    shipping_type = _normalize_shipping_type(shipping_type)
    support_pickup = _normalize_bool(support_pickup, default=False)
    if shipping_type not in SHIPPING_TYPE_LABELS:
        return {"success": False, "message": "shipping_type must be one of: 0, 1, 2, 3"}

    browser_manager = get_browser_manager()
    temp_image_files: list[str] = []

    try:
        # 1. Prepare images from URLs/base64 only
        upload_images: list[str] = []
        failed_image_urls: list[str] = []
        failed_image_base64_count = 0
        if images:
            normalized_images = [img.strip() for img in images if isinstance(img, str) and img.strip()]
            url_images = [img for img in normalized_images if _is_http_image_url(img)]
            non_url_images = [img for img in normalized_images if not _is_http_image_url(img)]

            base64_image_files: list[str] = []
            invalid_base64_images: list[str] = []
            if non_url_images:
                base64_image_files, invalid_base64_images = _decode_base64_images(non_url_images)
                failed_image_base64_count = len(invalid_base64_images)

            if invalid_base64_images:
                return {
                    "success": False,
                    "price": price,
                    "message": "images 仅支持 http/https URL 或 base64 图片字符串，不支持本地路径。",
                    "invalid_images": [_compact_image_ref(v) for v in invalid_base64_images],
                }

            url_upload_files: list[str] = []
            url_temp_files: list[str] = []
            if url_images:
                url_upload_files, url_temp_files, failed_image_urls = await _download_image_urls(url_images)

            # Base64 temp files are upload-ready files too
            temp_image_files.extend(base64_image_files)
            temp_image_files.extend(url_temp_files)
            upload_images = [*base64_image_files, *url_upload_files]

            if not upload_images:
                return {
                    "success": False,
                    "price": price,
                    "message": "未能获取任何可用图片，请检查图片 URL/base64。",
                    "failed_images": failed_image_urls,
                    "failed_base64_count": failed_image_base64_count,
                }

        async with browser_manager.new_tab() as page:
            nav_events: list[str] = []

            def _on_frame_navigated(frame) -> None:
                if frame == page.main_frame:
                    nav_events.append(frame.url)

            page.on("framenavigated", _on_frame_navigated)

            # 2. Navigate to the publish page
            logger.info("Navigating to publish page...")
            await page.goto(PUBLISH_URL, timeout=30000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            page_settle_info = await _wait_publish_page_settled(page, nav_events)
            await random_delay(1000, 1800)

            # 3. Upload images (URL download result)
            upload_widget_state: dict[str, Any] = {}
            upload_navigation_delta = 0
            if upload_images:
                logger.info(f"Uploading {len(upload_images)} images...")
                try:
                    file_input = page.locator(PUBLISH_SELECTORS["upload_input"])
                    if await file_input.count() == 0:
                        logger.warning("File input element not found")
                        form_screenshot = await take_screenshot(page, full_page=True)
                        return {
                            "success": False,
                            "price": price,
                            "images_count": len(upload_images),
                            "failed_images": failed_image_urls,
                            "failed_base64_count": failed_image_base64_count,
                            "message": "未找到图片上传控件。",
                            "failed_reason": "upload_input_not_found",
                            "form_screenshot": form_screenshot,
                            "nav_events": nav_events,
                            "page_settle_info": page_settle_info,
                        }

                    nav_before_upload = len(nav_events)
                    await file_input.first.set_input_files(upload_images)
                    await random_delay(2400, 3600)
                    upload_navigation_delta = len(nav_events) - nav_before_upload
                    upload_widget_state = await _read_upload_widget_state(page)
                    has_add_primary = bool(upload_widget_state.get("has_add_primary"))
                    has_add_detail = bool(upload_widget_state.get("has_add_detail"))

                    # After waiting for page settle, upload should not trigger another reload.
                    if upload_navigation_delta > 0:
                        logger.warning("Upload still triggered page reload after settle phase")
                        form_screenshot = await take_screenshot(page, full_page=True)
                        return {
                            "success": False,
                            "price": price,
                            "images_count": len(upload_images),
                            "failed_images": failed_image_urls,
                            "failed_base64_count": failed_image_base64_count,
                            "message": "上传图片时页面再次刷新，上传未生效。",
                            "failed_reason": "upload_triggered_navigation",
                            "upload_widget_state": upload_widget_state,
                            "upload_navigation_delta": upload_navigation_delta,
                            "form_screenshot": form_screenshot,
                            "nav_events": nav_events,
                            "page_settle_info": page_settle_info,
                        }

                    if not has_add_detail and has_add_primary:
                        logger.warning("Image upload did not enter detail-upload state")
                        form_screenshot = await take_screenshot(page, full_page=True)
                        return {
                            "success": False,
                            "price": price,
                            "images_count": len(upload_images),
                            "failed_images": failed_image_urls,
                            "failed_base64_count": failed_image_base64_count,
                            "message": "图片上传后未出现预期状态，请检查图片内容或账号发布权限。",
                            "failed_reason": "upload_state_invalid",
                            "upload_widget_state": upload_widget_state,
                            "upload_navigation_delta": upload_navigation_delta,
                            "form_screenshot": form_screenshot,
                            "nav_events": nav_events,
                            "page_settle_info": page_settle_info,
                        }
                    logger.info(f"Uploaded {len(upload_images)} images")
                except Exception as e:
                    logger.warning(f"Failed to upload images: {e}")
                    form_screenshot = await take_screenshot(page, full_page=True)
                    return {
                        "success": False,
                        "price": price,
                        "images_count": len(upload_images),
                        "failed_images": failed_image_urls,
                        "failed_base64_count": failed_image_base64_count,
                        "message": f"图片上传失败: {e}",
                        "failed_reason": "upload_exception",
                        "error": str(e),
                        "upload_widget_state": upload_widget_state,
                        "upload_navigation_delta": upload_navigation_delta,
                        "form_screenshot": form_screenshot,
                        "nav_events": nav_events,
                        "page_settle_info": page_settle_info,
                    }

            # 4. Fill in the description
            logger.info("Filling in description...")
            desc_editor = page.locator(PUBLISH_SELECTORS["description_editor"])
            if await desc_editor.count() > 0:
                await desc_editor.first.click()
                await random_delay(200, 400)
                # Clear existing content and type new description
                await desc_editor.first.fill("")  # Clear contenteditable
                await desc_editor.first.type(description, delay=30)
                await random_delay(300, 600)
            else:
                logger.warning("Description editor not found")

            # 5. Fill in the price
            logger.info("Filling in price...")
            # Try specific selector first, fallback to generic placeholder selector
            price_input = page.locator(PUBLISH_SELECTORS["price_input"])
            if await price_input.count() == 0:
                # Fallback: find price input by its label context
                price_input = page.locator('label[title="价格"]').locator('..').locator('input[placeholder="0.00"]')
            if await price_input.count() == 0:
                # Last fallback: use all placeholder inputs and take first (price)
                price_input = page.locator('input[placeholder="0.00"]').first

            if await price_input.count() > 0:
                await price_input.first.click()
                await price_input.first.fill(price)
                await random_delay(300, 600)
            else:
                logger.warning("Price input not found")

            # 6. Fill in shipping settings
            logger.info(f"Setting shipping: type={shipping_type}, pickup={support_pickup}")
            shipping_result = await _set_shipping_settings(
                page=page,
                shipping_type=shipping_type,
                support_pickup=support_pickup,
            )
            if not shipping_result.get("success"):
                form_screenshot = await take_screenshot(page, full_page=True)
                return {
                    "success": False,
                    "price": price,
                    "images_count": len(upload_images),
                    "failed_images": failed_image_urls,
                    "failed_base64_count": failed_image_base64_count,
                    "message": shipping_result.get("message", "发货设置失败"),
                    "failed_reason": "shipping_setting_failed",
                    "shipping": shipping_result,
                    "upload_widget_state": upload_widget_state,
                    "upload_navigation_delta": upload_navigation_delta,
                    "form_screenshot": form_screenshot,
                    "nav_events": nav_events,
                    "page_settle_info": page_settle_info,
                }

            # 7. Take a screenshot of the filled form for verification
            screenshot_path = await take_screenshot(page, full_page=True)
            logger.info(f"Form screenshot saved: {screenshot_path}")

            # 8. Click the publish button
            logger.info("Clicking publish button...")
            await scroll_to_bottom(page, max_scrolls=12)
            await random_delay(300, 600)

            submit_btn = page.locator(PUBLISH_SELECTORS["submit_button"])
            submit_selector_used = PUBLISH_SELECTORS["submit_button"]
            submit_btn_count = await submit_btn.count()
            if submit_btn_count == 0:
                for selector in SUBMIT_BUTTON_FALLBACK_SELECTORS:
                    candidate = page.locator(selector)
                    candidate_count = await candidate.count()
                    if candidate_count > 0:
                        submit_btn = candidate
                        submit_btn_count = candidate_count
                        submit_selector_used = selector
                        break

            if submit_btn_count > 0:
                await submit_btn.first.scroll_into_view_if_needed()
                await random_delay(200, 400)
                await submit_btn.first.click()
                await random_delay(3000, 5000)

                # Take a screenshot of the result
                result_screenshot = await take_screenshot(page)
                logger.info(f"Result screenshot saved: {result_screenshot}")

                return {
                    "success": True,
                    "price": price,
                    "images_count": len(upload_images),
                    "failed_images": failed_image_urls,
                    "failed_base64_count": failed_image_base64_count,
                    "shipping": shipping_result,
                    "upload_widget_state": upload_widget_state,
                    "upload_navigation_delta": upload_navigation_delta,
                    "submit_button_selector": submit_selector_used,
                    "message": "商品发布操作已完成，请查看截图确认发布结果。",
                    "form_screenshot": screenshot_path,
                    "result_screenshot": result_screenshot,
                    "nav_events": nav_events,
                    "page_settle_info": page_settle_info,
                }
            else:
                logger.warning("Submit button not found")
                submit_button_text_candidates = await page.eval_on_selector_all(
                    "button, [role='button']",
                    "els => Array.from(new Set(els.map(e => (e.textContent || '').trim()).filter(Boolean))).slice(0, 30)",
                )
                return {
                    "success": False,
                    "price": price,
                    "message": "未找到发布按钮，请查看截图确认页面状态。",
                    "failed_reason": "submit_button_not_found",
                    "shipping": shipping_result,
                    "submit_button_text_candidates": submit_button_text_candidates,
                    "submit_button_selector": submit_selector_used,
                    "upload_widget_state": upload_widget_state,
                    "upload_navigation_delta": upload_navigation_delta,
                    "form_screenshot": screenshot_path,
                    "nav_events": nav_events,
                    "page_settle_info": page_settle_info,
                }

    except Exception as e:
        logger.error(f"Error in publish_goods: {e}")
        return {
            "success": False,
            "price": price,
            "message": f"发布过程中出现错误: {e}",
            "error": str(e),
        }
    finally:
        # Cleanup temporary files downloaded from image URLs
        for tmp_file in temp_image_files:
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup temp image file {tmp_file}: {cleanup_error}")


async def get_my_goods(
    status: Optional[str] = None,
    page_num: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Get the logged-in user's published goods list.

    Args:
        status: Filter by status: 'selling', 'sold', 'taken_down'.
        page_num: Page number (default: 1).
        page_size: Number of items per page (default: 20).

    Returns:
        Dictionary with goods list and metadata.
    """
    logger.info(f"Tool called: get_my_goods (status: {status}, page: {page_num})")

    client = get_api_client()
    return await client.get_my_goods_list(
        page_number=page_num,
        page_size=page_size,
        status=status,
    )


async def take_down_goods(item_id: str) -> dict[str, Any]:
    """Take down a published item from Xianyu.

    Args:
        item_id: The item ID to take down.

    Returns:
        Dictionary with operation result.
    """
    logger.info(f"Tool called: take_down_goods (item_id: {item_id})")

    if not item_id:
        return {"success": False, "item_id": None, "message": "Item ID is required"}

    client = get_api_client()
    return await client.take_down_item(item_id)


async def delete_goods(item_id: str) -> dict[str, Any]:
    """Permanently delete a published item from Xianyu.

    Args:
        item_id: The item ID to delete.

    Returns:
        Dictionary with operation result.
    """
    logger.info(f"Tool called: delete_goods (item_id: {item_id})")

    if not item_id:
        return {"success": False, "item_id": None, "message": "Item ID is required"}

    client = get_api_client()
    return await client.delete_item(item_id)



# Tool definitions for MCP registration
SALE_TOOLS = [
    {
        "name": "get_my_goods",
        "description": "获取当前用户发布的商品列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "商品状态筛选：selling(在售)、sold(已售)、taken_down(已下架)",
                },
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
        "handler": get_my_goods,
    },
    {
        "name": "publish_goods",
        "description": "在闲鱼发布新的在售商品，需提供图片、商品描述、价格和发货设置。主要返回字段：success、message、failed_reason（失败时）、form_screenshot、result_screenshot、shipping、images_count 等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "商品描述（发布页唯一文本字段）",
                },
                "price": {
                    "type": "string",
                    "description": "商品价格（人民币，例如\"99.00\"）",
                },
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "图片列表：支持 http/https URL 或 base64 图片字符串（不支持本地路径，建议最多 6 张）。",
                },
                "shipping_type": {
                    "type": "string",
                    "enum": ["0", "1", "2", "3"],
                    "description": "发货类型（Inspector 推荐）：0=包邮，1=按距离计费，2=一口价，3=无需邮寄",
                },
                "support_pickup": {
                    "type": "boolean",
                    "description": "是否支持自提（true=开启，false=关闭）",
                    "default": False,
                },
            },
            "required": ["images", "description", "price", "shipping_type"],
        },
        "handler": publish_goods,
    },
    {
        "name": "take_down_goods",
        "description": "下架已发布的闲鱼商品（从在售列表移除，但保留在账号中）。主要返回字段：success、item_id、message（失败时可能包含 error）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "要下架的商品 ID",
                },
            },
            "required": ["item_id"],
        },
        "handler": take_down_goods,
    },
    {
        "name": "delete_goods",
        "description": "在闲鱼中永久删除已发布商品。主要返回字段：success、item_id、message（失败时可能包含 error）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "要删除的商品 ID",
                },
            },
            "required": ["item_id"],
        },
        "handler": delete_goods,
    },
]
