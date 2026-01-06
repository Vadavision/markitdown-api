"""
CDP Worker Queue - Queue-based processing for BrightData Scraping Browser.

Instead of semaphores and timeouts, uses a proper worker pool pattern:
- URLs are submitted to an asyncio queue
- Fixed number of workers consume from the queue
- Each worker gets a fresh browser connection per request
- No timeouts - workers just wait for their turn

References:
- https://github.com/apify/browser-pool
- https://aosabook.org/en/500L/a-web-crawler-with-asyncio-coroutines.html
"""
import asyncio
import os
import time
import tempfile
from typing import Optional, Dict, Any
from dataclasses import dataclass

from playwright.async_api import async_playwright, Browser, Playwright

from app.logging_config import logger
from app.config import BRIGHTDATA_SB_WS_URL

# Number of CDP workers (each gets its own browser connection)
CDP_WORKER_COUNT = 3

# Retry configuration for transient errors (502, connection failures)
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # Base delay in seconds (exponential backoff: 2, 4, 8)
RETRYABLE_ERRORS = ["502", "503", "504", "no_peer", "connection", "timeout", "ECONNREFUSED"]

# User agents
GOOGLEBOT_USER_AGENT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


@dataclass
class CDPTask:
    """A task to be processed by a CDP worker."""
    url: str
    use_googlebot: bool = False
    future: asyncio.Future = None  # Will hold the result


