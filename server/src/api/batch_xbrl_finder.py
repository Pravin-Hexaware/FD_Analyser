#!/usr/bin/env python3
"""
BSE Corporate Results -> Locate FIRST XBRL/iXBRL link for one or many companies.

Key traits:
- Numeric input (500510) -> inject exact scrip (no Smart Search mismatch).
- Name input -> server-side SmartSearch (CORS-free) first, then UI SmartSearch with retries.
- Robust extraction (direct href, popup, window.open hook, network sniff, same-tab navigation).
- Playwright navigation mirrors sample.py (comp_resultsnew search, filters, 20s post-submit wait).
- Broad date window uses BSE "Beyond last 1 year" on-page; `/api/ws/xbrl-fetch-all-std` still filters to past 5 FY in `xbrl_ws_route`.
- Never returns Comp_Resultsnew.aspx; returns None + error if no link after all attempts.

Endpoints:
- POST /get-xbrl-link
- POST /get-xbrl-links
"""

import asyncio
import re
import time
from pathlib import Path
from typing import Optional, List, Tuple

import requests
import urllib3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
# BSE corporate results (post-redesign); old Comp_Resultsnew.aspx flow is obsolete.
BSE_URL = "https://www.bseindia.com/corporates/comp_resultsnew"
BSE_HOME = "https://www.bseindia.com/"
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
MAX_ATTEMPTS_PER_COMPANY = 10        # full cycles
COOLDOWN_BETWEEN_ATTEMPTS_MS = 1500 # small pause to placate WAF
BROADCAST_PERIODS = ["7", "6", "5", "4", "3"]  # legacy ASP.NET values; sample.py flow uses ddl "Beyond last 1 year" only

# -------------------- Small helpers --------------------
def looks_like_scrip(text: str) -> bool:
    """True if text is a pure 4–6 digit BSE scrip code (e.g., 500325, 532540)."""
    return bool(re.fullmatch(r"\d{4,6}", (text or "").strip()))

def strip_lower(s: str) -> str:
    return (s or "").strip().lower()


def _is_bse_corporate_results_portal_url(url: str) -> bool:
    """True if URL is the BSE corporate results listing (old or new path), not an XBRL document."""
    low = strip_lower(url or "")
    if not low:
        return False
    if "xbrlfiles" in low:
        return False
    if low.endswith("comp_resultsnew.aspx"):
        return True
    return "/corporates/comp_resultsnew" in low


def _first_bse_scrip_in_text(text: str) -> Optional[str]:
    """Extract a 4–6 digit BSE scrip from a cell/label (no surrounding digits)."""
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    m = re.search(r"(?<!\d)(\d{4,6})(?!\d)", compact)
    return m.group(1) if m else None


def _row_belongs_to_scrip(code_cell: str, name_cell: str, expected: Optional[str]) -> bool:
    """If we know the target scrip, prefer rows that contain it (code column can be mis-indexed)."""
    if not expected or not re.fullmatch(r"\d{4,6}", expected.strip()):
        return True
    exp = expected.strip()
    combined = re.sub(r"\s+", "", f"{code_cell} {name_cell}")
    if exp in combined:
        return True
    for blob in (code_cell, name_cell):
        got = _first_bse_scrip_in_text(blob or "")
        if got == exp:
            return True
    return False


async def _grid_data_rows_locator(grid):
    """
    BSE asp:GridView often renders <table><tr> without <tbody>. sample.py uses table.locator('tr').
    Prefer tbody tr when present; otherwise all tr that have at least one td (skip thead-only rows).
    """
    tb = grid.locator("tbody tr")
    if await tb.count() > 0:
        return tb
    return grid.locator("tr:has(td)")

def save_raw_content(scrip_code: str, xbrl_type: str, period: str, raw_content: str, url: str) -> Optional[str]:
    """
    Save raw_content to file in /raw_content folder.
    Filename: {scripcode}-{std/con}-{period}.{html/xml}
    Returns the file path if successful, None otherwise.
    """
    try:
        # Create raw_content directory
        raw_content_dir = Path(__file__).resolve().parent.parent / "raw_content"
        raw_content_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine file extension from URL
        if url.lower().endswith('.xml'):
            ext = 'xml'
        else:
            ext = 'html'
        
        # Sanitize period for filename (replace special chars)
        safe_period = re.sub(r"[/\\:*?\"<>|]", "_", period)
        
        # Construct filename: {scripcode}-{std/con}-{period}.{ext}
        filename = f"{scrip_code}-{xbrl_type}-{safe_period}.{ext}"
        file_path = raw_content_dir / filename
        
        # Write content to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(raw_content)
        
        return str(file_path)
    except Exception as e:
        print(f"Error saving raw content for {scrip_code}: {e}")
        return None

