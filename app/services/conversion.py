"""
URL and file conversion services.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
import os
import json
import asyncio
from functools import partial
from markitdown import MarkItDown

from app.logging_config import logger
from app.config import BRIGHTDATA_API_TOKEN, JOB_EXPIRY
from app.core.storage import redis_client
from app.scraping.utils import is_blocked_error
from app.scraping.brightdata import fetch_via_brightdata

# Initialize MarkItDown
md = MarkItDown()

# Timeout for URL conversion (seconds)
URL_CONVERSION_TIMEOUT = 30


async def run_sync_in_executor(func, *args, **kwargs):
    """
    Run a synchronous function in a thread pool executor to avoid blocking the event loop.
    Used for MarkItDown operations which are synchronous.
    """
    loop = asyncio.get_event_loop()
    if kwargs:
        func = partial(func, **kwargs)
    return await loop.run_in_executor(None, func, *args)


async def process_url(url: str, job_id: str, query: str = None):
    """Process URL conversion as a background task."""
    try:
        logger.info(f"Starting URL conversion for job {job_id}: {url}" + (f" (query: {query})" if query else ""))

        # Update status to processing
        processing_status = {
            "status": "processing",
            "url": url,
            "filename": os.path.basename(url) or "url_content"
        }
        redis_client.set(f"job:{job_id}", json.dumps(processing_status), ex=JOB_EXPIRY)

        markdown_content = None
        used_brightdata = False

        # Try MarkItDown first (run in executor to avoid blocking event loop)
        try:
            # Add timeout to prevent hanging on slow sites
            result = await asyncio.wait_for(
                run_sync_in_executor(md.convert_url, url),
                timeout=URL_CONVERSION_TIMEOUT
            )
            markdown_content = result.markdown
            logger.info(f"URL conversion completed via MarkItDown for job {job_id}")

            # Note: Smart JS detection for SPA pages is now handled by deep_search.py
            # using semantic search (Jina reranker) instead of keyword matching.
            # This endpoint provides basic URL conversion only.

        except asyncio.TimeoutError:
            logger.warning(f"URL conversion timed out for {url} after {URL_CONVERSION_TIMEOUT}s")
            raise Exception(f"URL conversion timed out after {URL_CONVERSION_TIMEOUT}s")
        except Exception as e:
            # Check if this is a blocking error (403, captcha, etc.)
            # Use Web Unlocker for blocked requests, Scraping Browser for SPA fallback
            if is_blocked_error(e) and BRIGHTDATA_API_TOKEN:
                logger.warning(f"Direct fetch blocked for {url}, trying Web Unlocker fallback: {str(e)}")
                try:
                    markdown_content = await fetch_via_brightdata(url)
                    used_brightdata = True
                    logger.info(f"URL conversion completed via Web Unlocker for job {job_id}")
                except Exception as bd_error:
                    # Bright Data also failed, raise the original error
                    logger.error(f"Bright Data fallback also failed for {url}: {str(bd_error)}")
                    raise e
            else:
                # Not a blocking error or no Bright Data token, re-raise
                raise e

        # Store job result in Redis
        job_result = {
            "status": "completed",
            "markdown": markdown_content,
            "filename": os.path.basename(url) or "url_content",
            "source": "brightdata" if used_brightdata else "direct"
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)

    except Exception as e:
        # Handle any errors
        error_msg = f"Conversion error: {str(e)}"
        job_result = {
            "status": "failed",
            "error": error_msg,
            "url": url
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)
        logger.error(f"URL conversion failed for job {job_id}: {error_msg}")