class CDPWorkerPool:
    """
    Pool of CDP workers that process URLs from a queue.

    Each worker:
    1. Waits for a task from the queue
    2. Creates a fresh browser connection
    3. Navigates and extracts content
    4. Disconnects the browser
    5. Returns result via the task's future
    """

    def __init__(self, worker_count: int = CDP_WORKER_COUNT):
        self.worker_count = worker_count
        self.queue: asyncio.Queue[CDPTask] = asyncio.Queue()
        self.workers: list[asyncio.Task] = []
        self._playwright: Optional[Playwright] = None
        self._started = False
        self._shutdown = False
        self._md = None  # Lazy init MarkItDown

    async def start(self):
        """Start the worker pool."""
        if self._started:
            return

        # Initialize playwright once (shared across workers)
        self._playwright = await async_playwright().start()

        # Start worker tasks
        for i in range(self.worker_count):
            worker = asyncio.create_task(self._worker_loop(i))
            self.workers.append(worker)

        self._started = True
        logger.info("cdp_worker_pool_started", workers=self.worker_count)

    async def stop(self):
        """Stop the worker pool gracefully."""
        self._shutdown = True

        # Cancel all workers
        for worker in self.workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self.workers, return_exceptions=True)

        # Stop playwright
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        self._started = False
        logger.info("cdp_worker_pool_stopped")

    async def submit(self, url: str, use_googlebot: bool = False) -> str:
        """
        Submit a URL for processing and wait for the result.

        This is the main API - just submit and await, no timeouts needed.
        The queue ensures fair ordering and the workers process sequentially.
        """
        if not self._started:
            await self.start()

        # Create task with a future to receive the result
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        task = CDPTask(url=url, use_googlebot=use_googlebot, future=future)

        # Add to queue
        await self.queue.put(task)
        queue_size = self.queue.qsize()
        logger.info("cdp_task_queued", url=url, queue_size=queue_size)

        # Wait for worker to complete the task
        result = await future
        return result

    async def _worker_loop(self, worker_id: int):
        """Main loop for a CDP worker."""
        logger.info("cdp_worker_started", worker_id=worker_id)

        while not self._shutdown:
            try:
                # Wait for a task (no timeout - just wait)
                task = await self.queue.get()

                logger.info("cdp_worker_processing",
                           worker_id=worker_id,
                           url=task.url,
                           queue_remaining=self.queue.qsize())

                try:
                    # Process the task
                    result = await self._process_task(task, worker_id)
                    task.future.set_result(result)
                except Exception as e:
                    task.future.set_exception(e)
                finally:
                    self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("cdp_worker_error", worker_id=worker_id, error=str(e))

        logger.info("cdp_worker_stopped", worker_id=worker_id)

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is transient and should be retried."""
        error_str = str(error).lower()
        return any(err.lower() in error_str for err in RETRYABLE_ERRORS)

    async def _process_task(self, task: CDPTask, worker_id: int) -> str:
        """Process a single CDP task - fetch URL and return markdown with retry."""
        start_time = time.time()
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            browser: Optional[Browser] = None

            try:
                # Create fresh browser connection for this request
                browser = await self._playwright.chromium.connect_over_cdp(BRIGHTDATA_SB_WS_URL)
                logger.info("cdp_worker_connected",
                           worker_id=worker_id,
                           url=task.url,
                           attempt=attempt + 1)

                # Create context with user agent
                user_agent = GOOGLEBOT_USER_AGENT if task.use_googlebot else CHROME_USER_AGENT
                context = await browser.new_context(user_agent=user_agent)
                page = await context.new_page()

                try:
                    # Navigate and wait for content
                    await page.goto(task.url, wait_until="load", timeout=45000)
                    await page.wait_for_timeout(5000)  # Wait for JS rendering

                    # Get HTML content
                    html_content = await page.content()

                    elapsed = time.time() - start_time
                    logger.info("cdp_worker_fetched",
                               worker_id=worker_id,
                               url=task.url,
                               chars=len(html_content),
                               elapsed_s=round(elapsed, 1))

                finally:
                    await context.close()

                # Convert HTML to markdown
                markdown = await self._html_to_markdown(html_content)

                logger.info("cdp_worker_complete",
                           worker_id=worker_id,
                           url=task.url,
                           markdown_chars=len(markdown),
                           total_elapsed_s=round(time.time() - start_time, 1),
                           attempts=attempt + 1)

                return markdown

            except Exception as e:
                last_error = e

                # Always disconnect browser on error
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                    browser = None

                # Check if error is retryable
                if self._is_retryable_error(e) and attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)  # Exponential backoff
                    logger.warning("cdp_worker_retry",
                                  worker_id=worker_id,
                                  url=task.url,
                                  attempt=attempt + 1,
                                  max_retries=MAX_RETRIES,
                                  delay_s=delay,
                                  error=str(e))
                    await asyncio.sleep(delay)
                    continue
                else:
                    # Non-retryable error or max retries reached
                    logger.error("cdp_worker_failed",
                                worker_id=worker_id,
                                url=task.url,
                                attempts=attempt + 1,
                                error=str(e))
                    raise

            finally:
                # Ensure browser is closed
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                    logger.info("cdp_worker_disconnected", worker_id=worker_id)

        # Should not reach here, but just in case
        raise last_error or Exception("Max retries reached")

    async def _html_to_markdown(self, html_content: str) -> str:
        """Convert HTML to markdown using MarkItDown."""
        # Lazy init MarkItDown
        if self._md is None:
            from markitdown import MarkItDown
            self._md = MarkItDown()

        # Write to temp file and convert
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_content)
            temp_path = f.name

        try:
            result = self._md.convert(temp_path)
            return result.markdown
        finally:
            os.remove(temp_path)


# Global worker pool instance
cdp_pool: Optional[CDPWorkerPool] = None
_pool_lock: Optional[asyncio.Lock] = None


def _get_pool_lock() -> asyncio.Lock:
    """Get or create the pool lock (must be created in event loop context)."""
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


async def get_cdp_pool() -> CDPWorkerPool:
    """Get or create the global CDP worker pool."""
    global cdp_pool
    lock = _get_pool_lock()
    async with lock:
        if cdp_pool is None:
            cdp_pool = CDPWorkerPool(worker_count=CDP_WORKER_COUNT)
            await cdp_pool.start()
        return cdp_pool


async def fetch_with_cdp(url: str, use_googlebot: bool = False) -> str:
    """
    Fetch URL using CDP worker pool.

    This is the simple API - just call and await.
    No semaphores, no timeouts, just queue-based processing.
    """
    if not BRIGHTDATA_SB_WS_URL:
        raise ValueError("BRIGHTDATA_SB_WS_URL not configured")

    pool = await get_cdp_pool()
    return await pool.submit(url, use_googlebot=use_googlebot)


async def shutdown_cdp_pool():
    """Shutdown the CDP pool gracefully."""
    global cdp_pool
    if cdp_pool:
        await cdp_pool.stop()
        cdp_pool = None
