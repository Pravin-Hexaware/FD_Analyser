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
    period: Optional[str] = None
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
    period: Optional[str] = None
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

async def _extract_period_from_anchor(anchor) -> Optional[str]:
    """Try to extract a period token (e.g. DQ2025-2026) from the same row as the given anchor."""
    if not anchor:
        return None
    try:
        row = anchor.locator("xpath=ancestor::tr").first

        # Prefer a canonical period token in the row (e.g. DQ2025-2026)
        row_text = (await row.inner_text() or "").strip()
        if row_text:
            m = re.search(r"\b(?:DQ|SQ|MQ|JQ|SH|DN)\d{4}-\d{4}\b", row_text)
            if m:
                return m.group(0)

        # Prefer the 3rd column (index 2) which often contains the period
        tds = row.locator("td")
        n = await tds.count()
        if n >= 3:
            td3 = tds.nth(2)
            txt = (await td3.inner_text() or "").strip()
            if txt:
                m = re.search(r"\b(?:DQ|SQ|MQ|JQ|SH|DN)\d{4}-\d{4}\b", txt)
                if m:
                    return m.group(0)
                return txt

        # Prefer a dedicated "period" column if present (e.g., <td class="tdcolumn">...)</td>).
        period_td = row.locator('td.tdcolumn').first
        if await period_td.count():
            txt = (await period_td.inner_text() or "").strip()
            if txt:
                m = re.search(r"\b(?:DQ|SQ|MQ|JQ|SH|DN)\d{4}-\d{4}\b", txt)
                if m:
                    return m.group(0)
                return txt

        # Fallback: look for the first cell containing a period-like token
        for i in range(n):
            td = tds.nth(i)
            if await td.locator("a").count():
                continue
            txt = (await td.inner_text() or "").strip()
            if not txt:
                continue
            m = re.search(r"\b(?:DQ|SQ|MQ|JQ|SH|DN)\d{4}-\d{4}\b", txt)
            if m:
                return m.group(0)

        # Last fallback: return first non-link cell (shorten if huge)
        for i in range(n):
            td = tds.nth(i)
            if await td.locator("a").count():
                continue
            txt = (await td.inner_text() or "").strip()
            if txt:
                return txt.strip().splitlines()[0]
    except Exception:
        pass
    return None


