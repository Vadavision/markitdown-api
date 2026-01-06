"""
Scraping modules - Bright Data Web Unlocker, utils.
CDP/Scraping Browser is in app.core.cdp_queue.
"""
from app.scraping.utils import is_blocked_error, is_social_media_url
from app.scraping.brightdata import fetch_via_brightdata, md

__all__ = [
    "is_blocked_error",
    "is_social_media_url",
    "fetch_via_brightdata",
    "md",
]
