#!/usr/bin/env python3
"""
Crawl4AI-based XBRL link extraction from BSE Corporate Results.

Replaces complex Playwright logic with Crawl4AI's efficient web scraping.
Handles:
- Company name or numeric scrip code input
- SmartSearch simulation
- XBRL link extraction from results grid
- Multiple broadcast periods (Beyond 1 year -> 1 year -> 6m -> 3m -> 1m)
- Categorization of Standard vs Consolidated XBRL reports
"""

import re
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from pydantic import BaseModel, Field, validator

try:
    from crawl4ai import AsyncWebCrawler, CacheMode, BrowserConfig
except ImportError:
    raise ImportError(
        "crawl4ai is not installed. Install it with: pip install crawl4ai"
    )

logger = logging.getLogger(__name__)

# ==================== Constants ====================
BSE_URL = "https://www.bseindia.com/corporates/Comp_Resultsnew.aspx"
BSE_SMARTSEARCH_API = "https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w"
XBRL_FILE_PATTERN = re.compile(
    r"https?://.*?\.bseindia\.com.*?XBRLFILES.*?(?:\.xml|\.html|\.zip)",
    re.IGNORECASE,
)

BROADCAST_PERIODS = {
    "7": "Beyond 1 year",
    "6": "1 year",
    "5": "6 months",
    "4": "3 months",
    "3": "1 month",
}

# ==================== Models ====================
class GetXBRLRequest(BaseModel):
    company: str
    prefer: Optional[str] = Field("Any", description="Std|Con|Any")

    @validator("prefer")
    def validate_prefer(cls, v):
        if v and v.lower() not in ["std", "con", "any", "quarterly", "annual"]:
            raise ValueError("prefer must be Std, Con, Any, quarterly, or annual")
        return v or "Any"


class GetXBRLResponse(BaseModel):
    xbrl_url: Optional[str] = None
    period: Optional[str] = None
    report_type: Optional[str] = None  # Std or Con
    error: Optional[str] = None
    attempts: int = 0
    duration_ms: int = 0


class BatchGetXBRLRequest(BaseModel):
    companies: List[str] = Field(..., description="List of company names or numeric BSE scrip codes")
    prefer: Optional[str] = Field("Any", description="Std|Con|Any")

    @validator("prefer")
    def validate_prefer(cls, v):
        if v and v.lower() not in ["std", "con", "any"]:
            raise ValueError("prefer must be Std, Con, or Any")
        return v or "Any"


class BatchItemResult(BaseModel):
    company: str
    xbrl_url: Optional[str] = None
    period: Optional[str] = None
    report_type: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    duration_ms: int = 0


class BatchGetXBRLResponse(BaseModel):
    results: List[BatchItemResult]


# ==================== Helper Functions ====================
def looks_like_scrip(text: str) -> bool:
    """Check if text is a 4-6 digit BSE scrip code."""
    return bool(re.fullmatch(r"\d{4,6}", (text or "").strip()))


def strip_lower(s: str) -> str:
    """Normalize string."""
    return (s or "").strip().lower()


async def resolve_scrip_via_api(query: str) -> Optional[Dict[str, Any]]:
    """
    Use BSE SmartSearch API to resolve company name or partial name to scrip code.
    Returns first result with code, name, etc., or None.
    """
    import requests

    try:
        params = {"Type": "EQ", "text": query}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.bseindia.com",
            "Referer": BSE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
        }
        response = requests.get(
            BSE_SMARTSEARCH_API,
            params=params,
            headers=headers,
            timeout=10,
            verify=False,
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, list) and len(data) > 0:
            result = data[0]
            return {
                "code": result.get("Code") or result.get("code"),
                "name": result.get("Name") or result.get("name"),
                "symbol": result.get("Symbol") or result.get("symbol"),
            }
    except Exception as e:
        logger.warning(f"SmartSearch API failed for '{query}': {e}")

    return None


