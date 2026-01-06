"""
Search Service - Clean, Agent-Friendly Web Search Pipeline.
Handles SERP search, scraping, chunking, reranking with automatic CDP fallback.
"""
import asyncio
import json
import httpx
import urllib.parse
from typing import Optional, AsyncGenerator, List, Dict, Any
from dataclasses import dataclass

from app.logging_config import logger
from app.config import (
    SERP_API_KEY,
    JINA_API_KEY,
    SEARCH_DEFAULT_LIMIT,
    SEARCH_DEFAULT_TOP_K,
    BRIGHTDATA_SB_WS_URL,
    BRIGHTDATA_API_TOKEN,
    BRIGHTDATA_SERP_ZONE,
)
from app.services.streaming import stream_url_conversion
from app.processing.chunking import split_markdown_into_paragraphs
from app.processing.nlp import extract_text_from_markdown
from app.core.cdp_queue import fetch_with_cdp  # Queue-based CDP processing

# Per-URL timeout for scraping (seconds) - prevents a single URL from blocking everything
SCRAPE_URL_TIMEOUT = 45

# Minimum relevance score to consider content valid (not a JS shell)
RELEVANCE_THRESHOLD = 0.3


@dataclass
class SearchResult:
    """Search result from SERP API."""
    title: str
    url: str
    snippet: str


@dataclass
class ScrapedSource:
    """Scraped content from a URL."""
    url: str
    title: str
    content: str


@dataclass
class RankedChunk:
    """Chunk with relevance score."""
    content: str
    source_url: str
    source_title: str
    relevance_score: float


# =============================================================================
# SERP SEARCH
# =============================================================================

async def search_with_serpapi(query: str, limit: int, page: int = 1) -> List[SearchResult]:
    """Search using SerpAPI (primary) with pagination support."""
    start = (page - 1) * limit

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            "https://serpapi.com/search",
            params={
                "q": query,
                "api_key": SERP_API_KEY,
                "engine": "google",
                "num": limit,
                "start": start,
            }
        )
        response.raise_for_status()
        data = response.json()

    results = []
    for r in data.get("organic_results", []):
        results.append(SearchResult(
            title=r.get("title", ""),
            url=r.get("link", ""),
            snippet=r.get("snippet", "")
        ))
    return results


async def search_with_brightdata(query: str, limit: int, page: int = 1) -> List[SearchResult]:
    """Search using BrightData SERP API (fallback) with pagination support."""
    if not BRIGHTDATA_API_TOKEN:
        raise ValueError("BRIGHTDATA_API_TOKEN not configured for SERP fallback")

    start = (page - 1) * limit
    encoded_query = urllib.parse.quote_plus(query)
    google_url = f"https://www.google.com/search?q={encoded_query}&num={limit}&start={start}&brd_json=1"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.brightdata.com/request",
            headers={
                "Authorization": f"Bearer {BRIGHTDATA_API_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "zone": BRIGHTDATA_SERP_ZONE,
                "url": google_url,
                "format": "json",
            }
        )
        response.raise_for_status()
        data = response.json()

    body = data.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    results = []
    for r in body.get("organic", []):
        results.append(SearchResult(
            title=r.get("title", ""),
            url=r.get("link", ""),
            snippet=r.get("description", "")
        ))

    logger.info("brightdata_serp_complete", query=query, results=len(results))
    return results


async def search_serp(query: str, limit: int = None, page: int = 1) -> List[SearchResult]:
    """
    Search web using SERP API with BrightData fallback.

    Args:
        query: Search query string
        limit: Results per page (default from config)
        page: Page number, 1-indexed (default 1)
    """
    limit = limit or SEARCH_DEFAULT_LIMIT

    # Try SerpAPI first
    if SERP_API_KEY:
        try:
            results = await search_with_serpapi(query, limit, page)
            logger.info("serp_search_complete", query=query, page=page, results=len(results))
            return results
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("serpapi_rate_limited", query=query)
            else:
                raise

    # Fallback to BrightData SERP API
    if BRIGHTDATA_API_TOKEN:
        try:
            results = await search_with_brightdata(query, limit, page)
            return results
        except Exception as e:
            logger.error("brightdata_serp_failed", query=query, error=str(e))
            raise

    raise ValueError("No SERP API configured (need SERP_API_KEY or BRIGHTDATA_API_TOKEN)")


# =============================================================================
# SCRAPING
# =============================================================================

