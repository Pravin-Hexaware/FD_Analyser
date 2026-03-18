#!/usr/bin/env python3
"""
BSE Corporate Results -> Locate FIRST XBRL/iXBRL link for one or many companies.

Key traits:
- Numeric input (500510) -> inject exact scrip (no Smart Search mismatch).
- Name input -> server-side SmartSearch (CORS-free) first, then UI SmartSearch with retries.
- Robust extraction (direct href, popup, window.open hook, network sniff, same-tab navigation).
- Cycles multiple Broadcast Periods (Beyond 1 year -> 1 year -> 6m -> 3m -> 1m) until found.
- Never returns Comp_Resultsnew.aspx; returns None + error if no link after all attempts.

Endpoints:
- POST /get-xbrl-link
- POST /get-xbrl-links
"""

import asyncio
import json
import re
import time
from typing import Optional, List, Dict, Any, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError, APIResponse

router = APIRouter()

# -------------------- Request/Response Models --------------------
class GetXBRLRequest(BaseModel):
    company: str  # company name OR numeric scrip code
    prefer: Optional[str] = Field("Any", description="Std|Con|Any")

    @validator("prefer")
    def _prefer_val(cls, v):
        v = (v or "Any").strip().lower()
        if v not in {"std", "con", "any"}:
            return "any"
        return v

class GetXBRLResponse(BaseModel):
    xbrl_url: Optional[str]
    error: Optional[str] = None
    attempts: int = 0
    duration_ms: int = 0

class BatchGetXBRLRequest(BaseModel):
    companies: List[str] = Field(..., description="List of company names or numeric BSE scrip codes")
    prefer: Optional[str] = Field("Any", description="Std|Con|Any")
    parallel: Optional[int] = Field(2, ge=1, le=6, description="Max parallel pages (default 2)")
    @validator("prefer")
    def _prefer_val(cls, v):
        v = (v or "Any").strip().lower()
        if v not in {"std", "con", "any"}:
            return "any"
        return v

class BatchItemResult(BaseModel):
    company: str
    xbrl_url: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    duration_ms: int = 0

class BatchGetXBRLResponse(BaseModel):
    results: List[BatchItemResult]

# -------------------- Constants & Config --------------------
BSE_URL = "https://www.bseindia.com/corporates/Comp_Resultsnew.aspx"
BSE_HOME = "https://www.bseindia.com/"
SMART_API_PART = "/BseIndiaAPI/api/PeerSmartSearch/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

# Master knobs (tune if needed)
NAV_TIMEOUT = 25_000                # generous for slow days
GRID_TIMEOUT = 18_000               # wait grid
XHR_TIMEOUT  = 12_000               # smart search fetch
CLICK_NAV_TIMEOUT = 8_000           # navigation after click
POPUP_TIMEOUT = 4_000               # popup wait
POST_CLICK_SETTLE_MS = 600          # small delay after click to let window.open fire
MAX_ATTEMPTS_PER_COMPANY = 6        # full cycles
COOLDOWN_BETWEEN_ATTEMPTS_MS = 1500 # small pause to placate WAF
BROADCAST_PERIODS = ["7", "6", "5", "4", "3"]  # 7: Beyond 1 year, 6: 1y, 5: 6m, 4: 3m, 3: 1m

# -------------------- Small helpers --------------------
def looks_like_scrip(text: str) -> bool:
    """True if text is a pure 4–6 digit BSE scrip code (e.g., 500325, 532540)."""
    return bool(re.fullmatch(r"\d{4,6}", (text or "").strip()))

def strip_lower(s: str) -> str:
    return (s or "").strip().lower()

