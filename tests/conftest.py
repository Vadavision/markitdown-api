"""
Pytest configuration and shared fixtures.
"""

import pytest
import httpx
import os

# API configuration
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
TIMEOUT = float(os.environ.get("TEST_TIMEOUT", "120"))


@pytest.fixture(scope="session")
def api_base_url():
    """Get API base URL from environment or default."""
    return API_BASE_URL


@pytest.fixture
async def api_client(api_base_url):
    """Create async HTTP client for API calls."""
    async with httpx.AsyncClient(base_url=api_base_url, timeout=TIMEOUT) as client:
        yield client


@pytest.fixture
def sync_client(api_base_url):
    """Create sync HTTP client for simple checks."""
    with httpx.Client(base_url=api_base_url, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as requiring external services"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection."""
    # Add 'integration' marker to all tests in test_scraping_scenarios.py
    for item in items:
        if "scraping_scenarios" in item.nodeid:
            item.add_marker(pytest.mark.integration)