async def scrape_url(url: str, title: str, snippet: str, query: str) -> ScrapedSource:
    """Scrape a single URL using the streaming conversion service."""
    try:
        chunks = []
        async for line in stream_url_conversion(url, query):
            if line.strip():
                data = json.loads(line)
                if data.get("type") == "batch":
                    chunks.extend(data.get("chunks", []))
                elif data.get("type") == "error":
                    raise Exception(data.get("message", "Scraping failed"))

        content = "\n\n".join(chunks)
        if content and len(content.strip()) > 100:
            return ScrapedSource(url=url, title=title, content=content)

        return ScrapedSource(url=url, title=title, content=snippet)

    except Exception as e:
        logger.warning("scrape_url_failed", url=url, error=str(e))
        return ScrapedSource(url=url, title=title, content=snippet)


async def scrape_urls(results: List[SearchResult], query: str) -> List[ScrapedSource]:
    """Scrape all search result URLs in parallel."""
    tasks = [
        scrape_url(r.url, r.title, r.snippet, query)
        for r in results
    ]
    scraped = await asyncio.gather(*tasks, return_exceptions=True)

    sources = []
    for s in scraped:
        if isinstance(s, ScrapedSource) and len(s.content) > 50:
            sources.append(s)

    logger.info("scrape_urls_complete", total=len(results), successful=len(sources))
    return sources


async def scrape_url_with_cdp(url: str) -> str:
    """Scrape URL using CDP (headless browser with JS rendering)."""
    try:
        content = await fetch_with_cdp(url)
        logger.info("cdp_scrape_complete", url=url, chars=len(content))
        return content
    except Exception as e:
        logger.error("cdp_scrape_failed", url=url, error=str(e))
        return ""


# =============================================================================
# CHUNKING & RERANKING
# =============================================================================

def chunk_text(text: str) -> List[str]:
    """Chunk text using LangChain's MarkdownTextSplitter."""
    cleaned = extract_text_from_markdown(text)
    return split_markdown_into_paragraphs(cleaned)


async def rerank_chunks(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: int = None
) -> List[RankedChunk]:
    """Rerank chunks using Jina Reranker API."""
    top_k = top_k or SEARCH_DEFAULT_TOP_K

    if not JINA_API_KEY or not chunks:
        return [
            RankedChunk(
                content=c["content"],
                source_url=c["source_url"],
                source_title=c["source_title"],
                relevance_score=1 - idx * 0.1
            )
            for idx, c in enumerate(chunks)
        ][:top_k]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.jina.ai/v1/rerank",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {JINA_API_KEY}",
                },
                json={
                    "model": "jina-reranker-v2-base-multilingual",
                    "query": query,
                    "documents": [c["content"] for c in chunks],
                    "top_n": min(len(chunks), top_k * 2),
                }
            )
            response.raise_for_status()
            data = response.json()

        ranked = []
        for r in data.get("results", []):
            idx = r["index"]
            ranked.append(RankedChunk(
                content=chunks[idx]["content"],
                source_url=chunks[idx]["source_url"],
                source_title=chunks[idx]["source_title"],
                relevance_score=r["relevance_score"]
            ))

        ranked.sort(key=lambda x: x.relevance_score, reverse=True)
        logger.info("rerank_complete", total_chunks=len(chunks), top_score=ranked[0].relevance_score if ranked else 0)
        return ranked[:top_k]

    except Exception as e:
        logger.error("rerank_failed", error=str(e))
        return [
            RankedChunk(
                content=c["content"],
                source_url=c["source_url"],
                source_title=c["source_title"],
                relevance_score=1 - idx * 0.05
            )
            for idx, c in enumerate(chunks)
        ][:top_k]


async def rerank_and_check_relevance(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: int = None
) -> tuple[bool, List[RankedChunk]]:
    """
    Rerank chunks and check if content is semantically relevant.
    Returns (is_relevant, ranked_chunks).
    """
    ranked = await rerank_chunks(query, chunks, top_k)

    if not ranked:
        return False, []

    best_score = ranked[0].relevance_score
    is_relevant = best_score >= RELEVANCE_THRESHOLD

    logger.info(
        "relevance_check",
        best_score=round(best_score, 3),
        threshold=RELEVANCE_THRESHOLD,
        is_relevant=is_relevant,
        num_chunks=len(chunks)
    )

    return is_relevant, ranked


# =============================================================================
# MAIN STREAMING ENDPOINTS
# =============================================================================

