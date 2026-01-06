"""
Bright Data Web Unlocker functions.
CDP/Scraping Browser is handled by app.core.cdp_queue.
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from markitdown import MarkItDown

from app.logging_config import logger
from app.config import BRIGHTDATA_API_TOKEN, BRIGHTDATA_ZONE, BRIGHTDATA_API_URL

# Initialize MarkItDown (shared instance)
md = MarkItDown()


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=5),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    before_sleep=lambda retry_state: logger.warning(f"Retrying Bright Data request, attempt {retry_state.attempt_number}")
)
async def fetch_via_brightdata(url: str) -> str:
    """
    Fetch URL content via Bright Data Web Unlocker API.
    Note: This zone does NOT render JavaScript - only handles 403/captcha blocks.
    Returns markdown content directly.
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(BRIGHTDATA_API_URL, headers=headers, json=payload)
        response.raise_for_status()

    markdown_content = response.text
    logger.info(f"Successfully fetched URL via Bright Data: {url} ({len(markdown_content)} chars)")

    return markdown_content
