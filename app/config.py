"""
Configuration and environment variables.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
import os
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# Bright Data Web Unlocker configuration
BRIGHTDATA_API_TOKEN = os.environ.get("BRIGHTDATA_API_TOKEN", "")
BRIGHTDATA_ZONE = os.environ.get("BRIGHTDATA_ZONE", "web_unlocker1")
BRIGHTDATA_API_URL = "https://api.brightdata.com/request"

# Bright Data Scraping Browser configuration (for JS rendering via CDP)
# Full WebSocket URL: wss://brd-customer-{ID}-zone-{ZONE}:{PASSWORD}@brd.superproxy.io:9222
BRIGHTDATA_SB_WS_URL = os.environ.get("BRIGHTDATA_SB_WS_URL", "")

# Content cache configuration (in-memory with TTL)
CACHE_TTL = int(os.environ.get("CACHE_TTL", "3600"))  # 1 hour default
CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "true").lower() == "true"

# Redis configuration
REDIS_HOST = os.environ.get("REDIS_HOST", "markitdown-redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# Job result expiration time (in seconds) - 24 hours
JOB_EXPIRY = 86400

# Deep Search configuration
SERP_API_KEY = os.environ.get("SERP_API_KEY", "")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")

# BrightData SERP API (fallback when SerpAPI is rate limited)
# Uses https://api.brightdata.com/request with zone and Google search URL
BRIGHTDATA_SERP_ZONE = os.environ.get("BRIGHTDATA_SERP_ZONE", "serp_api1")

# Deep search parameters
DEEP_SEARCH_MAX_RESULTS = int(os.environ.get("DEEP_SEARCH_MAX_RESULTS", "10"))
DEEP_SEARCH_MAX_SOURCES = int(os.environ.get("DEEP_SEARCH_MAX_SOURCES", "4"))
DEEP_SEARCH_TOP_CHUNKS = int(os.environ.get("DEEP_SEARCH_TOP_CHUNKS", "8"))
# Chunking uses LangChain's MarkdownTextSplitter (2000 chars, 200 overlap) from chunking.py
