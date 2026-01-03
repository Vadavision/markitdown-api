"""
Pydantic models for request/response validation.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
from pydantic import BaseModel
from typing import Optional


class URLRequest(BaseModel):
    url: str
    query: Optional[str] = None  # Search query for smart JS rendering detection


class DeepSearchRequest(BaseModel):
    """Request model for deep search endpoint."""
    query: str
    num_results: Optional[int] = None  # Max search results from SERP API
    num_sources: Optional[int] = None  # Max URLs to scrape
    top_chunks: Optional[int] = None   # Number of top chunks to return after reranking
