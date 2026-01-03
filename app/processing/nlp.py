"""
NLP and text processing functions.
Provides text extraction from markdown for content processing.

Note: Keyword-based query matching (has_query_content, extract_search_terms) has been
removed in favor of semantic search using Jina reranker in deep_search.py.
"""
import re

from app.logging_config import logger


def extract_text_from_markdown(markdown: str) -> str:
    """
    Remove only non-text content (images, SVG, canvas, base64 data).
    Keeps links, formatting, and everything else for better matching.
    """
    if not markdown:
        return ""

    text = markdown

    # Remove images: ![alt](url) or ![alt](data:...)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)

    # Remove base64 data URIs
    text = re.sub(r'data:[^;]+;base64,[A-Za-z0-9+/=]+', '', text)

    # Remove SVG content
    text = re.sub(r'<svg[\s\S]*?</svg>', '', text, flags=re.IGNORECASE)

    # Remove canvas tags
    text = re.sub(r'<canvas[\s\S]*?</canvas>', '', text, flags=re.IGNORECASE)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text