async def fetch_xbrl_content(ctx, url: str) -> Optional[str]:
    """
    Fetch the content of an XBRL URL (HTML or XML) using requests with cookies from browser session.
    Returns the page source content or None if failed.
    """
    page = None
    try:
        page = await ctx.new_page()

        # Add anti-detection script
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        # First visit BSE corporate results page to establish session
        await page.goto(BSE_URL, timeout=10000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)  # Let session establish

        # Get cookies from the browser context
        cookies = await ctx.cookies()
        cookie_dict = {cookie['name']: cookie['value'] for cookie in cookies}

        # Use requests to fetch the XBRL URL with cookies and referer
        headers = {
            'User-Agent': USER_AGENT,
            'Referer': BSE_URL,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        response = requests.get(url, cookies=cookie_dict, headers=headers, timeout=30, verify=False)
        if response.status_code == 200:
            return response.text
        else:
            print(f"Failed to load XBRL URL {url}: status {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching XBRL content from {url}: {e}")
        return None
    finally:
        if page:
            try:
                await page.close()
            except Exception as e:
                print(f"Error closing page {page}: {e}")

# -------------------- Browser/context helpers --------------------
async def create_browser_and_context(p):
    """Minimal browser setup aligned with sample.py (viewport + UA only)."""
    launch_kw = dict(
        headless=True,
        args=[
            "--no-sandbox",
        ],
    )
    # BSE autocomplete often fails in bundled Chromium; real Chrome improves headless parity with sample.py.
    try:
        browser = await p.chromium.launch(channel="chrome", **launch_kw)
    except Exception:
        browser = await p.chromium.launch(**launch_kw)
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=USER_AGENT,
        ignore_https_errors=True,
    )
    return browser, ctx

async def prepare_page(ctx):
    """
    One page per company attempt. No SmartSearch route interception — sample.py relies on
    the browser's normal XHR/autocomplete; fulfilling PeerSmartSearch here can desync UI vs suggestions.
    """
    page = await ctx.new_page()

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

    def _record_request(req):
        try:
            if "XBRLFILES" in req.url.upper():
                if not hasattr(page, "__xbrl_requests__"):
                    page.__xbrl_requests__ = []
                page.__xbrl_requests__.append(req.url)
        except Exception as e:
            print("XBRLFILES: ", e)

    page.on("request", _record_request)
    page.__xbrl_requests__ = []

    return page

async def navigate_and_prepare(page):
    """
    Same sequence as sample.py: open comp_resultsnew, networkidle, small mouse gesture, cookies.
    """
    status = 0
    try:
        resp = await page.goto(BSE_URL, timeout=NAV_TIMEOUT)
        status = resp.status if resp else 0
    except Exception as e:
        print(e)

    if status == 403:
        try:
            await page.goto(BSE_HOME, timeout=NAV_TIMEOUT)
            await page.wait_for_timeout(1200)
            await page.goto(BSE_URL, timeout=NAV_TIMEOUT)
        except Exception as e:
            print(e)

    try:
        await page.wait_for_load_state("networkidle", timeout=60_000)
    except Exception as e:
        print("Warning: networkidle wait failed after navigation:", e)

    try:
        await page.mouse.move(300, 300)
        await page.mouse.click(300, 300)
    except Exception as e:
        print(e)

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
        except Exception as e:
            print(e)
            continue


async def apply_results_filters_new(page) -> None:
    """
    Matches sample.py: Result Period ALL, Industry ALL, Broadcast Beyond last 1 year (best-effort).
    """
    await page.wait_for_selector("#ContentPlaceHolder1_periioddd", timeout=10_000)
    await page.select_option("#ContentPlaceHolder1_periioddd", label="ALL")
    await page.wait_for_selector("#dllindustry", timeout=10_000)
    await page.select_option("#dllindustry", label="ALL")
    try:
        await page.wait_for_selector("#ddlBrodCastPeriod", timeout=10_000)
        await page.select_option("#ddlBrodCastPeriod", label="Beyond last 1 year")
    except Exception as e:
        print(f"Warning: failed to set broadcast period 'Beyond last 1 year': {e}")

