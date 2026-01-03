"""
Bright Data Web Unlocker and Scraping Browser functions.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
import os
import time
import tempfile
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from markitdown import MarkItDown

from app.logging_config import logger
from app.config import BRIGHTDATA_API_TOKEN, BRIGHTDATA_ZONE, BRIGHTDATA_API_URL, BRIGHTDATA_SB_WS_URL
from app.core.playwright_pool import playwright_pool

# Initialize MarkItDown
md = MarkItDown()


async def fetch_with_js_rendering(url: str) -> str:
    """
    Fetch URL content with JavaScript rendering using Bright Data Scraping Browser via CDP.
    Uses connection pool for better performance on subsequent requests.
    Returns markdown content after rendering the page.
    """
    if not BRIGHTDATA_SB_WS_URL:
        raise ValueError("BRIGHTDATA_SB_WS_URL environment variable not set for JS rendering")

    if not playwright_pool:
        raise ValueError("Playwright pool not initialized")

    logger.info("fetch_with_js_rendering_start", url=url)
    start_time = time.time()

    # Get browser from pool (reuses existing connection)
    browser = await playwright_pool.get_browser()

    # Create a new context and page for this request (isolated)
    context = await browser.new_context()
    page = await context.new_page()

    try:
        # Navigate and wait for load event, then wait for JS to render
        await page.goto(url, wait_until="load", timeout=30000)

        # Wait for JS frameworks to render content
        await page.wait_for_timeout(5000)

        # Get the rendered HTML
        html_content = await page.content()

        elapsed = time.time() - start_time
        logger.info("fetch_with_js_rendering_complete", url=url, chars=len(html_content), elapsed_s=round(elapsed, 1))

    finally:
        # Close context and page, but keep browser connection alive
        await context.close()

    # Convert HTML to markdown using MarkItDown
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
        f.write(html_content)
        temp_path = f.name

    try:
        result = md.convert(temp_path)
        markdown_content = result.markdown
    finally:
        os.remove(temp_path)

    logger.info("fetch_with_js_rendering_success", url=url, markdown_chars=len(markdown_content))
    return markdown_content


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    before_sleep=lambda retry_state: logger.warning(f"Retrying Bright Data request, attempt {retry_state.attempt_number}")
)
async def fetch_via_brightdata(url: str) -> str:
    """
    Fetch URL content via Bright Data Web Unlocker API.
    Note: This zone does NOT render JavaScript - only handles 403/captcha blocks.
    Returns markdown content directly.
    Uses async httpx with exponential backoff retry.
    """
    if not BRIGHTDATA_API_TOKEN:
        raise ValueError("BRIGHTDATA_API_TOKEN environment variable not set")

    headers = {
        "Authorization": f"Bearer {BRIGHTDATA_API_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "zone": BRIGHTDATA_ZONE,
        "url": url,
        "format": "raw",
        "data_format": "markdown"
    }

    logger.info(f"Fetching URL via Bright Data Web Unlocker: {url}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(BRIGHTDATA_API_URL, headers=headers, json=payload)
        response.raise_for_status()

    markdown_content = response.text
    logger.info(f"Successfully fetched URL via Bright Data: {url} ({len(markdown_content)} chars)")

    return markdown_content