async def search_stream(
    query: str,
    page: int = 1,
    limit: int = None,
    top_k: int = None
) -> AsyncGenerator[str, None]:
    """
    Full search pipeline with streaming progress.

    1. Search via SERP API (with pagination)
    2. Scrape all result URLs in parallel
    3. Chunk all content
    4. Rerank with Jina
    5. Return top relevant chunks

    Args:
        query: Search query string (required)
        page: SERP page number, 1-indexed (default: 1)
        limit: Results per SERP page (default: 10)
        top_k: Top chunks to return after reranking (default: 8)

    Yields JSON-delimited progress updates and results.
    """
    limit = limit or SEARCH_DEFAULT_LIMIT
    top_k = top_k or SEARCH_DEFAULT_TOP_K

    all_sources: List[Dict[str, str]] = []

    try:
        # Step 1: Search with pagination
        yield json.dumps({
            "type": "progress",
            "status": "searching",
            "message": f"Searching for: {query} (page {page}, limit {limit})..."
        }) + "\n"

        search_results = await search_serp(query, limit, page)

        if not search_results:
            yield json.dumps({
                "type": "error",
                "message": "No search results found"
            }) + "\n"
            return

        yield json.dumps({
            "type": "progress",
            "status": "scraping",
            "message": f"Reading {len(search_results)} sources..."
        }) + "\n"

        # Step 2: Scrape all URLs
        scraped_sources = await scrape_urls(search_results, query)

        if not scraped_sources:
            yield json.dumps({
                "type": "error",
                "message": "Failed to scrape any sources"
            }) + "\n"
            return

        # Track sources
        for s in scraped_sources:
            all_sources.append({"url": s.url, "title": s.title})

        yield json.dumps({
            "type": "sources",
            "sources": all_sources
        }) + "\n"

        # Step 3: Chunk all content
        yield json.dumps({
            "type": "progress",
            "status": "chunking",
            "message": f"Processing {len(scraped_sources)} sources..."
        }) + "\n"

        all_chunks = []
        for source in scraped_sources:
            chunks = chunk_text(source.content)
            for chunk in chunks:
                all_chunks.append({
                    "content": chunk,
                    "source_url": source.url,
                    "source_title": source.title
                })

        logger.info("chunking_complete", total_chunks=len(all_chunks))

        if not all_chunks:
            yield json.dumps({
                "type": "error",
                "message": "No content extracted from sources"
            }) + "\n"
            return

        # Step 4: Rerank and check relevance
        yield json.dumps({
            "type": "progress",
            "status": "ranking",
            "message": f"Ranking {len(all_chunks)} passages by relevance..."
        }) + "\n"

        is_relevant, ranked_chunks = await rerank_and_check_relevance(query, all_chunks, top_k)

        # Step 4b: If content not relevant, try CDP for JS-rendered pages
        if not is_relevant and BRIGHTDATA_SB_WS_URL:
            yield json.dumps({
                "type": "progress",
                "status": "js_rendering",
                "message": "Content may be JS-rendered, fetching with browser..."
            }) + "\n"

            logger.info("triggering_cdp_fallback", reason="low_relevance_score")

            cdp_tasks = [scrape_url_with_cdp(s.url) for s in scraped_sources]
            cdp_results = await asyncio.gather(*cdp_tasks, return_exceptions=True)

            all_chunks = []
            for idx, content in enumerate(cdp_results):
                if isinstance(content, str) and len(content) > 100:
                    source = scraped_sources[idx]
                    chunks = chunk_text(content)
                    for chunk in chunks:
                        all_chunks.append({
                            "content": chunk,
                            "source_url": source.url,
                            "source_title": source.title
                        })

            if all_chunks:
                logger.info("cdp_chunking_complete", total_chunks=len(all_chunks))

                yield json.dumps({
                    "type": "progress",
                    "status": "ranking",
                    "message": f"Re-ranking {len(all_chunks)} JS-rendered passages..."
                }) + "\n"

                _, ranked_chunks = await rerank_and_check_relevance(query, all_chunks, top_k)
            else:
                logger.warning("cdp_no_content", message="CDP scrape returned no content")

        # Step 5: Return results
        yield json.dumps({
            "type": "progress",
            "status": "complete",
            "message": f"Found {len(ranked_chunks)} relevant passages from {len(all_sources)} sources"
        }) + "\n"

        for idx, chunk in enumerate(ranked_chunks):
            yield json.dumps({
                "type": "chunk",
                "index": idx,
                "content": chunk.content,
                "source_url": chunk.source_url,
                "source_title": chunk.source_title,
                "relevance_score": round(chunk.relevance_score, 4)
            }) + "\n"

        yield json.dumps({
            "type": "done",
            "query": query,
            "page": page,
            "total_sources": len(all_sources),
            "total_chunks": len(ranked_chunks),
            "sources": all_sources
        }) + "\n"

        logger.info("search_complete", query=query, page=page, sources=len(all_sources), chunks=len(ranked_chunks))

    except Exception as e:
        logger.error("search_error", query=query, error=str(e))
        yield json.dumps({
            "type": "error",
            "message": f"Search failed: {str(e)}"
        }) + "\n"