# -------------------- Browser/context helpers --------------------
async def create_browser_and_context(p):
    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-infobars",
            "--window-size=1360,900",
            "--lang=en-US,en;q=0.9",
        ],
    )
    ctx = await browser.new_context(
        accept_downloads=False,
        user_agent=USER_AGENT,
        viewport={"width": 1360, "height": 900},
        locale="en-US",
        timezone_id="Asia/Kolkata",
        java_script_enabled=True,
        ignore_https_errors=True,
        extra_http_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Sec-CH-UA": '"Chromium";v="121", "Not(A:Brand";v="24", "Google Chrome";v="121"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Referer": BSE_HOME,
        },
    )
    await ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    """)
    return browser, ctx

async def prepare_page(ctx):
    page = await ctx.new_page()

    # Block heavy assets only; allow scripts/styles for delayed JS logic
    async def _router(route, req):
        try:
            if req.resource_type in ["image", "font", "stylesheet"]:
                return await route.abort()
        except Exception:
            pass
        return await route.continue_()

    await page.route("**/*", _router)

    # window.open hook to record target URL even if popup is blocked
    await page.add_init_script("""
        (function(){
          try {
            window.__openedWindows__ = [];
            const _oldOpen = window.open;
            window.open = function(u, n, f){
              try { if (u) window.__openedWindows__.push(String(u)); } catch(e){}
              return _oldOpen ? _oldOpen.apply(this, arguments) : null;
            };
          } catch(e){}
        })();
    """)

    # CORS-safe SmartSearch proxy via APIRequestContext
    async def smartsearch_proxy(route, request):
        if SMART_API_PART in request.url:
            try:
                resp: APIResponse = await ctx.request.get(
                    request.url,
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Origin": "https://www.bseindia.com",
                        "Referer": BSE_URL,
                        "X-Requested-With": "XMLHttpRequest",
                        "Sec-Fetch-Site": "same-site",
                        "Sec-Fetch-Mode": "cors",
                        "Sec-Fetch-Dest": "empty",
                    },
                    timeout=XHR_TIMEOUT
                )
                body = await resp.body()
                status = resp.status
                await route.fulfill(status=status, body=body, headers={"content-type": "application/json"})
                return
            except Exception:
                # let it pass through (may CORS-fail, but we tried)
                pass
        await route.continue_()

    await page.route("**/BseIndiaAPI/api/PeerSmartSearch/**", smartsearch_proxy)

    # Network sniffer: record any request to /XBRLFILES/
    def _record_request(req):
        try:
            if "XBRLFILES" in req.url.upper():
                if not hasattr(page, "__xbrl_requests__"):
                    page.__xbrl_requests__ = []
                page.__xbrl_requests__.append(req.url)
        except Exception:
            pass

    page.on("request", _record_request)
    page.__xbrl_requests__ = []

    return page

async def navigate_and_prepare(page):
    async def goto_with_status(url: str) -> int:
        resp = await page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        return resp.status if resp else 0

    status = 0
    try:
        status = await goto_with_status(BSE_URL)
    except Exception:
        pass

    if status == 403:
        try:
            await goto_with_status(BSE_HOME)
            await page.wait_for_timeout(1200)
            await goto_with_status(BSE_URL)
        except Exception:
            pass

    # Dismiss popups (best effort)
    for sel in [
        'button:has-text("Accept")',
        'button:has-text("I Agree")',
        'a:has-text("Accept")',
        'a:has-text("I Agree")',
        '#onetrust-accept-btn-handler',
        'button[id*="accept" i]',
        'div[role="dialog"] button:has-text("OK")',
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible():
                await loc.click()
                break
        except Exception:
            continue

# -------------------- Field helpers --------------------
async def set_result_period(page):
    sel = "#ContentPlaceHolder1_periioddd"
    await page.wait_for_selector(sel, timeout=GRID_TIMEOUT)
    await page.select_option(sel, value="3")  # 3 = Quarterly

async def set_broadcast_period(page, value: str):
    sel = "#ContentPlaceHolder1_broadcastdd"
    await page.wait_for_selector(sel, timeout=GRID_TIMEOUT)
    await page.select_option(sel, value=value)

async def submit_form(page):
    btn_sel = '#ContentPlaceHolder1_btnSubmit'
    await page.wait_for_selector(btn_sel, timeout=GRID_TIMEOUT)
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=CLICK_NAV_TIMEOUT):
        await page.click(btn_sel)

# -------------------- SmartSearch & Scrip handling --------------------
async def inject_scrip_code(page, scrip_code: str, display_name: Optional[str] = None) -> None:
    display = display_name or scrip_code
    await page.evaluate(
        """({ code, name }) => {
            const inpt = document.getElementById('ContentPlaceHolder1_SmartSearch_smartSearch');
            const h1 = document.getElementById('ContentPlaceHolder1_SmartSearch_hdnCode');
            const h2 = document.getElementById('ContentPlaceHolder1_hf_scripcode');
            const hn = document.getElementById('ContentPlaceHolder1_hf_scripname');
            if (inpt) inpt.value = name || '';
            if (h1) h1.value = code || '';
            if (h2) h2.value = code || '';
            if (hn) hn.value = name || '';
        }""",
        {"code": scrip_code.strip(), "name": display},
    )

async def resolve_scrip_via_api(ctx, query: str) -> Optional[str]:
    """Server-side SmartSearch (no CORS). Return a best scrip code or None."""
    # Use the same API that the page uses
    url = f"https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w?Type=EQ&text={query}"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.bseindia.com",
        "Referer": BSE_URL,
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        resp = await ctx.request.get(url, headers=headers, timeout=XHR_TIMEOUT)
        if resp.status != 200:
            return None
        data = await resp.json()
        items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        # Try to find a scrip code-looking field
        for it in items:
            # direct keys
            for k, v in it.items():
                if re.search(r"(scrip|security.*code|code)$", k, re.I):
                    vs = str(v).strip()
                    if re.fullmatch(r"\d{4,6}", vs):
                        return vs
            # scan numeric tokens
            blob = " ".join(map(lambda x: str(x or ""), it.values()))
            m = re.search(r"(?<!\d)(\d{4,6})(?!\d)", blob)
            if m:
                return m.group(1)
    except Exception:
        return None
    return None

async def smartsearch_fill(page, text: str) -> None:
    # Find the input
    input_sel = None
    for sel in [
        "#ContentPlaceHolder1_SmartSearch_smartSearch",
        'input[id*="SmartSearch"][id*="smartSearch"]',
        'input[placeholder*="Search" i]',
        'input[type="text"]',
    ]:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=2500)
            box = await loc.bounding_box()
            if box and box["width"] > 0 and box["height"] > 0:
                input_sel = sel
                break
        except Exception:
            continue
    if not input_sel:
        raise RuntimeError("Smart Search input not found; selectors may need refresh.")

    sugg_box = "#ajax_response_smart"
    await page.click(input_sel, timeout=1500)
    await page.click(input_sel, click_count=3, timeout=800)
    await page.keyboard.press("Delete")

    txt = text if len(text) <= 6 else text[:6]
    await page.type(input_sel, txt, delay=10)

    # wait for suggestions
    try:
        await page.wait_for_function(
            """(s) => {
                const b = document.querySelector(s);
                if (!b) return false;
                const r = b.getBoundingClientRect();
                if (r.width===0 || r.height===0) return false;
                return (b.innerText||'').trim().length>0;
            }""", arg=sugg_box, timeout=2000
        )
    except PWTimeoutError:
        # nudge
        try:
            await page.type(input_sel, " ", delay=10)
            await page.keyboard.press("Backspace")
        except Exception:
            pass

    # try click first viable suggestion
    clicked = False
    suggestions = page.locator(f"{sugg_box} a, {sugg_box} li, {sugg_box} div, {sugg_box} span")
    try:
        await suggestions.first.wait_for(timeout=1000)
        count = await suggestions.count()
        for i in range(count):
            el = suggestions.nth(i)
            try:
                visible = await el.is_visible()
                txt = (await el.inner_text() or "").strip()
                if not visible or not txt:
                    continue
                await el.click()
                clicked = True
                break
            except Exception:
                continue
    except PWTimeoutError:
        pass

    if not clicked:
        await page.focus(input_sel)
        await page.keyboard.press("ArrowDown")
        await page.keyboard.press("Enter")

# -------------------- Grid wait & sanity --------------------
async def wait_grid_ready(page) -> None:
    # Wait for grid and a second, so delayed anchors can materialize
    try:
        await page.wait_for_selector('#ContentPlaceHolder1_gvData', timeout=GRID_TIMEOUT)
        await page.wait_for_timeout(1000)  # allow delayed JS to inject anchors
    except PWTimeoutError:
        # Potentially "No Record Found"
        try:
            await page.get_by_text(re.compile(r"No\s+Record\s+Found", re.I)).first.wait_for(timeout=2000)
        except PWTimeoutError:
            await page.screenshot(path="debug_wait_for_results.png", full_page=True)
            raise RuntimeError("Grid not found and 'No Record Found' not visible.")

# -------------------- URL resolve helper --------------------
async def resolve_absolute_url(page, href: str) -> str:
    href = (href or "").strip()
    if href.startswith("http") or href.startswith("https"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.bseindia.com" + href
    if href.startswith("../"):
        return "https://www.bseindia.com/corporates/" + href.replace("../", "")
    base = page.url.rstrip("/")
    return base + "/" + href

# -------------------- Robust XBRL extraction --------------------
async def pick_std_con_column_anchor(grid, prefer: str):
    """Return a locator of the desired anchor if Std/Con header is identifiable; else None."""
    prefer = strip_lower(prefer)
    try:
        header_cells = grid.locator("thead tr th")
        n_th = await header_cells.count()
        target_col = None
        for i in range(n_th):
            txt = strip_lower(await header_cells.nth(i).inner_text() or "")
            if prefer == "std" and ("std" in txt and "xbrl" in txt):
                target_col = i
                break
            if prefer == "con" and ("con" in txt and "xbrl" in txt):
                target_col = i
                break
        if target_col is None:
            return None
        # First data row
        first_row = grid.locator("tbody tr").nth(0)
        return first_row.locator("td").nth(target_col).locator("a")
    except Exception:
        return None

async def get_first_xbrl_url(page, prefer: str = "any") -> Optional[str]:
    """
    Exhaustive strategy:
      1) If Std/Con header recognized (prefer), pick exact cell anchor.
      2) Direct href anchors (.html/.xml/.zip or /XBRLFILES/).
      3) Click anchor -> expect popup (normal) -> read url.
      4) Post-click small wait -> read window.__openedWindows__.
      5) Scan network for /XBRLFILES/ requests.
      6) Same-tab navigation check -> wait_for_url(regex).
      7) Re-scan direct anchors.
    """
    # 0) Locate grid
    grid = None
    for sel in [
        '#ContentPlaceHolder1_gvData',
        'table:has(th:has-text("XBRL"))',
        'table:has-text("Std XBRL"), table:has-text("Con XBRL")',
    ]:
        try:
            await page.wait_for_selector(sel, timeout=1500)
            grid = page.locator(sel).first
            break
        except PWTimeoutError:
            continue
    if grid is None:
        # maybe 'No Record Found'
        if await page.locator('text=/No\\s+Record\\s+Found/i').count():
            return None
        raise RuntimeError("Could not locate results table.")

    async def _resolve(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        low = strip_lower(url)
        if low.endswith("comp_resultsnew.aspx"):
            return None
        if url.startswith("http"):
            return url
        return await resolve_absolute_url(page, url)

    # 1) Prefer exact Std/Con column if requested
    prefer = strip_lower(prefer)
    if prefer in {"std", "con"}:
        c_anchor = await pick_std_con_column_anchor(grid, prefer)
        if c_anchor is not None and await c_anchor.count():
            href0 = (await c_anchor.first.get_attribute("href")) or ""
            if href0 and not href0.lower().startswith("javascript:"):
                url0 = await _resolve(href0)
                if url0:
                    return url0
            # else click this exact anchor and continue the general flow using candidate
            candidate = c_anchor.first
        else:
            candidate = None
    else:
        candidate = None

    # 2) Direct anchors (fastest)
    direct_sel = (
        'a[href*="XBRLFILES" i], '
        'a[href$=".xml" i], '
        'a[href$=".html" i], '
        'a[href$=".zip" i]'
    )
    direct = grid.locator(direct_sel).first
    if await direct.count():
        href = (await direct.get_attribute("href")) or ""
        if href and not href.lower().startswith("javascript:"):
            url = await _resolve(href)
            if url:
                return url

    # 3) Candidate anchor selection if not already chosen
    if candidate is None:
        candidate = grid.locator('a[id*="lnkXML"]').first
        if not await candidate.count():
            candidate = grid.locator("a").filter(has_text=re.compile(r"\bXBRL\b", re.I)).first
        if not await candidate.count():
            return None

    # Clear previous window.open captures
    try:
        await page.evaluate("() => { try { window.__openedWindows__ = []; } catch(e){} }")
    except Exception:
        pass

    # 3A) Try popup first
    popup_url = None
    try:
        async with page.expect_popup() as pop_info:
            await candidate.click()
        pop = await pop_info.value
        try:
            await pop.wait_for_load_state("domcontentloaded", timeout=POPUP_TIMEOUT)
        except Exception:
            pass
        popup_url = pop.url
        try:
            await pop.close()
        except Exception:
            pass
    except Exception:
        # 3B) No popup; click normally (postback/same-tab)
        try:
            await candidate.click()
        except Exception:
            pass

    # 4) small settle
    await page.wait_for_timeout(POST_CLICK_SETTLE_MS)

    # popup url?
    if popup_url:
        url = await _resolve(popup_url)
        if url:
            return url

    # 5) window.open captured URL
    try:
        opened = await page.evaluate("() => (window.__openedWindows__ || []).slice(-1)[0] || ''")
        url = await _resolve(opened)
        if url:
            return url
    except Exception:
        pass

    # 6) same-tab navigation recognition: wait URL containing XBRLFILES
    try:
        await page.wait_for_url(re.compile(r".*XBRLFILES.*", re.I), timeout=1500)
        url = await _resolve(page.url)
        if url:
            return url
    except Exception:
        pass

    # 7) Network sniffer fallback
    try:
        candidates = [u for u in getattr(page, "__xbrl_requests__", []) if "XBRLFILES" in u.upper()]
        if candidates:
            url = await _resolve(candidates[-1])
            if url:
                return url
    except Exception:
        pass

    # 8) Re-scan direct anchors after postback
    try:
        direct2 = grid.locator(direct_sel).first
        if await direct2.count():
            href2 = (await direct2.get_attribute("href")) or ""
            if href2 and not href2.lower().startswith("javascript:"):
                url = await _resolve(href2)
                if url:
                    return url
    except Exception:
        pass

    return None

async def get_latest_std_xbrl_urls(page, max_urls: int = 5) -> List[str]:
    """Return up to `max_urls` URLs from the Std XBRL column (latest first)."""

    # Reuse grid detection logic from get_first_xbrl_url
    grid = None
    for sel in [
        '#ContentPlaceHolder1_gvData',
        'table:has(th:has-text("XBRL"))',
        'table:has-text("Std XBRL"), table:has-text("Con XBRL")',
    ]:
        try:
            await page.wait_for_selector(sel, timeout=1500)
            grid = page.locator(sel).first
            break
        except PWTimeoutError:
            continue
    if grid is None:
        return []

    async def _resolve(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        low = strip_lower(url)
        if low.endswith("comp_resultsnew.aspx"):
            return None
        if url.startswith("http"):
            return url
        return await resolve_absolute_url(page, url)

    # Determine Std XBRL column index (prefer std, but fallback to any xbrl link)
    col_index = None
    try:
        header_cells = grid.locator("thead tr th")
        n_th = await header_cells.count()
        for i in range(n_th):
            txt = strip_lower(await header_cells.nth(i).inner_text() or "")
            if "std" in txt and "xbrl" in txt:
                col_index = i
                break
    except Exception:
        col_index = None

    urls: List[str] = []
    rows = grid.locator("tbody tr")
    row_count = await rows.count()

    # Helper to click an anchor and capture any resulting XBRL URL(s).
    async def _capture_from_click(anchor) -> Optional[str]:
        # Try direct href first
        href = (await anchor.get_attribute("href")) or ""
        if href and not href.lower().startswith("javascript:"):
            resolved = await _resolve(href)
            if resolved:
                return resolved

        # Reset captured sources
        try:
            await page.evaluate("() => { window.__openedWindows__ = []; }")
        except Exception:
            pass

        initial_url = page.url
        popup_url = None

        # Try popup click (if any)
        try:
            async with page.expect_popup() as pop_info:
                await anchor.click()
            pop = await pop_info.value
            try:
                await pop.wait_for_load_state("domcontentloaded", timeout=POPUP_TIMEOUT)
            except Exception:
                pass
            popup_url = pop.url
            try:
                await pop.close()
            except Exception:
                pass
        except Exception:
            # Fallback: click normally
            try:
                await anchor.click()
            except Exception:
                pass

        await page.wait_for_timeout(POST_CLICK_SETTLE_MS)

        # 1) Popup URL
        if popup_url:
            resolved = await _resolve(popup_url)
            if resolved:
                return resolved

        # 2) window.open captured
        try:
            opened = await page.evaluate("() => (window.__openedWindows__ || []).slice(-1)[0] || ''")
            resolved = await _resolve(opened)
            if resolved:
                return resolved
        except Exception:
            pass

        # 3) Network sniff
        try:
            candidates = [u for u in getattr(page, "__xbrl_requests__", []) if "XBRLFILES" in u.upper()]
            if candidates:
                resolved = await _resolve(candidates[-1])
                if resolved:
                    return resolved
        except Exception:
            pass

        # 4) Same-tab navigation (unlikely for Std XBRL, but safe)
        try:
            if "XBRLFILES" in page.url.upper():
                resolved = await _resolve(page.url)
                if resolved:
                    return resolved
        except Exception:
            pass

        # Try to return to previous results page if we navigated away
        try:
            if page.url != initial_url and "XBRLFILES" not in page.url.upper():
                await page.go_back()
                await page.wait_for_timeout(500)
        except Exception:
            pass

        return None

    # Iterate over rows, collecting URLs (stop when max_urls reached)
    for i in range(min(row_count, max_urls * 3)):
        if len(urls) >= max_urls:
            break
        try:
            row = rows.nth(i)
            if col_index is not None:
                cell = row.locator("td").nth(col_index)
                anchors = cell.locator("a")
            else:
                anchors = row.locator(
                    'a[href*="XBRLFILES" i], '
                    'a[href$=".xml" i], '
                    'a[href$=".html" i], '
                    'a[href$=".zip" i]'
                )

            if not await anchors.count():
                # Try fallback: elements with inline onclick that may trigger XBRL download
                anchors = cell.locator("*[onclick*='XBRL' i], *[onclick*='xbrl' i]")
                if not await anchors.count():
                    continue

            for j in range(await anchors.count()):
                if len(urls) >= max_urls:
                    break
                anchor = anchors.nth(j)
                resolved = await _capture_from_click(anchor)
                if resolved and resolved not in urls:
                    urls.append(resolved)
        except Exception:
            continue

    return urls[:max_urls]


# -------------------- Core per-company attempt loop --------------------
async def fetch_hist_xbrl_for_company(ctx, company: str, prefer: str = "any") -> Tuple[Optional[str], int]:
    """
    Returns (url, attempts_used). Tries multiple broadcast periods and multiple attempts until found.
    """
    attempts = 0
    start_t = time.perf_counter()

    # Outer attempt loop
    while attempts < MAX_ATTEMPTS_PER_COMPANY:
        attempts += 1
        page = await prepare_page(ctx)
        try:
            await navigate_and_prepare(page)

            # if numeric -> inject; else resolve scrip via API, else UI smart search
            if looks_like_scrip(company):
                await page.wait_for_selector("#ContentPlaceHolder1_SmartSearch_smartSearch", timeout=GRID_TIMEOUT)
                await inject_scrip_code(page, company)
            else:
                # try server-side API for deterministic scrip
                scrip = await resolve_scrip_via_api(ctx, company)
                if scrip:
                    await page.wait_for_selector("#ContentPlaceHolder1_SmartSearch_smartSearch", timeout=GRID_TIMEOUT)
                    await inject_scrip_code(page, scrip, display_name=company)
                else:
                    # UI SmartSearch
                    await smartsearch_fill(page, company)

            # Set result period
            await set_result_period(page)

            # try multiple broadcast periods (beyond 1y -> 1y -> 6m -> 3m -> 1m)
            for bp in BROADCAST_PERIODS:
                await set_broadcast_period(page, bp)
                await submit_form(page)
                await wait_grid_ready(page)

                url = await get_first_xbrl_url(page, prefer=prefer)
                # Guard: never return Comp_Results page
                if url:
                    low_curr = strip_lower(page.url)
                    low_url  = strip_lower(url)
                    if low_url == low_curr or low_url.endswith("comp_resultsnew.aspx"):
                        url = None
                if url:
                    # success
                    try:
                        await page.close()
                    except Exception:
                        pass
                    return url, attempts

            # no url; next attempt after cooldown
            await page.wait_for_timeout(COOLDOWN_BETWEEN_ATTEMPTS_MS)

        except Exception:
            try:
                await page.wait_for_timeout(COOLDOWN_BETWEEN_ATTEMPTS_MS)
            except Exception:
                pass
        finally:
            try:
                await page.close()
            except Exception:
                pass

    # All attempts exhausted
    return None, attempts


async def fetch_hist_xbrl_for_company_multi(
    ctx,
    company: str,
    prefer: str = "any",
    max_urls: int = 5,
) -> Tuple[List[str], int]:
    """Returns (urls, attempts_used). Tries multiple broadcast periods and multiple attempts until found.

    The returned list is (up to) `max_urls` results from the Std XBRL column for the latest filings.
    """
    attempts = 0

    # Outer attempt loop
    while attempts < MAX_ATTEMPTS_PER_COMPANY:
        attempts += 1
        page = await prepare_page(ctx)
        try:
            await navigate_and_prepare(page)

            # if numeric -> inject; else resolve scrip via API, else UI SmartSearch
            if looks_like_scrip(company):
                await page.wait_for_selector("#ContentPlaceHolder1_SmartSearch_smartSearch", timeout=GRID_TIMEOUT)
                await inject_scrip_code(page, company)
            else:
                # try server-side API for deterministic scrip
                scrip = await resolve_scrip_via_api(ctx, company)
                if scrip:
                    await page.wait_for_selector("#ContentPlaceHolder1_SmartSearch_smartSearch", timeout=GRID_TIMEOUT)
                    await inject_scrip_code(page, scrip, display_name=company)
                else:
                    # UI SmartSearch
                    await smartsearch_fill(page, company)

            # Set result period
            await set_result_period(page)

            # try multiple broadcast periods (beyond 1y -> 1y -> 6m -> 3m -> 1m)
            for bp in BROADCAST_PERIODS:
                await set_broadcast_period(page, bp)
                await submit_form(page)
                await wait_grid_ready(page)

                urls = await get_latest_std_xbrl_urls(page, max_urls=max_urls)
                urls = [u for u in urls if u and not strip_lower(u).endswith("comp_resultsnew.aspx")]
                if urls:
                    try:
                        await page.close()
                    except Exception:
                        pass
                    return urls, attempts

            # no urls; next attempt after cooldown
            await page.wait_for_timeout(COOLDOWN_BETWEEN_ATTEMPTS_MS)

        except Exception:
            try:
                await page.wait_for_timeout(COOLDOWN_BETWEEN_ATTEMPTS_MS)
            except Exception:
                pass
        finally:
            try:
                await page.close()
            except Exception:
                pass

    # All attempts exhausted
    return [], attempts


# -------------------- Public single-company runner --------------------
async def run_single(company: str, prefer: str = "any") -> GetXBRLResponse:
    started = time.perf_counter()
    async with async_playwright() as p:
        browser, ctx = await create_browser_and_context(p)
        try:
            url, attempts = await fetch_hist_xbrl_for_company(ctx, company, prefer=prefer)
            dur = int((time.perf_counter() - started) * 1000)
            if url:
                return GetXBRLResponse(xbrl_url=url, error=None, attempts=attempts, duration_ms=dur)
            return GetXBRLResponse(xbrl_url=None, error="No XBRL link found after exhaustive attempts.", attempts=attempts, duration_ms=dur)
        finally:
            await ctx.close()
            await browser.close()