async def fill_company_search_new(page, company: str) -> None:
    """
    Same UX as sample.py: #scripsearchtxtbx.last, char-by-char type(delay=150),
    visible li.quotemenu, pick row where match_key in text else first.
    For names, resolve PeerSmartSearch API to scrip when possible so typing matches BSE suggestions.
    """
    ctx = page.context
    needle = (company or "").strip()
    if not needle:
        raise RuntimeError("Empty company / scrip")

    if looks_like_scrip(needle):
        type_string = needle.strip()
        match_key = type_string
    else:
        resolved = await resolve_scrip_via_api(ctx, needle)
        if resolved:
            type_string = resolved.strip()
            match_key = type_string
        else:
            type_string = needle.strip()
            match_key = needle.strip()

    await page.wait_for_selector("#scripsearchtxtbx", timeout=10_000)
    input_box = page.locator("#scripsearchtxtbx").last
    await input_box.click()

    for ch in type_string:
        await input_box.type(str(ch), delay=150)

    try:
        await page.wait_for_selector("li.quotemenu", state="visible", timeout=10_000)
    except Exception as e:
        print(f"Warning: no suggestions visible for {needle}: {e}")

    items = page.locator("li.quotemenu")
    suggestions: List[str] = []
    if await items.count() > 0:
        suggestions = await items.all_inner_texts()

    mk = match_key.lower()
    selected = False
    for i, text in enumerate(suggestions):
        if mk in (text or "").lower():
            await items.nth(i).click()
            selected = True
            break

    if not selected:
        await page.wait_for_timeout(2000)
        items = page.locator("li.quotemenu")
        if await items.count() > 0:
            suggestions = await items.all_inner_texts()
            for i, text in enumerate(suggestions):
                if mk in (text or "").lower():
                    await items.nth(i).click()
                    selected = True
                    break

    if not selected:
        if await items.count() > 0:
            await items.nth(0).click()
            selected = True
        else:
            # sample.py does not throw here; headless often never shows li.quotemenu. Seed the same
            # hidden fields a real click would set so submit still filters to the intended scrip.
            code_to_bind = type_string.strip()
            if looks_like_scrip(needle) or looks_like_scrip(code_to_bind):
                try:
                    await page.evaluate(
                        """([code]) => {
                            code = String(code || '').trim();
                            const inputs = Array.from(document.querySelectorAll('#scripsearchtxtbx'));
                            const vis = inputs.length ? inputs[inputs.length - 1] : null;
                            if (vis) {
                                vis.value = code;
                                vis.dispatchEvent(new Event('input', { bubbles: true }));
                                vis.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                            const ids = [
                                'ContentPlaceHolder1_hf_scripcode',
                                'ContentPlaceHolder1_SmartSearch_hdnCode',
                                'hf_scripcode'
                            ];
                            for (const id of ids) {
                                const h = document.getElementById(id);
                                if (h) {
                                    h.value = code;
                                    h.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                            }
                        }""",
                        [code_to_bind],
                    )
                    await inject_scrip_code(page, code_to_bind, display_name=code_to_bind)
                except Exception as e:
                    print(f"Warning: failed to select first suggestion for {needle}: {e}")
            else:
                try:
                    await input_box.press("ArrowDown")
                    await input_box.press("Enter")
                except Exception as e:
                    print(f"Warning: failed to select first suggestion for {needle}: {e}")

    await page.wait_for_timeout(400)
    if looks_like_scrip(needle):
        try:
            await page.wait_for_function(
                """(code) => {
                    const want = String(code).trim();
                    const ids = [
                      'ContentPlaceHolder1_hf_scripcode',
                      'ContentPlaceHolder1_SmartSearch_hdnCode',
                      'hf_scripcode'
                    ];
                    for (const id of ids) {
                      const el = document.getElementById(id);
                      if (el && String(el.value || '').trim() === want) return true;
                    }
                    return false;
                }""",
                arg=needle.strip(),
                timeout=3_000,
            )
        except PWTimeoutError:
            pass


# -------------------- Field helpers --------------------
async def set_result_period(page):
    sel = "#ContentPlaceHolder1_periioddd"
    await page.wait_for_selector(sel, timeout=GRID_TIMEOUT)
    await page.select_option(sel, value="3")  # 3 = Quarterly