async def fetch_stream(
    url: str,
    query: Optional[str] = None,
    top_k: int = None
) -> AsyncGenerator[str, None]:
    """
    Fetch a single URL, chunk content, and optionally rerank.
    Automatically falls back to CDP (browser rendering) if content relevance is low.

    Args:
        url: URL to fetch (required)
        query: Optional query for relevance checking and focused reranking
        top_k: Top chunks if query provided (default: 10)

    Yields JSON-delimited progress updates and content chunks.
    """
    top_k = top_k or 10

    try:
        yield json.dumps({
            "type": "progress",
            "status": "fetching",
            "message": f"Fetching: {url}..."
        }) + "\n"

        # Step 1: Fetch content via streaming conversion
        content = ""
        chunks = []
        used_cdp = False  # Track if CDP was already used

        async for line in stream_url_conversion(url, query):
            if line.strip():
                data = json.loads(line)
                if data.get("type") == "metadata":
                    # Check if CDP/brightdata was already used
                    if data.get("source") == "brightdata":
                        used_cdp = True
                elif data.get("type") == "batch":
                    chunks.extend(data.get("chunks", []))
                elif data.get("type") == "error":
                    raise Exception(data.get("message", "Scraping failed"))

        content = "\n\n".join(chunks)

        # Step 2: If we have a query, check relevance and maybe fall back to CDP
        # Skip CDP fallback if already used (e.g., for social media URLs)
        if query and content and len(content) > 100:
            yield json.dumps({
                "type": "progress",
                "status": "checking",
                "message": "Checking content relevance..."
            }) + "\n"

            text_chunks = chunk_text(content)
            sample_chunks = [{"content": c, "source_url": url, "source_title": url} for c in text_chunks[:5]]

            if sample_chunks:
                is_relevant, _ = await rerank_and_check_relevance(query, sample_chunks, top_k=3)

                # Only try CDP fallback if not already used and content is irrelevant
                if not is_relevant and BRIGHTDATA_SB_WS_URL and not used_cdp:
                    yield json.dumps({
                        "type": "progress",
                        "status": "js_rendering",
                        "message": "Content may be JS-rendered, fetching with browser..."
                    }) + "\n"

                    logger.info("fetch_cdp_fallback", url=url, reason="low_relevance")

                    cdp_content = await scrape_url_with_cdp(url)
                    if cdp_content and len(cdp_content) > 100:
                        content = cdp_content
                        used_cdp = True
                elif not is_relevant and used_cdp:
                    # Already used CDP but content still not relevant - log it
                    logger.warning("fetch_cdp_low_relevance", url=url, reason="cdp_content_not_relevant")

        # Step 3: Chunk and return content
        if not content or len(content) < 50:
            yield json.dumps({
                "type": "error",
                "message": "Failed to extract content from URL"
            }) + "\n"
            return

        yield json.dumps({
            "type": "progress",
            "status": "chunking",
            "message": "Processing content..."
        }) + "\n"

        text_chunks = chunk_text(content)
        all_chunks = [{"content": c, "source_url": url, "source_title": url} for c in text_chunks]

        # Step 4: If query provided, rerank chunks
        if query and all_chunks:
            yield json.dumps({
                "type": "progress",
                "status": "ranking",
                "message": f"Ranking {len(all_chunks)} passages..."
            }) + "\n"

            _, ranked_chunks = await rerank_and_check_relevance(query, all_chunks, top_k=top_k)

            for idx, chunk in enumerate(ranked_chunks):
                yield json.dumps({
                    "type": "chunk",
                    "index": idx,
                    "content": chunk.content,
                    "source_url": chunk.source_url,
                    "relevance_score": round(chunk.relevance_score, 4)
                }) + "\n"
        else:
            # No query, just return all chunks
            for idx, chunk in enumerate(all_chunks):
                yield json.dumps({
                    "type": "chunk",
                    "index": idx,
                    "content": chunk["content"],
                    "source_url": url
                }) + "\n"

        yield json.dumps({
            "type": "done",
            "url": url,
            "total_chunks": len(all_chunks),
            "used_cdp": used_cdp
        }) + "\n"

        logger.info("fetch_complete", url=url, chunks=len(all_chunks), used_cdp=used_cdp)

    except Exception as e:
        logger.error("fetch_error", url=url, error=str(e))
        yield json.dumps({
            "type": "error",
            "message": f"Fetch failed: {str(e)}"
        }) + "\n"
