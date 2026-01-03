"""
Scraping utility functions.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""


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