async def get_first_xbrl_url(page, prefer: str = "any") -> Tuple[Optional[str], Optional[str]]:
    """
    Exhaustive strategy (extended):
      If prefer in {'quarterly','annual'}:
        - Parse entire grid
        - Classify Period by 2nd char: 'Q' (quarter) or 'C' (cumulative/annual)
        - Pick latest by FY end (and quarter order for Q: J=Q1, S=Q2, D=Q3, M=Q4)
        - Resolve Std XBRL (prefer), else Con XBRL
      Else original flow:
        1) If Std/Con header recognized (prefer), pick exact cell anchor.
        2) Direct href anchors (.html/.xml/.zip or /XBRLFILES/).
        3) Click anchor -> expect popup (normal) -> read url.
        4) Post-click small wait -> read window.__openedWindows__.
        5) Scan network for /XBRLFILES/ requests.
        6) Same-tab navigation check -> wait_for_url(regex).
        7) Re-scan direct anchors.

    Returns (xbrl_url, period)
    """
    import re

    # ---------- small local helpers ----------
    _Q_ORDER = {"J": 1, "S": 2, "D": 3, "M": 4}
    _PERIOD_RE = re.compile(r"^\s*([MSDJ])([QCHN])(\d{4})-(\d{4})\s*$", re.IGNORECASE)

    def _classify_period(period_text: str):
        """
        Returns dict { 'type': 'quarterly'|'annual'|'other', 'fy_end': int|-1, 'q_order': int|None }
        """
        if not period_text:
            return {"type": "other", "fy_end": -1, "q_order": None}
        m = _PERIOD_RE.match(period_text)
        if not m:
            return {"type": "other", "fy_end": -1, "q_order": None}
        first, second, fy_start, fy_end = m.group(1).upper(), m.group(2).upper(), int(m.group(3)), int(m.group(4))
        if second == "Q":
            return {"type": "quarterly", "fy_end": fy_end, "q_order": _Q_ORDER.get(first, 0)}
        if second == "C":
            return {"type": "annual", "fy_end": fy_end, "q_order": None}
        return {"type": "other", "fy_end": fy_end, "q_order": None}

    async def _resolve(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        low = strip_lower(url)
        if low.endswith("comp_resultsnew.aspx"):
            return None
        if url.startswith("http"):
            return url
        return await resolve_absolute_url(page, url)

    async def _resolve_from_anchor(a_locator) -> Optional[str]:
        """
        Try to resolve URL from an <a> element using:
          - direct href
          - popup
          - same-tab
          - window.__openedWindows__
          - network sniffer
        Mirrors your original fallbacks.
        """
        if a_locator is None or not await a_locator.count():
            return None
        href = (await a_locator.first.get_attribute("href")) or ""
        if href and not href.lower().startswith("javascript:"):
            url = await _resolve(href)
            if url:
                return url

        # Clear previous window.open captures
        try:
            await page.evaluate("() => { try { window.__openedWindows__ = []; } catch(e){} }")
        except Exception:
            pass

        popup_url = None
        try:
            async with page.expect_popup() as pop_info:
                await a_locator.first.click()
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
            # no popup -> click same tab
            try:
                await a_locator.first.click()
            except Exception:
                pass

        # settle
        await page.wait_for_timeout(POST_CLICK_SETTLE_MS)

        if popup_url:
            url = await _resolve(popup_url)
            if url:
                return url

        # window.open captured?
        try:
            opened = await page.evaluate("() => (window.__openedWindows__ || []).slice(-1)[0] || ''")
            url = await _resolve(opened)
            if url:
                return url
        except Exception:
            pass

        # same-tab navigation recognition
        try:
            await page.wait_for_url(re.compile(r".*XBRLFILES.*", re.I), timeout=1500)
            url = await _resolve(page.url)
            if url:
                return url
        except Exception:
            pass

        # network sniffer fallback
        try:
            candidates = [u for u in getattr(page, "__xbrl_requests__", []) if "XBRLFILES" in u.upper()]
            if candidates:
                url = await _resolve(candidates[-1])
                if url:
                    return url
        except Exception:
            pass

        return None

    # ---------- 0) Locate grid ----------
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
        if await page.locator('text=/No\\s+Record\\s+Found/i').count():
            return None, None
        raise RuntimeError("Could not locate results table.")

    # ---------- A) NEW BEHAVIOUR for prefer in {'quarterly','annual'} ----------
    prefer_mode = strip_lower(prefer)
    if prefer_mode in {"quarterly", "annual"}:
        # try to detect header indices (robust to column order)
        idx_code = 0; idx_name = 1; idx_industry = 2; idx_period = 3; idx_aud = 4; idx_std = 5; idx_con = 6
        try:
            header = grid.locator("thead tr").first
            ths = header.locator("th")
            hmap = {}
            for i in range(await ths.count()):
                txt = (await ths.nth(i).inner_text()).strip().lower()
                hmap[txt] = i

            def _idx(needle: str, default: int) -> int:
                for k, v in hmap.items():
                    if needle in k:
                        return v
                return default

            idx_code = _idx("security code", idx_code)
            idx_name = _idx("security name", idx_name)
            idx_industry = _idx("industry", idx_industry)
            idx_period = _idx("period", idx_period)
            idx_aud = _idx("a/u", idx_aud)
            idx_std = _idx("std xbrl", idx_std)
            idx_con = _idx("con xbrl", idx_con)
        except Exception:
            pass

        # collect all rows
        rows_meta: List[dict] = []
        body_rows = grid.locator("tbody tr")
        for r in range(await body_rows.count()):
            tr = body_rows.nth(r)
            tds = tr.locator("td")
            try:
                code = (await tds.nth(idx_code).inner_text()).strip()
                name = (await tds.nth(idx_name).inner_text()).strip()
                ind  = (await tds.nth(idx_industry).inner_text()).strip()
                per  = (await tds.nth(idx_period).inner_text()).strip()
                aud  = (await tds.nth(idx_aud).inner_text()).strip() if await tds.count() > idx_aud else ""
                std_a = tds.nth(idx_std).locator("a").first if await tds.count() > idx_std else None
                con_a = tds.nth(idx_con).locator("a").first if await tds.count() > idx_con else None
            except Exception:
                continue

            meta = _classify_period(per)
            rows_meta.append({
                "security_code": code,
                "security_name": name,
                "industry": ind,
                "period": per,
                "audited": aud,
                "type": meta["type"],
                "fy_end": meta["fy_end"],
                "q_order": meta["q_order"],
                "std_anchor": std_a,
                "con_anchor": con_a,
            })

        if not rows_meta:
            return None, None

        # filter by requested type and pick "latest"
        if prefer_mode == "quarterly":
            candidates = [r for r in rows_meta if r["type"] == "quarterly"]
            latest = max(candidates, key=lambda r: (r["fy_end"], r["q_order"] or 0)) if candidates else None
        else:  # annual
            candidates = [r for r in rows_meta if r["type"] == "annual"]
            latest = max(candidates, key=lambda r: (r["fy_end"], 99)) if candidates else None

        if not latest:
            return None, None

        # resolve Std first; if missing, Con
        url_final = await _resolve_from_anchor(latest["std_anchor"])
        picked_anchor = latest["std_anchor"]
        if not url_final:
            url_final = await _resolve_from_anchor(latest["con_anchor"])
            picked_anchor = latest["con_anchor"]

        if url_final:
            # if we have the exact row, period is known; but keep anchor extractor fallback if needed
            period_text = latest["period"] or (await _extract_period_from_anchor(picked_anchor)) if picked_anchor else None
            return url_final, period_text

        # If still nothing, fall through to original generic strategy.
        # (This ensures we don't regress if the table acts weird.)

    # ---------- B) ORIGINAL STRATEGY (std/con/any) ----------
    # 1) Prefer exact Std/Con column if requested
    candidate = None
    if prefer_mode in {"std", "con"}:
        c_anchor = await pick_std_con_column_anchor(grid, prefer_mode)
        if c_anchor is not None and await c_anchor.count():
            href0 = (await c_anchor.first.get_attribute("href")) or ""
            if href0 and not href0.lower().startswith("javascript:"):
                url0 = await _resolve(href0)
                if url0:
                    return url0, await _extract_period_from_anchor(c_anchor.first)
            candidate = c_anchor.first

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
                return url, await _extract_period_from_anchor(direct)

    # 3) Candidate anchor selection if not already chosen
    if candidate is None:
        candidate = grid.locator('a[id*="lnkXML"]').first
        if not await candidate.count():
            candidate = grid.locator("a").filter(has_text=re.compile(r"\bXBRL\b", re.I)).first
        if not await candidate.count():
            return None, None

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
            return url, await _extract_period_from_anchor(candidate)

    # 5) window.open captured URL
    try:
        opened = await page.evaluate("() => (window.__openedWindows__ || []).slice(-1)[0] || ''")
        url = await _resolve(opened)
        if url:
            return url, await _extract_period_from_anchor(candidate)
    except Exception:
        pass

    # 6) same-tab navigation recognition: wait URL containing XBRLFILES
    try:
        await page.wait_for_url(re.compile(r".*XBRLFILES.*", re.I), timeout=1500)
        url = await _resolve(page.url)
        if url:
            return url, await _extract_period_from_anchor(candidate)
    except Exception:
        pass

    # 7) Network sniffer fallback
    try:
        candidates = [u for u in getattr(page, "__xbrl_requests__", []) if "XBRLFILES" in u.upper()]
        if candidates:
            url = await _resolve(candidates[-1])
            if url:
                return url, await _extract_period_from_anchor(candidate)
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
                    return url, await _extract_period_from_anchor(direct2)
    except Exception:
        pass

    return None, None

# -------------------- Core per-company attempt loop --------------------
async def fetch_xbrl_for_company(ctx, company: str, prefer: str = "any") -> Tuple[Optional[str], Optional[str], int, Optional[str], Optional[str]]:
    """
    Returns (chosen_url, period, attempts_used, annual_url, quarterly_url).
    Tries multiple broadcast periods and multiple attempts until found both annual and quarterly (or best fallback).
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
            annual_url = None
            quarterly_url = None
            annual_period = None
            quarterly_period = None

            for bp in BROADCAST_PERIODS:
                await set_broadcast_period(page, bp)
                await submit_form(page)
                await wait_grid_ready(page)

                url = None
                period = None

                if prefer == "annual":
                    annual_url, annual_period = await get_first_xbrl_url(page, prefer="annual")
                    url, period = annual_url, annual_period
                elif prefer == "quarterly":
                    quarterly_url, quarterly_period = await get_first_xbrl_url(page, prefer="quarterly")
                    url, period = quarterly_url, quarterly_period
                else:
                    if annual_url is None:
                        annual_url, annual_period = await get_first_xbrl_url(page, prefer="annual")
                    if quarterly_url is None:
                        quarterly_url, quarterly_period = await get_first_xbrl_url(page, prefer="quarterly")

                    fallback_url = None
                    fallback_period = None
                    if (annual_url is None and quarterly_url is None) and prefer not in {"quarterly", "annual"}:
                        fallback_url, fallback_period = await get_first_xbrl_url(page, prefer=prefer)

                    url = annual_url or quarterly_url or fallback_url
                    period = annual_period or quarterly_period or fallback_period

                # Guard: never return Comp_Results page
                if url:
                    low_curr = strip_lower(page.url)
                    low_url = strip_lower(url)
                    if low_url == low_curr or low_url.endswith("comp_resultsnew.aspx"):
                        url = None
                        period = None

                if url:
                    try:
                        await page.close()
                    except Exception:
                        pass
                    return url, period, attempts, annual_url, quarterly_url

            # no url; next attempt after cooldown
            await page.wait_for_timeout(COOLDOWN_BETWEEN_ATTEMPTS_MS)

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
    return None, None, attempts, None, None

# -------------------- Public single-company runner --------------------
async def run_single(company: str, prefer: str = "any") -> GetXBRLResponse:
    started = time.perf_counter()
    async with async_playwright() as p:
        browser, ctx = await create_browser_and_context(p)
        try:
            url, period, attempts, annual_url, quarterly_url = await fetch_xbrl_for_company(ctx, company, prefer=prefer)
            dur = int((time.perf_counter() - started) * 1000)
            if url:
                return GetXBRLResponse(
                    xbrl_url=url,
                    period=period,
                    error=None,
                    attempts=attempts,
                    duration_ms=dur,
                )
            return GetXBRLResponse(
                xbrl_url=None,
                period=None,
                error="No XBRL link found after exhaustive attempts.",
                attempts=attempts,
                duration_ms=dur,
            )
        finally:
            await ctx.close()
            await browser.close()

# -------------------- FastAPI endpoints --------------------
@router.post("/get-xbrl-link", response_model=GetXBRLResponse)
async def get_xbrl_link(request: GetXBRLRequest):
    """
    Get the first XBRL link for a single company/scrip.
    Body: {"company": "<Name or BSE scrip code>", "prefer": "Std|Con|Any"}
    """
    company = (request.company or "").strip()
    if not company:
        raise HTTPException(status_code=400, detail="company is required")
    return await run_single(company, prefer=request.prefer)

@router.post("/get-xbrl-links", response_model=BatchGetXBRLResponse)
async def get_xbrl_links(request: BatchGetXBRLRequest):
    """
    Batch: Get the first XBRL link for many companies/scrip codes.
    Body:
    {
      "companies": ["500325", "Tata Consultancy Services Ltd", "Hexaware Technologies Limited"],
      "prefer": "Any",
      "parallel": 2
    }
    """
    companies = [c.strip() for c in (request.companies or []) if c and c.strip()]
    if not companies:
        raise HTTPException(status_code=400, detail="companies must be a non-empty list")

    parallel = request.parallel or 2
    prefer   = request.prefer

    results: List[BatchItemResult] = []
    async with async_playwright() as p:
        browser, ctx = await create_browser_and_context(p)
        sem = asyncio.Semaphore(parallel)

        async def work(name: str) -> BatchItemResult:
            started = time.perf_counter()
            attempts_used = 0
            try:
                async with sem:
                    url, period, attempts_used, annual_url, quarterly_url = await fetch_xbrl_for_company(ctx, name, prefer=prefer)
                dur = int((time.perf_counter() - started) * 1000)
                if url:
                    return BatchItemResult(
                        company=name,
                        xbrl_url=url,
                        period=period,
                        error=None,
                        attempts=attempts_used,
                        duration_ms=dur,
                    )
                return BatchItemResult(
                    company=name,
                    xbrl_url=None,
                    period=None,
                    error="No XBRL link found after exhaustive attempts.",
                    attempts=attempts_used,
                    duration_ms=dur,
                )
            except Exception as e:
                dur = int((time.perf_counter() - started) * 1000)
                return BatchItemResult(company=name, xbrl_url=None, period=None, error=str(e), attempts=attempts_used, duration_ms=dur)

        try:
            tasks = [asyncio.create_task(work(c)) for c in companies]
            per = await asyncio.gather(*tasks)
            results.extend(per)
        finally:
            await ctx.close()
            await browser.close()

    return BatchGetXBRLResponse(results=results)