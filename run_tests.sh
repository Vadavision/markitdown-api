#!/bin/bash

# Test runner script for MarkItDown API
# Usage: ./run_tests.sh [scenario]
#
# Scenarios:
#   all         - Run all tests
#   direct      - Test direct MarkItDown (static sites)
#   unlocker    - Test Web Unlocker (403/blocked sites)
#   captcha     - Test Web Unlocker (captcha sites)
#   cdp         - Test CDP/Scraping Browser (SPA/JS sites)
#   cache       - Test caching functionality
#   health      - Test API health endpoints
#   fast        - Run only fast tests (exclude slow)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default API URL
export API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}MarkItDown API Test Runner${NC}"
echo -e "${YELLOW}API URL: ${API_BASE_URL}${NC}"
echo -e "${YELLOW}========================================${NC}"

# Check if API is running
echo -e "\n${YELLOW}Checking API health...${NC}"
if curl -s "${API_BASE_URL}/health" > /dev/null 2>&1; then
    echo -e "${GREEN}API is running${NC}"
else
    echo -e "${RED}API is not running at ${API_BASE_URL}${NC}"
    echo -e "${YELLOW}Start the API first: uvicorn api:app --reload${NC}"
    exit 1
fi

# Parse scenario argument
SCENARIO="${1:-all}"

case "$SCENARIO" in
    all)
        echo -e "\n${YELLOW}Running ALL tests...${NC}"
        pytest tests/test_scraping_scenarios.py -v -s
        ;;
    direct)
        echo -e "\n${YELLOW}Running DIRECT MarkItDown tests...${NC}"
        pytest tests/test_scraping_scenarios.py -v -s -k "TestDirectMarkItDown"
        ;;
    unlocker)
        echo -e "\n${YELLOW}Running WEB UNLOCKER (403) tests...${NC}"
        pytest tests/test_scraping_scenarios.py -v -s -k "TestWebUnlocker403"
        ;;
    captcha)
        echo -e "\n${YELLOW}Running WEB UNLOCKER (CAPTCHA) tests...${NC}"
        pytest tests/test_scraping_scenarios.py -v -s -k "TestWebUnlockerCaptcha"
        ;;
    cdp)
        echo -e "\n${YELLOW}Running CDP/SCRAPING BROWSER tests...${NC}"
        pytest tests/test_scraping_scenarios.py -v -s -k "TestCDPJSRendering"
        ;;
    cache)
        echo -e "\n${YELLOW}Running CACHE tests...${NC}"
        pytest tests/test_scraping_scenarios.py -v -s -k "TestCaching"
        ;;
    health)
        echo -e "\n${YELLOW}Running HEALTH/API tests...${NC}"
        pytest tests/test_scraping_scenarios.py -v -s -k "TestAPIHealth"
        ;;
    fast)
        echo -e "\n${YELLOW}Running FAST tests (excluding slow)...${NC}"
        pytest tests/test_scraping_scenarios.py -v -s -m "not slow"
        ;;
    performance)
        echo -e "\n${YELLOW}Running PERFORMANCE tests...${NC}"
        pytest tests/test_scraping_scenarios.py -v -s -k "TestPerformance"
        ;;
    controls)
        echo -e "\n${YELLOW}Running CONTROL tests...${NC}"
        pytest tests/test_controls.py -v -s
        ;;
    controls-unit)
        echo -e "\n${YELLOW}Running UNIT CONTROL tests (no API needed)...${NC}"
        pytest tests/test_controls.py -v -s -k "not api_client"
        ;;
    fallback)
        echo -e "\n${YELLOW}Running FALLBACK CHAIN tests...${NC}"
        pytest tests/test_controls.py -v -s -k "TestControlFallbackChain"
        ;;
    *)
        echo -e "${RED}Unknown scenario: $SCENARIO${NC}"
        echo -e "Usage: $0 [all|direct|unlocker|captcha|cdp|cache|health|fast|performance|controls|controls-unit|fallback]"
        exit 1
        ;;
esac

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Tests completed!${NC}"
echo -e "${GREEN}========================================${NC}"