async def set_broadcast_period(page, value: str):
    """
    Broadcast / date window. Redesigned page uses #ddlBrodCastPeriod (labels + legacy values);
    fall back to old #ContentPlaceHolder1_broadcastdd if still present.
    """
    new_sel = "#ddlBrodCastPeriod"
    legacy_sel = "#ContentPlaceHolder1_broadcastdd"
    try:
        await page.wait_for_selector(new_sel, timeout=8_000)
        try:
            await page.select_option(new_sel, value=value)
            return
        except Exception as e:
            print(f"Warning: failed to set broadcast period {value} via value= on new selector: {e}")
        # Common label fallbacks when value= does not match redesigned options
        label_by_value = {
            "7": "Beyond last 1 year",
            "6": "Last 1 year",
            "5": "Last 6 months",
            "4": "Last 3 months",
            "3": "Last 1 month",
        }
        lbl = label_by_value.get(value)
        if lbl:
            try:
                await page.select_option(new_sel, label=lbl)
                return
            except Exception:
                for alt in (
                    "Beyond last 1 year",
                    "1 Year",
                    "6 Months",
                    "3 Months",
                    "1 Month",
                ):
                    try:
                        await page.select_option(new_sel, label=alt)
                        return
                    except Exception as e:
                        print(f"Warning: failed to set broadcast period {value} via label '{alt}': {e}")
                        continue
    except PWTimeoutError:
        pass
    try:
        await page.wait_for_selector(legacy_sel, timeout=5_000)
        await page.select_option(legacy_sel, value=value)
    except Exception as e:
        print(f"Warning: failed to set broadcast period {value}: {e}")


async def submit_form(page):
    """
    Matches sample.py: focus submit, snapshot gvData HTML, JS click submit,
    wait 20s for ASP.NET postback, then wait for grid change or presence, then networkidle.
    """
    await page.bring_to_front()

    submit_button = page.locator("#ContentPlaceHolder1_btnSubmit")
    await submit_button.wait_for(state="visible", timeout=10_000)
    await submit_button.scroll_into_view_if_needed()
    await submit_button.focus()

    old_table_html = None
    if await page.locator("#ContentPlaceHolder1_gvData").count() > 0:
        try:
            old_table_html = await page.locator("#ContentPlaceHolder1_gvData").first.inner_html()
        except Exception:
            old_table_html = None

    await page.evaluate(
        "() => { const b = document.querySelector('#ContentPlaceHolder1_btnSubmit'); if (b) b.click(); }"
    )

    await page.wait_for_timeout(20_000)
    try:
        if old_table_html is None:
            await page.wait_for_selector("#ContentPlaceHolder1_gvData", timeout=30_000)
        else:
            await page.wait_for_function(
                """([selector, oldHtml]) => {
                    const el = document.querySelector(selector);
                    return el && el.innerHTML !== oldHtml;
                }""",
                arg=["#ContentPlaceHolder1_gvData", old_table_html],
                timeout=30_000,
            )
    except PWTimeoutError:
        pass

    try:
        await page.wait_for_load_state("networkidle", timeout=60_000)
    except Exception as e:
        print("Warning: networkidle wait failed after submit:", e)

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


async def resolve_expected_bse_scrip(ctx, company: str) -> Optional[str]:
    """Canonical numeric scrip for this run (CSV scrip or PeerSmartSearch for names)."""
    s = (company or "").strip()
    if not s:
        return None
    if looks_like_scrip(s):
        return s
    return await resolve_scrip_via_api(ctx, s)


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
        except Exception as e:
            print("Error finding Smart Search input:", e)
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
        except Exception as e:
            print("Error clicking suggestion:", e)

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
            except Exception as e:
                print("Error clicking suggestion:", e)
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
async def pick_std_con_column_anchor(grid, prefer: str, first_data_row=None):
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
        if first_data_row is not None:
            first_row = first_data_row
        else:
            data_rows = await _grid_data_rows_locator(grid)
            first_row = data_rows.first
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
    except Exception as e:
        print(e)
    return None


