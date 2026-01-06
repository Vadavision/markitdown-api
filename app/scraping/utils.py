"""
Scraping utility functions.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
from urllib.parse import urlparse


def get_domain(url: str) -> str:
    """Extract the domain from a URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return ""


def is_social_media_url(url: str) -> bool:
    """
    Check if the URL is from a social media platform that may need specialized scraping.
    These sites often require authentication for full profile data.
    """
    social_domains = {
        "linkedin.com", "facebook.com", "instagram.com",
        "twitter.com", "x.com", "tiktok.com"
    }
    domain = get_domain(url)
    return any(social in domain for social in social_domains)


def is_blocked_error(error: Exception) -> bool:
    """
    Check if the error indicates the request was blocked (403, captcha, etc.)
    """
    error_str = str(error).lower()
    # Check for common blocking indicators
    blocked_indicators = [
        "403", "forbidden",
        "captcha", "challenge",
        "blocked", "denied",
        "access denied", "bot",
        "429", "too many requests",
        "cloudflare", "security check"
    ]
    return any(indicator in error_str for indicator in blocked_indicators)
