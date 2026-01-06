"""
Streaming URL conversion service.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
import os
import json
import asyncio
import httpx
from typing import Optional, AsyncGenerator

from app.logging_config import logger
from app.config import BRIGHTDATA_API_TOKEN, BRIGHTDATA_SB_WS_URL

# Timeout for URL conversion (seconds)
URL_CONVERSION_TIMEOUT = 30
from app.core.cache import content_cache
from app.scraping.utils import is_blocked_error, is_social_media_url
from app.scraping.brightdata import fetch_via_brightdata, md
from app.core.cdp_queue import fetch_with_cdp  # Queue-based CDP processing
from app.processing.chunking import split_markdown_into_paragraphs, create_smart_batches
from app.services.conversion import run_sync_in_executor


async def stream_url_conversion(url: str, query: Optional[str] = None) -> AsyncGenerator[str, None]:
    """
    Convert URL to markdown and stream back as paragraphs.
    - Social media URLs go directly to CDP (BrightData Scraping Browser)
    - Other URLs use MarkItDown with fallback to Web Unlocker/CDP
    - Relevance checking is handled by deep_search.py, not here
    """
    try:
        logger.info("stream_url_conversion_start", url=url, query=query)

        markdown = None
        used_brightdata = False
        from_cache = False

        # Check cache first
        if content_cache:
            cached = content_cache.get(url, query)
            if cached:
                markdown = cached
                from_cache = True
                logger.info("stream_url_conversion_cache_hit", url=url)

        if not markdown:
            # For social media URLs, skip MarkItDown and go straight to CDP
            if is_social_media_url(url) and BRIGHTDATA_SB_WS_URL:
                logger.info("stream_url_conversion_cdp_direct", url=url)
                try:
                    markdown = await fetch_with_cdp(url)
                    used_brightdata = True
                    logger.info("stream_url_conversion_cdp_direct_success", url=url, content_len=len(markdown) if markdown else 0)
                except Exception as cdp_error:
                    logger.error("stream_url_conversion_cdp_direct_failed", url=url, error=str(cdp_error))
                    raise cdp_error

            # Try MarkItDown for non-social media URLs
            else:
                try:
                    # Add timeout to prevent hanging on slow sites
                    result = await asyncio.wait_for(
                        run_sync_in_executor(md.convert_url, url),
                        timeout=URL_CONVERSION_TIMEOUT
                    )
                    markdown = result.markdown
                    logger.info("stream_url_conversion_markitdown", url=url)

                except asyncio.TimeoutError:
                    logger.warning("stream_url_conversion_timeout", url=url, timeout=URL_CONVERSION_TIMEOUT)
                    # Try CDP for timeouts
                    if BRIGHTDATA_SB_WS_URL:
                        logger.info("stream_url_conversion_cdp_fallback_timeout", url=url)
                        try:
                            markdown = await fetch_with_cdp(url)
                            used_brightdata = True
                            logger.info("stream_url_conversion_cdp_success", url=url)
                        except Exception as cdp_error:
                            logger.error("stream_url_conversion_cdp_failed", url=url, error=str(cdp_error))
                            raise Exception(f"URL conversion timed out after {URL_CONVERSION_TIMEOUT}s")
                    else:
                        raise Exception(f"URL conversion timed out after {URL_CONVERSION_TIMEOUT}s")

                except Exception as e:
                    # Check if this is a blocking error (403, captcha, etc.)
                    if is_blocked_error(e) and BRIGHTDATA_API_TOKEN:
                        logger.warning("stream_url_conversion_blocked", url=url, error=str(e))
                        try:
                            markdown = await fetch_via_brightdata(url)
                            used_brightdata = True
                            logger.info("stream_url_conversion_web_unlocker", url=url)
                        except Exception as bd_error:
                            logger.error("stream_url_conversion_brightdata_failed", url=url, error=str(bd_error))
                            # Web Unlocker failed - try CDP as last resort
                            if BRIGHTDATA_SB_WS_URL:
                                logger.info("stream_url_conversion_cdp_fallback", url=url)
                                try:
                                    markdown = await fetch_with_cdp(url)
                                    used_brightdata = True
                                    logger.info("stream_url_conversion_cdp_success", url=url)
                                except Exception as cdp_error:
                                    logger.error("stream_url_conversion_cdp_failed", url=url, error=str(cdp_error))
                                    raise e
                            else:
                                raise e
                    elif BRIGHTDATA_SB_WS_URL:
                        # Not a typical blocking error but maybe an auth wall - try CDP
                        logger.info("stream_url_conversion_cdp_fallback_auth", url=url, error=str(e))
                        try:
                            markdown = await fetch_with_cdp(url)
                            used_brightdata = True
                            logger.info("stream_url_conversion_cdp_success", url=url)
                        except Exception as cdp_error:
                            logger.error("stream_url_conversion_cdp_failed", url=url, error=str(cdp_error))
                            raise e
                    else:
                        raise e

            # Cache the result if caching is enabled
            if content_cache and markdown:
                content_cache.set(url, markdown, query)

        # Check for empty content
        if not markdown or not markdown.strip():
            yield json.dumps({"type": "error", "message": "No content extracted from URL"}) + "\n"
            return

        # Split into paragraphs/chunks
        chunks = split_markdown_into_paragraphs(markdown)

        # Create smart batches for efficient processing
        batches = create_smart_batches(chunks, max_batch_size=32, max_tokens_per_batch=8000)

        logger.info(f"Split markdown into {len(chunks)} chunks, organized into {len(batches)} batches")

        # Stream metadata first
        source = "cache" if from_cache else ("brightdata" if used_brightdata else "direct")
        metadata = {
            "type": "metadata",
            "filename": os.path.basename(url) or "url_content",
            "total_chunks": len(chunks),
            "total_batches": len(batches),
            "source": source,
            "cached": from_cache
        }
        yield json.dumps(metadata) + "\n"

        # Stream each batch
        for batch_idx, batch in enumerate(batches):
            batch_data = {
                "type": "batch",
                "batch_index": batch_idx,
                "chunks": batch,
                "chunk_count": len(batch),
                "total_batches": len(batches)
            }
            yield json.dumps(batch_data) + "\n"

        # Stream completion marker
        completion = {
            "type": "complete",
            "total_chunks": len(chunks),
            "source": source
        }
        yield json.dumps(completion) + "\n"

        logger.info(f"Completed streaming conversion for URL: {url} (source: {source})")

    except httpx.HTTPStatusError as e:
        error_data = {
            "type": "error",
            "message": f"HTTP error: {str(e)}",
            "url": url
        }
        yield json.dumps(error_data) + "\n"
        logger.error(f"HTTP error in streaming conversion for {url}: {str(e)}")

    except httpx.HTTPError as e:
        error_data = {
            "type": "error",
            "message": f"Request error: {str(e)}",
            "url": url
        }
        yield json.dumps(error_data) + "\n"
        logger.error(f"Request error in streaming conversion for {url}: {str(e)}")

    except Exception as e:
        error_data = {
            "type": "error",
            "message": f"Conversion error: {str(e)}",
            "url": url
        }
        yield json.dumps(error_data) + "\n"
        logger.error(f"Error in streaming conversion for {url}: {str(e)}")