async def get_first_xbrl_url(
    page,
    prefer: str = "any",
    expected_scrip: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Locate an XBRL link in the results grid. When ``expected_scrip`` is set (4–6 digit BSE code),
    only rows for that security are considered so we never return the first XBRL on a mixed/default grid.
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
        first, second,  fy_end = m.group(1).upper(), m.group(2).upper(), int(m.group(4))
        if second == "Q":
            return {"type": "quarterly", "fy_end": fy_end, "q_order": _Q_ORDER.get(first, 0)}
        if second == "C":
            return {"type": "annual", "fy_end": fy_end, "q_order": None}
        return {"type": "other", "fy_end": fy_end, "q_order": None}

    async def _resolve(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        if _is_bse_corporate_results_portal_url(url):
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
        except Exception as e:
            print(e)

        popup_url = None
        try:
            async with page.expect_popup() as pop_info:
                await a_locator.first.click()
            pop = await pop_info.value
            try:
                await pop.wait_for_load_state("domcontentloaded", timeout=POPUP_TIMEOUT)
            except Exception as e:
                print("Error clicking popup:", e)
            popup_url = pop.url
            try:
                await pop.close()
            except Exception as e:
                print("Error clicking anchor:", e)
        except Exception:
            # no popup -> click same tab
            try:
                await a_locator.first.click()
            except Exception as e:
                print("Error clicking anchor:", e)

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
        except Exception as e:
            print("Error getting window.open URL:", e)

        # same-tab navigation recognition
        try:
            await page.wait_for_url(re.compile(r".*XBRLFILES.*", re.I), timeout=1500)
            url = await _resolve(page.url)
            if url:
                return url
        except Exception as e:
            print("Error waiting for same-tab XBRLFILES navigation:", e)

        # network sniffer fallback
        try:
            candidates = [u for u in getattr(page, "__xbrl_requests__", []) if "XBRLFILES" in u.upper()]
            if candidates:
                url = await _resolve(candidates[-1])
                if url:
                    return url
        except Exception as e:
            print("Error getting XBRL files:", e)

        return None

    # ---------- 0) Locate grid ----------
    grid = None
    for sel in [
        '#ContentPlaceHolder1_gvData',
        'table:has(th:has-text("XBRL"))',
        'table:has-text("Std XBRL"), table:has-text("Con XBRL")',
    ]:
        try:
            await page.wait_for_selector(sel, timeout=GRID_TIMEOUT)
            grid = page.locator(sel).first
            break
        except PWTimeoutError:
            continue
    if grid is None:
        if await page.locator('text=/No\\s+Record\\s+Found/i').count():
            return None, None
        raise RuntimeError("Could not locate results table.")

    scoped_rows = None
    link_scope = grid
    if expected_scrip and re.fullmatch(r"\d{4,6}", expected_scrip.strip()):
        ex = expected_scrip.strip()
        data_rows = await _grid_data_rows_locator(grid)
        sr = data_rows.filter(has_text=re.compile(rf"(?<!\d){re.escape(ex)}(?!\d)"))
        if await sr.count() > 0:
            scoped_rows = sr
            link_scope = scoped_rows
        else:
            loose = data_rows.filter(has_text=ex)
            if await loose.count() > 0:
                scoped_rows = loose
                link_scope = loose

    first_data_row = scoped_rows.first if scoped_rows is not None else None

    # ---------- A) NEW BEHAVIOUR for prefer in {'quarterly','annual'} ----------
    prefer_mode = strip_lower(prefer)
    if prefer_mode in {"quarterly", "annual"}:
        # try to detect header indices (robust to column order)
        idx_code = 0
        idx_name = 1
        idx_industry = 2
        idx_period = 3
        idx_aud = 4
        idx_std = 5
        idx_con = 6
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
        except Exception as e:
            print(e)

        # collect all rows (GridView may omit tbody — match sample.py tr walk)
        rows_meta: List[dict] = []
        body_rows = await _grid_data_rows_locator(grid)
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
            except Exception as e:
                print(e)
                continue

            if not _row_belongs_to_scrip(code, name, expected_scrip):
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

        if rows_meta:
            # filter by requested type and pick "latest"
            if prefer_mode == "quarterly":
                candidates = [r for r in rows_meta if r["type"] == "quarterly"]
                latest = max(candidates, key=lambda r: (r["fy_end"], r["q_order"] or 0)) if candidates else None
            else:  # annual
                candidates = [r for r in rows_meta if r["type"] == "annual"]
                latest = max(candidates, key=lambda r: (r["fy_end"], 99)) if candidates else None

            if latest:
                # resolve Std first; if missing, Con
                url_final = await _resolve_from_anchor(latest["std_anchor"])
                picked_anchor = latest["std_anchor"]
                if not url_final:
                    url_final = await _resolve_from_anchor(latest["con_anchor"])
                    picked_anchor = latest["con_anchor"]

                if url_final:
                    period_text = latest["period"] or (await _extract_period_from_anchor(picked_anchor)) if picked_anchor else None
                    return url_final, period_text

        # Fall through to generic strategy if typed path found nothing

    if expected_scrip and re.fullmatch(r"\d{4,6}", (expected_scrip or "").strip()):
        ex = (expected_scrip or "").strip()
        dr = await _grid_data_rows_locator(grid)
        if await dr.count() > 0 and await dr.filter(has_text=ex).count() == 0:
            return None, None

    if (
        expected_scrip
        and re.fullmatch(r"\d{4,6}", (expected_scrip or "").strip())
        and scoped_rows is None
    ):
        data_rows = await _grid_data_rows_locator(grid)
        loose = data_rows.filter(has_text=expected_scrip.strip())
        if await loose.count() > 0:
            scoped_rows = loose
            link_scope = loose
            first_data_row = scoped_rows.first

    # ---------- B) ORIGINAL STRATEGY (std/con/any) ----------
    # 1) Prefer exact Std/Con column if requested
    candidate = None
    if prefer_mode in {"std", "con"}:
        c_anchor = await pick_std_con_column_anchor(grid, prefer_mode, first_data_row)
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
    direct = link_scope.locator(direct_sel).first
    if await direct.count():
        href = (await direct.get_attribute("href")) or ""
        if href and not href.lower().startswith("javascript:"):
            url = await _resolve(href)
            if url:
                return url, await _extract_period_from_anchor(direct)

    # 3) Candidate anchor selection if not already chosen
    if candidate is None:
        candidate = link_scope.locator('a[id*="lnkXML"]').first
        if not await candidate.count():
            candidate = link_scope.locator("a").filter(has_text=re.compile(r"\bXBRL\b", re.I)).first
        if not await candidate.count():
            return None, None

    # Clear previous window.open captures
    try:
        await page.evaluate("() => { try { window.__openedWindows__ = []; } catch(e){} }")
    except Exception as e:
        print("Error visiting page:", e)

    # 3A) Try popup first
    popup_url = None
    try:
        async with page.expect_popup() as pop_info:
            await candidate.click()
        pop = await pop_info.value
        try:
            await pop.wait_for_load_state("domcontentloaded", timeout=POPUP_TIMEOUT)
        except Exception as e:
            print("Error waiting for popup load:", e)
        popup_url = pop.url
        try:
            await pop.close()
        except Exception as e:
            print("Error clicking popup:", e)
    except Exception:
        # 3B) No popup; click normally (postback/same-tab)
        try:
            await candidate.click()
        except Exception as e:
            print("Error clicking candidate anchor:", e)

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
    except Exception as e:
        print("Error checking window.__openedWindows__:", e)

    # 6) same-tab navigation recognition: wait URL containing XBRLFILES
    try:
        await page.wait_for_url(re.compile(r".*XBRLFILES.*", re.I), timeout=1500)
        url = await _resolve(page.url)
        if url:
            return url, await _extract_period_from_anchor(candidate)
    except Exception as e:
        print("Error waiting for same-tab navigation:", e)

    # 7) Network sniffer fallback
    try:
        candidates = [u for u in getattr(page, "__xbrl_requests__", []) if "XBRLFILES" in u.upper()]
        if candidates:
            url = await _resolve(candidates[-1])
            if url:
                return url, await _extract_period_from_anchor(candidate)
    except Exception as e:
        print("Error visiting page:", e)

    # 8) Re-scan direct anchors after postback
    try:
        direct2 = link_scope.locator(direct_sel).first
        if await direct2.count():
            href2 = (await direct2.get_attribute("href")) or ""
            if href2 and not href2.lower().startswith("javascript:"):
                url = await _resolve(href2)
                if url:
                    return url, await _extract_period_from_anchor(direct2)
    except Exception as e:
        print("Error re-scanning direct anchors:", e)

    return None, None

# -------------------- Core per-company attempt loop --------------------
async def fetch_xbrl_for_company(ctx, company: str, prefer: str = "any") -> Tuple[Optional[str], Optional[str], int, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Returns (chosen_url, period, attempts_used, annual_url, annual_period, quarterly_url, quarterly_period).
    One BSE results load per attempt (sample.py-style submit); retries up to MAX_ATTEMPTS_PER_COMPANY.
    """
    attempts = 0

    # Outer attempt loop
    while attempts < MAX_ATTEMPTS_PER_COMPANY:
        attempts += 1
        page = await prepare_page(ctx)
        try:
            await navigate_and_prepare(page)

            expected_scrip = await resolve_expected_bse_scrip(ctx, company)

            await fill_company_search_new(page, company)
            await apply_results_filters_new(page)

            # Single submit + grid refresh (same as sample.py). Past multi-broadcast loop removed;
            # "Beyond last 1 year" is set in apply_results_filters_new. Five-year filtering stays in xbrl_ws_route.

            await submit_form(page)
            await wait_grid_ready(page)

            annual_url = None
            quarterly_url = None
            annual_period = None
            quarterly_period = None

            if prefer == "annual":
                annual_url, annual_period = await get_first_xbrl_url(
                    page, prefer="annual", expected_scrip=expected_scrip
                )

            elif prefer == "quarterly":
                quarterly_url, quarterly_period = await get_first_xbrl_url(
                    page, prefer="quarterly", expected_scrip=expected_scrip
                )

            else:
                annual_url, annual_period = await get_first_xbrl_url(
                    page, prefer="annual", expected_scrip=expected_scrip
                )
                quarterly_url, quarterly_period = await get_first_xbrl_url(
                    page, prefer="quarterly", expected_scrip=expected_scrip
                )
                if annual_url is None and quarterly_url is None:
                    fallback_url, fallback_period = await get_first_xbrl_url(
                        page, prefer=prefer, expected_scrip=expected_scrip
                    )
                    if fallback_url:
                        annual_url = fallback_url
                        annual_period = fallback_period

            # done searching for this attempt
            url = None
            period = None
            if prefer == "annual":
                url, period = annual_url, annual_period
            elif prefer == "quarterly":
                url, period = quarterly_url, quarterly_period
            else:
                url = annual_url or quarterly_url
                period = annual_period or quarterly_period

            # Guard: never return Comp_Results page
            if url:
                low_curr = strip_lower(page.url)
                low_url = strip_lower(url)
                if low_url == low_curr or _is_bse_corporate_results_portal_url(low_url):
                    url = None
                    period = None

            if url:
                try:
                    await page.close()
                except Exception as e:
                    print("Warning: failed to close page:", e)
                return url, period, attempts, annual_url, annual_period, quarterly_url, quarterly_period

            # no url; next attempt after cooldown
            await page.wait_for_timeout(COOLDOWN_BETWEEN_ATTEMPTS_MS)

        except Exception:
            try:
                await page.wait_for_timeout(COOLDOWN_BETWEEN_ATTEMPTS_MS)
            except Exception as e:
                print("Warning: failed to wait for cooldown:", e)
        finally:
            try:
                await page.close()
            except Exception as e:
                print("Warning: failed to close page:", e)

    # All attempts exhausted
    return None, None, attempts, None, None, None, None


async def get_all_std_xbrl_urls(ctx, company: str):
    """
    Async generator that yields (url, period, xbrl_type, raw_content, industry) for each Std and Con XBRL link found for the company.
    Yields as soon as each URL is resolved. One grid load per successful attempt (aligned with sample.py).
    """
    async def _resolve(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        if _is_bse_corporate_results_portal_url(url):
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
        except Exception as e:
            print("Error resolving url:", e)

        popup_url = None
        try:
            async with page.expect_popup() as pop_info:
                await a_locator.first.click()
            pop = await pop_info.value
            try:
                await pop.wait_for_load_state("domcontentloaded", timeout=POPUP_TIMEOUT)
            except Exception as e:
                print("Error clicking popup:", e)
            popup_url = pop.url
            try:
                await pop.close()
            except Exception as e:
                print("Error clicking anchor:", e)
        except Exception:
            # no popup -> click same tab
            try:
                await a_locator.first.click()
            except Exception as e:
                print("Error clicking anchor:", e)

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
        except Exception as e:
            print(e)

        # same-tab navigation recognition
        try:
            await page.wait_for_url(re.compile(r".*XBRLFILES.*", re.I), timeout=1500)
            url = await _resolve(page.url)
            if url:
                return url
        except Exception as e:
            print("Error waiting for same-tab navigation:", e)

        # network sniffer fallback
        try:
            candidates = [u for u in getattr(page, "__xbrl_requests__", []) if "XBRLFILES" in u.upper()]
            if candidates:
                url = await _resolve(candidates[-1])
                if url:
                    return url
        except Exception as e:
            print(e)

        return None

    attempts = 0

    yielded = set()  # to deduplicate by (period, report_type)

    # Outer attempt loop
    while attempts < MAX_ATTEMPTS_PER_COMPANY:
        attempts += 1
        page = await prepare_page(ctx)
        try:
            await navigate_and_prepare(page)

            expected_scrip = await resolve_expected_bse_scrip(ctx, company)

            await fill_company_search_new(page, company)
            await apply_results_filters_new(page)

            await submit_form(page)
            await wait_grid_ready(page)

            yielded_any = False

            grid = None
            for sel in [
                '#ContentPlaceHolder1_gvData',
                'table:has(th:has-text("XBRL"))',
                'table:has-text("Std XBRL"), table:has-text("Con XBRL")',
            ]:
                try:
                    await page.wait_for_selector(sel, timeout=GRID_TIMEOUT)
                    grid = page.locator(sel).first
                    break
                except PWTimeoutError:
                    continue
            if grid is not None:
                # detect header indices
                idx_code = 0
                idx_name = 1
                idx_period = 3
                idx_industry = 2
                idx_std = 5
                idx_con = 6
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
                    idx_period = _idx("period", idx_period)
                    idx_industry = _idx("industry", idx_industry)
                    idx_std = _idx("std xbrl", idx_std)
                    idx_con = _idx("con xbrl", idx_con)
                except Exception as e:
                    print("Error clicking anchor:", e)

                # collect all rows (GridView may omit <tbody>)
                body_rows = await _grid_data_rows_locator(grid)
                for r in range(await body_rows.count()):
                    tr = body_rows.nth(r)
                    tds = tr.locator("td")
                    try:
                        code_cell = (await tds.nth(idx_code).inner_text()).strip() if await tds.count() > idx_code else ""
                        name_cell = (
                            (await tds.nth(idx_name).inner_text()).strip()
                            if await tds.count() > idx_name
                            else ""
                        )
                        if not _row_belongs_to_scrip(code_cell, name_cell, expected_scrip):
                            continue

                        per = (await tds.nth(idx_period).inner_text()).strip()
                        ind = (await tds.nth(idx_industry).inner_text()).strip() if await tds.count() > idx_industry else ""
                        std_a = tds.nth(idx_std).locator("a").first if await tds.count() > idx_std else None
                        con_a = tds.nth(idx_con).locator("a").first if await tds.count() > idx_con else None


                        # Yield Std XBRL
                        if std_a and await std_a.count():
                            href = (await std_a.first.get_attribute("href")) or ""
                            if href and not href.lower().startswith("javascript:"):
                                url = await _resolve(href)
                            else:
                                url = await _resolve_from_anchor(std_a)

                            if url and (per, "std") not in yielded:
                                yielded.add((per, "std"))
                                yielded_any = True
                                # Fetch XBRL content and save to file
                                xbrl_content = await fetch_xbrl_content(ctx, url)
                                yield url, per, "std", xbrl_content, ind
                                await asyncio.sleep(2)  # Delay to avoid rate limiting

                        # Yield Con XBRL
                        if con_a and await con_a.count():
                            href = (await con_a.first.get_attribute("href")) or ""
                            if href and not href.lower().startswith("javascript:"):
                                url = await _resolve(href)
                            else:
                                url = await _resolve_from_anchor(con_a)

                            if url and (per, "con") not in yielded:
                                yielded.add((per, "con"))
                                yielded_any = True
                                xbrl_content = await fetch_xbrl_content(ctx, url)
                                yield url, per, "con", xbrl_content, ind
                                await asyncio.sleep(2)  # Delay to avoid rate limiting

                    except Exception as e:
                        print("Error clicking anchor:", e)
                        continue

            # If we yielded any, success
            if yielded_any:
                try:
                    await page.close()
                except Exception as e:
                    print("Error clicking anchor:", e)
                return

            # no links; next attempt after cooldown
            await page.wait_for_timeout(COOLDOWN_BETWEEN_ATTEMPTS_MS)

        except Exception:
            try:
                await page.wait_for_timeout(COOLDOWN_BETWEEN_ATTEMPTS_MS)
            except Exception as e:
                print("Warning: failed to wait for cooldown:", e)
        finally:
            try:
                await page.close()
            except Exception as e:
                print("Error closing page:", e)

    # All attempts exhausted, yield nothing


# -------------------- Public single-company runner --------------------
async def run_single(company: str, prefer: str = "any") -> GetXBRLResponse:
    started = time.perf_counter()
    async with async_playwright() as p:
        browser, ctx = await create_browser_and_context(p)
        try:
            url, period, attempts, annual_url, annual_period, quarterly_url, quarterly_period = await fetch_xbrl_for_company(ctx, company, prefer=prefer)
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
                    url, period, attempts_used, annual_url, annual_period, quarterly_url, quarterly_period = await fetch_xbrl_for_company(ctx, name, prefer=prefer)
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