def extract_period_from_row(row_html: str) -> Optional[str]:
    """
    Extract period text like 'DQ2025-2026' (December Quarter FY2025-2026) from a table row.
    Pattern: [MSDJ]Q[0-9]{4}-[0-9]{4} or similar.
    """
    match = re.search(
        r"([MSDJ]Q\d{4}-\d{4}|[MSDJ]C\d{4}-\d{4}|[MSDJ]H\d{4}-\d{4})",
        row_html,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def extract_xbrl_links_from_html(
    html: str, prefer: str = "any"
) -> List[Tuple[str, Optional[str], str]]:
    """
    Extract all XBRL links from the results grid HTML.
    Returns list of (url, period, report_type) tuples where report_type is 'Std' or 'Con'.

    Strategy:
    1. Find table rows containing XBRL data
    2. Identify if row is for Standard or Consolidated
    3. Extract XBRL link and period
    """
    results = []
    prefer = strip_lower(prefer)

    try:
        # Split into table rows
        row_pattern = re.compile(r"<tr[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
        rows = row_pattern.findall(html)

        for row in rows:
            # Skip if no XBRL link in this row
            if not re.search(r"xbrl|ixbrl", row, re.IGNORECASE):
                continue

            # Determine if Standard or Consolidated
            report_type = "Std"
            if re.search(r"consolidated|con\s*xbrl", row, re.IGNORECASE):
                report_type = "Con"
            elif re.search(r"standard|std\s*xbrl", row, re.IGNORECASE):
                report_type = "Std"

            # Skip if user preference doesn't match
            if prefer in ["std", "con"] and strip_lower(report_type) != prefer:
                continue

            # Extract XBRL URL
            url_match = re.search(
                r'href\s*=\s*["\']([^"\']*(?:\.xml|\.html|\.zip|XBRLFILES)[^"\']*)["\']',
                row,
                re.IGNORECASE,
            )
            if not url_match:
                url_match = re.search(
                    r'href\s*=\s*["\']([^"\']*)["\']',
                    row,
                    re.IGNORECASE,
                )

            if url_match:
                url = url_match.group(1).strip()
                # Resolve relative URLs
                if url.startswith("/"):
                    url = "https://www.bseindia.com" + url
                elif url.startswith("../"):
                    url = "https://www.bseindia.com/corporates/" + url.replace("../", "")
                elif not url.startswith("http"):
                    url = "https://www.bseindia.com/corporates/" + url

                period = extract_period_from_row(row)
                results.append((url, period, report_type))

        # Sort by period (newest first)
        def period_key(item):
            period = item[1]
            if not period:
                return (9999, 9999)
            match = re.match(r"([MSDJ])Q(\d{4})-(\d{4})", period, re.IGNORECASE)
            if match:
                quarter_order = {"M": 4, "S": 2, "D": 3, "J": 1}
                q_num = quarter_order.get(match.group(1).upper(), 0)
                fy_end = int(match.group(3))
                return (-(fy_end), -q_num)
            return (9999, 9999)

        results.sort(key=period_key)

    except Exception as e:
        logger.error(f"Error extracting XBRL links from HTML: {e}")

    return results


def resolve_url(base_url: str, href: str) -> str:
    """Resolve relative URL to absolute."""
    href = (href or "").strip()
    if href.startswith("http") or href.startswith("https"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.bseindia.com" + href
    if href.startswith("../"):
        return "https://www.bseindia.com/corporates/" + href.replace("../", "")
    return base_url.rstrip("/") + "/" + href


# ==================== Main Crawl4AI Functions ====================
async def fetch_xbrl_with_crawl4ai(
    company: str, prefer: str = "any", max_attempts: int = 5
) -> Tuple[Optional[str], Optional[str], Optional[str], int, Optional[str]]:
    """
    Fetch XBRL link for a company using Crawl4AI.

    Returns:
        (xbrl_url, period, report_type, attempts_used, error_message)
    """
    start_time = datetime.now()
    attempts = 0
    scrip_code = None
    error_msg = None

    try:
        # Step 1: Resolve scrip code if company name provided
        if looks_like_scrip(company):
            scrip_code = company.strip()
            logger.info(f"Using numeric scrip code: {scrip_code}")
        else:
            logger.info(f"Resolving company name '{company}' via SmartSearch API...")
            api_result = await asyncio.to_thread(resolve_scrip_via_api, company)
            if api_result:
                scrip_code = api_result.get("code")
                logger.info(f"Resolved to scrip code: {scrip_code}")
            else:
                error_msg = f"Could not resolve company name '{company}'"
                return None, None, None, attempts, error_msg

        # Step 2: Try multiple broadcast periods
        browser_config = BrowserConfig(
            headless=True,
            viewport={"width": 1360, "height": 900},
            ignore_https_errors=True,
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            for attempt_num, period_code in enumerate(BROADCAST_PERIODS.keys(), start=1):
                attempts = attempt_num
                logger.info(
                    f"Attempt {attempt_num} for {company} (scrip: {scrip_code}) - "
                    f"Period: {BROADCAST_PERIODS.get(period_code)}"
                )

                try:
                    # Construct form submission with POST-like behavior
                    # Since BSE uses ASP.NET postback, we'll navigate to the initial page
                    # and Crawl4AI will execute JS to submit the form

                    js_code = f"""
                    (async () => {{
                        // Set scrip code in hidden fields
                        const codeField1 = document.getElementById('ContentPlaceHolder1_SmartSearch_hdnCode');
                        const codeField2 = document.getElementById('ContentPlaceHolder1_hf_scripcode');
                        if (codeField1) codeField1.value = '{scrip_code}';
                        if (codeField2) codeField2.value = '{scrip_code}';

                        // Set Period (Quarterly = 3)
                        const periodSelect = document.getElementById('ContentPlaceHolder1_periioddd');
                        if (periodSelect) periodSelect.value = '3';

                        // Set Broadcast Period
                        const broadcastSelect = document.getElementById('ContentPlaceHolder1_broadcastdd');
                        if (broadcastSelect) broadcastSelect.value = '{period_code}';

                        // Click submit
                        const submitBtn = document.getElementById('ContentPlaceHolder1_btnSubmit');
                        if (submitBtn) {{
                            submitBtn.click();
                            // Wait for navigation
                            await new Promise(r => setTimeout(r, 3000));
                        }}
                    }})();
                    """

                    # First load the page
                    result = await crawler.arun(
                        url=BSE_URL,
                        js_code=js_code,
                        cache_mode=CacheMode.NO_CACHE,
                        magic=True,
                    )

                    if result.html:
                        # Extract XBRL links from results
                        xbrl_links = extract_xbrl_links_from_html(result.html, prefer)

                        if xbrl_links:
                            url, period, report_type = xbrl_links[0]
                            logger.info(
                                f"Found XBRL link for {company}: {url} "
                                f"(Period: {period}, Type: {report_type})"
                            )
                            duration_ms = int(
                                (datetime.now() - start_time).total_seconds() * 1000
                            )
                            return url, period, report_type, attempts, None

                        logger.debug(f"No XBRL links found in HTML for period {period_code}")

                except Exception as e:
                    logger.warning(
                        f"Attempt {attempt_num} failed for {company} (scrip: {scrip_code}): {e}"
                    )
                    if attempt_num == 1:
                        error_msg = str(e)
                    continue

                # Small cooldown between attempts
                await asyncio.sleep(1)

        error_msg = error_msg or f"No XBRL found after {attempts} attempts"
        return None, None, None, attempts, error_msg

    except Exception as e:
        logger.error(f"Error fetching XBRL for {company}: {e}", exc_info=True)
        return None, None, None, attempts, str(e)


async def fetch_multiple_xbrl_links(
    companies: List[str], prefer: str = "any", max_parallel: int = 2
) -> List[Tuple[str, Optional[str], Optional[str], Optional[str], int, Optional[str]]]:
    """
    Fetch XBRL links for multiple companies in parallel (respecting max_parallel limit).

    Returns list of (company, url, period, report_type, attempts, error) tuples.
    """
    semaphore = asyncio.Semaphore(max_parallel)

    async def fetch_with_semaphore(company):
        async with semaphore:
            url, period, report_type, attempts, error = await fetch_xbrl_with_crawl4ai(
                company, prefer
            )
            return company, url, period, report_type, attempts, error

    results = await asyncio.gather(
        *[fetch_with_semaphore(company) for company in companies],
        return_exceptions=False,
    )
    return results


# ==================== Alternative: Direct extraction without form submission ====================
async def fetch_xbrl_direct(
    company: str, prefer: str = "any"
) -> Tuple[Optional[str], Optional[str], Optional[str], int, Optional[str]]:
    """
    Alternative method: Use Crawl4AI to directly search and extract from BSE SmartSearch.
    More lightweight than form submission.
    """
    start_time = datetime.now()
    attempts = 0

    try:
        # Resolve company to scrip code
        if looks_like_scrip(company):
            scrip_code = company.strip()
        else:
            api_result = await asyncio.to_thread(resolve_scrip_via_api, company)
            if not api_result:
                return None, None, None, 0, f"Could not resolve '{company}'"
            scrip_code = api_result.get("code")

        # Direct URL construction (if you know the pattern)
        # Most BSE pages allow direct query parameters or AJAX calls
        search_urls = [
            f"https://www.bseindia.com/corporates/Comp_Resultsnew.aspx?scripcode={scrip_code}",
            f"{BSE_URL}?code={scrip_code}",
        ]

        browser_config = BrowserConfig(headless=True)

        async with AsyncWebCrawler(config=browser_config) as crawler:
            for url in search_urls:
                attempts += 1
                try:
                    result = await crawler.arun(
                        url=url,
                        cache_mode=CacheMode.NO_CACHE,
                        magic=True,
                    )

                    if result.html:
                        xbrl_links = extract_xbrl_links_from_html(result.html, prefer)
                        if xbrl_links:
                            url_found, period, report_type = xbrl_links[0]
                            duration_ms = int(
                                (datetime.now() - start_time).total_seconds() * 1000
                            )
                            return url_found, period, report_type, attempts, None

                except Exception as e:
                    logger.debug(f"Attempt {attempts} with URL {url} failed: {e}")
                    continue

        return None, None, None, attempts, "No XBRL found after all attempts"

    except Exception as e:
        logger.error(f"Error in fetch_xbrl_direct for {company}: {e}")
        return None, None, None, attempts, str(e)


# ==================== FastAPI Integration (to be imported in routes) ====================
# These functions are meant to be used by FastAPI endpoints defined in a routes file
