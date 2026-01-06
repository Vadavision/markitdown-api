"""
Pydantic models for request/response validation.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
from pydantic import BaseModel
from typing import Optional


class URLRequest(BaseModel):
    url: str
    query: Optional[str] = None  # Search query for smart JS rendering detection


class SearchRequest(BaseModel):
    """
    Request model for /search endpoint.
    Clean, agent-friendly parameters for web search with scraping and reranking.
    """
    query: str                         # Search query (required)
    page: Optional[int] = 1            # SERP page number, 1-indexed (default: 1)
    limit: Optional[int] = None        # Results per SERP page (default: 10 from config)
    top_k: Optional[int] = None        # Top chunks to return after reranking (default: 8)


class FetchRequest(BaseModel):
    """
    Request model for /fetch endpoint.
    Fetch a single URL with automatic CDP (browser) fallback for JS-heavy pages.
    """
    url: str                           # URL to fetch (required)
    query: Optional[str] = None        # Optional: for relevance checking & focused reranking
    top_k: Optional[int] = None        # Top chunks if query provided (default: 10)
