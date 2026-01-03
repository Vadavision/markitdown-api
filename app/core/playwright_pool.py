"""
Playwright browser connection pool for Scraping Browser.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
import asyncio

from app.logging_config import logger
from app.config import BRIGHTDATA_SB_WS_URL


class PlaywrightPool:
    """
    Singleton pool for Playwright browser connections.
    Reuses browser connections to avoid reconnection overhead.
    """

    def __init__(self):
        self._browser = None
        self._playwright = None
        self._lock = asyncio.Lock()

    async def get_browser(self):
        """Get or create a browser connection."""
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                from playwright.async_api import async_playwright
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.connect_over_cdp(BRIGHTDATA_SB_WS_URL)
                logger.info("playwright_pool_connected", ws_url=BRIGHTDATA_SB_WS_URL[:50] + "...")
            return self._browser

    async def close(self):
        """Close browser and playwright."""
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            logger.info("playwright_pool_closed")


# Initialize Playwright pool (lazy - connects on first use)
playwright_pool = PlaywrightPool() if BRIGHTDATA_SB_WS_URL else None
