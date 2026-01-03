"""
Deep Search Service - Search, Scrape, Chunk, Rerank Pipeline.
Moved from Node.js deep-search.service.ts to Python for better performance.
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
    DEEP_SEARCH_MAX_RESULTS,
    DEEP_SEARCH_MAX_SOURCES,
    DEEP_SEARCH_TOP_CHUNKS,
    BRIGHTDATA_SB_WS_URL,
    BRIGHTDATA_API_TOKEN,
    BRIGHTDATA_SERP_ZONE,
)
from app.services.streaming import stream_url_conversion
from app.processing.chunking import split_markdown_into_paragraphs
from app.processing.nlp import extract_text_from_markdown
from app.scraping.brightdata import fetch_with_js_rendering

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


async def search_with_serpapi(query: str, num_results: int) -> List[SearchResult]:
    """Search using SerpAPI (primary)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            "https://serpapi.com/search",
            params={
                "q": query,
                "api_key": SERP_API_KEY,
                "engine": "google",
                "num": num_results,
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


async def search_with_brightdata(query: str, num_results: int) -> List[SearchResult]:
    """Search using BrightData SERP API (fallback)."""
    if not BRIGHTDATA_API_TOKEN:
        raise ValueError("BRIGHTDATA_API_TOKEN not configured for SERP fallback")

    # Build Google search URL with brd_json=1 for parsed JSON response
    encoded_query = urllib.parse.quote_plus(query)
    google_url = f"https://www.google.com/search?q={encoded_query}&num={num_results}&brd_json=1"

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

    # Response body is a JSON string, parse it
    body = data.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    results = []
    # BrightData SERP API returns organic results in 'organic' array
    for r in body.get("organic", []):
        results.append(SearchResult(
            title=r.get("title", ""),
            url=r.get("link", ""),
            snippet=r.get("description", "")
        ))

    logger.info("brightdata_serp_complete", query=query, results=len(results))
    return results


async def search_web(query: str, num_results: int = None) -> List[SearchResult]:
    """
    Search web using SERP API with BrightData fallback.
    Falls back to BrightData SERP API on 429 rate limit errors.
    """
    num_results = num_results or DEEP_SEARCH_MAX_RESULTS

    # Try SerpAPI first
    if SERP_API_KEY:
        try:
            results = await search_with_serpapi(query, num_results)
            logger.info("serp_search_complete", query=query, results=len(results))
            return results
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("serpapi_rate_limited", query=query)
                # Fall through to BrightData
            else:
                raise

    # Fallback to BrightData SERP API
    if BRIGHTDATA_API_TOKEN:
        try:
            results = await search_with_brightdata(query, num_results)
            return results
        except Exception as e:
            logger.error("brightdata_serp_failed", query=query, error=str(e))
            raise

    raise ValueError("No SERP API configured (need SERP_API_KEY or BRIGHTDATA_API_TOKEN)")


async def scrape_url(url: str, title: str, snippet: str, query: str) -> ScrapedSource:
    """
    Scrape a single URL using the streaming conversion service.
    Falls back to snippet if scraping fails.
    """
    try:
        # Collect all chunks from streaming conversion
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

        # Fallback to snippet
        return ScrapedSource(url=url, title=title, content=snippet)

    except Exception as e:
        logger.warning("scrape_url_failed", url=url, error=str(e))
        return ScrapedSource(url=url, title=title, content=snippet)


async def scrape_urls(results: List[SearchResult], query: str, max_sources: int = None) -> List[ScrapedSource]:
    """
    Scrape multiple URLs in parallel.
    Returns list of scraped sources with content.
    """
    max_sources = max_sources or DEEP_SEARCH_MAX_SOURCES
    results_to_scrape = results[:max_sources]

    # Scrape all URLs in parallel
    tasks = [
        scrape_url(r.url, r.title, r.snippet, query)
        for r in results_to_scrape
    ]
    scraped = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out exceptions and empty content
    sources = []
    for s in scraped:
        if isinstance(s, ScrapedSource) and len(s.content) > 50:
            sources.append(s)

    logger.info("scrape_urls_complete", total=len(results_to_scrape), successful=len(sources))
    return sources


def chunk_text(text: str) -> List[str]:
    """
    Chunk text using LangChain's MarkdownTextSplitter.
    Reuses existing chunking.py implementation.
    """
    # Clean content first
    cleaned = extract_text_from_markdown(text)
    # Use LangChain's markdown-aware splitter
    return split_markdown_into_paragraphs(cleaned)


async def rerank_and_check_relevance(
    query: str,
    chunks: List[Dict[str, Any]],
    top_n: int = None
) -> tuple[bool, List[RankedChunk]]:
    """
    Rerank chunks and check if content is semantically relevant.
    Returns (is_relevant, ranked_chunks) - reuse ranked_chunks if relevant!

    This avoids duplicate Jina API calls by combining:
    1. Relevance check (is content a JS shell or real content?)
    2. Final ranking for results
    """
    ranked = await rerank_chunks(query, chunks, top_n)

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


async def scrape_with_cdp_fallback(
    url: str,
    title: str,
    snippet: str,
    query: str
) -> tuple[str, bool]:
    """
    Scrape URL with static method first, return content.
    Returns (content, used_cdp) tuple.
    CDP fallback is handled at the pipeline level after relevance check.
    """
    try:
        # Collect all chunks from streaming conversion (static scrape)
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
            return content, False

        # Fallback to snippet
        return snippet, False

    except Exception as e:
        logger.warning("scrape_url_failed", url=url, error=str(e))
        return snippet, False


async def scrape_url_with_cdp(url: str) -> str:
    """
    Scrape URL using CDP (headless browser with JS rendering).
    Used when static scrape content is not relevant.
    """
    try:
        content = await fetch_with_js_rendering(url)
        logger.info("cdp_scrape_complete", url=url, chars=len(content))
        return content
    except Exception as e:
        logger.error("cdp_scrape_failed", url=url, error=str(e))
        return ""


async def rerank_chunks(
    query: str,
    chunks: List[Dict[str, Any]],
    top_n: int = None
) -> List[RankedChunk]:
    """
    Rerank chunks using Jina Reranker API.
    Returns chunks sorted by relevance score.
    """
    top_n = top_n or DEEP_SEARCH_TOP_CHUNKS

    if not JINA_API_KEY or not chunks:
        # No reranking, return as-is with default scores
        return [
            RankedChunk(
                content=c["content"],
                source_url=c["source_url"],
                source_title=c["source_title"],
                relevance_score=1 - idx * 0.1
            )
            for idx, c in enumerate(chunks)
        ][:top_n]

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
                    "top_n": min(len(chunks), top_n * 2),
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

        # Sort by score descending and limit to top_n
        ranked.sort(key=lambda x: x.relevance_score, reverse=True)
        logger.info("rerank_complete", total_chunks=len(chunks), top_score=ranked[0].relevance_score if ranked else 0)
        return ranked[:top_n]

    except Exception as e:
        logger.error("rerank_failed", error=str(e))
        # Fallback: return chunks as-is
        return [
            RankedChunk(
                content=c["content"],
                source_url=c["source_url"],
                source_title=c["source_title"],
                relevance_score=1 - idx * 0.05
            )
            for idx, c in enumerate(chunks)
        ][:top_n]


async def deep_search_stream(
    query: str,
    num_results: int = None,
    num_sources: int = None,
    top_chunks: int = None
) -> AsyncGenerator[str, None]:
    """
    Full deep search pipeline with streaming progress.

    1. Search via SERP API
    2. Scrape top URLs in parallel
    3. Chunk all content
    4. Rerank with Jina
    5. Return top relevant chunks

    Yields JSON-delimited progress updates and final results.
    """
    num_results = num_results or DEEP_SEARCH_MAX_RESULTS
    num_sources = num_sources or DEEP_SEARCH_MAX_SOURCES
    top_chunks = top_chunks or DEEP_SEARCH_TOP_CHUNKS

    all_sources: List[Dict[str, str]] = []

    try:
        # Step 1: Search
        yield json.dumps({
            "type": "progress",
            "status": "searching",
            "message": f"Searching for: {query}..."
        }) + "\n"

        search_results = await search_web(query, num_results)

        if not search_results:
            yield json.dumps({
                "type": "error",
                "message": "No search results found"
            }) + "\n"
            return

        yield json.dumps({
            "type": "progress",
            "status": "scraping",
            "message": f"Reading {min(len(search_results), num_sources)} sources..."
        }) + "\n"

        # Step 2: Scrape URLs
        scraped_sources = await scrape_urls(search_results, query, num_sources)

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

        # Step 4: Rerank and check relevance (semantic search)
        yield json.dumps({
            "type": "progress",
            "status": "ranking",
            "message": f"Ranking {len(all_chunks)} passages by relevance..."
        }) + "\n"

        is_relevant, ranked_chunks = await rerank_and_check_relevance(query, all_chunks, top_chunks)

        # Step 4b: If content not relevant, try CDP for JS-rendered pages
        if not is_relevant and BRIGHTDATA_SB_WS_URL:
            yield json.dumps({
                "type": "progress",
                "status": "js_rendering",
                "message": "Content may be JS-rendered, fetching with browser..."
            }) + "\n"

            logger.info("triggering_cdp_fallback", reason="low_relevance_score")

            # Re-scrape sources with CDP
            cdp_tasks = [scrape_url_with_cdp(s.url) for s in scraped_sources]
            cdp_results = await asyncio.gather(*cdp_tasks, return_exceptions=True)

            # Rebuild chunks from CDP content
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

                # Re-rerank with CDP content
                yield json.dumps({
                    "type": "progress",
                    "status": "ranking",
                    "message": f"Re-ranking {len(all_chunks)} JS-rendered passages..."
                }) + "\n"

                _, ranked_chunks = await rerank_and_check_relevance(query, all_chunks, top_chunks)
            else:
                logger.warning("cdp_no_content", message="CDP scrape returned no content")

        # Step 5: Return results
        yield json.dumps({
            "type": "progress",
            "status": "complete",
            "message": f"Found {len(ranked_chunks)} relevant passages from {len(all_sources)} sources"
        }) + "\n"

        # Yield each ranked chunk
        for idx, chunk in enumerate(ranked_chunks):
            yield json.dumps({
                "type": "chunk",
                "index": idx,
                "content": chunk.content,
                "source_url": chunk.source_url,
                "source_title": chunk.source_title,
                "relevance_score": round(chunk.relevance_score, 4)
            }) + "\n"

        # Final completion with all sources
        yield json.dumps({
            "type": "done",
            "query": query,
            "total_sources": len(all_sources),
            "total_chunks": len(ranked_chunks),
            "sources": all_sources
        }) + "\n"

        logger.info("deep_search_complete", query=query, sources=len(all_sources), chunks=len(ranked_chunks))

    except Exception as e:
        logger.error("deep_search_error", query=query, error=str(e))
        yield json.dumps({
            "type": "error",
            "message": f"Deep search failed: {str(e)}"
        }) + "\n"
