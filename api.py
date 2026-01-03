"""
MarkItDown API - Backward Compatible Entry Point

This file provides backward compatibility for existing imports.
All code has been modularized into the app/ package.

Usage:
    uvicorn api:app --port 8000

Structure:
    app/
    ├── config.py              # Environment variables
    ├── logging_config.py      # Structlog configuration
    ├── models.py              # Pydantic models
    ├── main.py                # FastAPI app and routes
    ├── core/
    │   ├── cache.py           # ContentCache
    │   ├── storage.py         # Redis/InMemory storage
    │   └── playwright_pool.py # Browser connection pool
    ├── scraping/
    │   ├── utils.py           # is_blocked_error
    │   └── brightdata.py      # Bright Data functions
    ├── processing/
    │   ├── nlp.py             # spaCy query extraction
    │   ├── tokens.py          # tiktoken counting
    │   └── chunking.py        # LangChain chunking
    └── services/
        ├── conversion.py      # URL conversion
        ├── streaming.py       # Streaming conversion
        └── deep_search.py     # Deep search pipeline (SERP + scrape + chunk + rerank)
"""

# Re-export everything for backward compatibility with existing imports
from app.main import app

# Config
from app.config import (
    BRIGHTDATA_API_TOKEN,
    BRIGHTDATA_ZONE,
    BRIGHTDATA_API_URL,
    BRIGHTDATA_SB_WS_URL,
    CACHE_TTL,
    CACHE_ENABLED,
    REDIS_HOST,
    REDIS_PORT,
    JOB_EXPIRY,
    SERP_API_KEY,
    JINA_API_KEY,
    DEEP_SEARCH_MAX_RESULTS,
    DEEP_SEARCH_MAX_SOURCES,
    DEEP_SEARCH_TOP_CHUNKS,
)

# Logging
from app.logging_config import logger, request_id_ctx

# Models
from app.models import URLRequest, DeepSearchRequest

# Core
from app.core.cache import ContentCache, content_cache
from app.core.storage import (
    JobStorage,
    RedisJobStorage,
    InMemoryJobStorage,
    DummyRedisClient,
    storage,
    redis_client,
)
from app.core.playwright_pool import PlaywrightPool, playwright_pool

# Scraping
from app.scraping.utils import is_blocked_error
from app.scraping.brightdata import (
    fetch_via_brightdata,
    fetch_with_js_rendering,
    md,
)

# Processing
from app.processing.nlp import extract_text_from_markdown
from app.processing.tokens import count_tokens, tiktoken_encoder
from app.processing.chunking import (
    split_markdown_into_paragraphs,
    create_smart_batches,
    markdown_splitter,
)

# Services
from app.services.conversion import process_url, run_sync_in_executor
from app.services.streaming import stream_url_conversion
from app.services.deep_search import (
    deep_search_stream,
    search_web,
    scrape_urls,
    chunk_text,
    rerank_chunks,
    SearchResult,
    ScrapedSource,
    RankedChunk,
)


__all__ = [
    # App
    "app",
    # Config
    "BRIGHTDATA_API_TOKEN", "BRIGHTDATA_ZONE", "BRIGHTDATA_API_URL", "BRIGHTDATA_SB_WS_URL",
    "CACHE_TTL", "CACHE_ENABLED", "REDIS_HOST", "REDIS_PORT", "JOB_EXPIRY",
    "SERP_API_KEY", "JINA_API_KEY", "DEEP_SEARCH_MAX_RESULTS", "DEEP_SEARCH_MAX_SOURCES", "DEEP_SEARCH_TOP_CHUNKS",
    # Logging
    "logger", "request_id_ctx",
    # Models
    "URLRequest", "DeepSearchRequest",
    # Core
    "ContentCache", "content_cache",
    "JobStorage", "RedisJobStorage", "InMemoryJobStorage", "DummyRedisClient", "storage", "redis_client",
    "PlaywrightPool", "playwright_pool",
    # Scraping
    "is_blocked_error", "fetch_via_brightdata", "fetch_with_js_rendering", "md",
    # Processing
    "extract_text_from_markdown",
    "count_tokens", "tiktoken_encoder",
    "split_markdown_into_paragraphs", "create_smart_batches", "markdown_splitter",
    # Services
    "process_url", "run_sync_in_executor", "stream_url_conversion",
    # Deep Search
    "deep_search_stream", "search_web", "scrape_urls", "chunk_text", "rerank_chunks",
    "SearchResult", "ScrapedSource", "RankedChunk",
]
