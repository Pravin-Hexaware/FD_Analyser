#!/usr/bin/env python3
"""
BSE Corporate Results -> Locate FIRST XBRL/iXBRL link for one or many companies.
Option C: Keep Smart Search UX but fix CORS by routing the SmartSearch XHR via Playwright.
Fixes javascript:__doPostBack(...) by capturing popup instead of resolving the href.
Also: if input looks like a numeric BSE scrip code (4–6 digits), bypass Smart Search and inject scrip directly.

New:
- POST /get-xbrl-links: batch version that takes a list of companies/scrip codes and returns per-company results.
"""

import asyncio
import json
import re
import time
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError, APIResponse

router = APIRouter()

# ---------- Request/Response Models ----------
class GetXBRLRequest(BaseModel):
    company: str  # can be company name OR numeric scrip code

class GetXBRLResponse(BaseModel):
    xbrl_url: Optional[str]

class BatchGetXBRLRequest(BaseModel):
    companies: List[str] = Field(..., description="List of company names or numeric BSE scrip codes")
    parallel: Optional[int] = Field(2, ge=1, le=6, description="Max parallel pages (default 2)")

class BatchItemResult(BaseModel):
    company: str
    xbrl_url: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None

class BatchGetXBRLResponse(BaseModel):
    results: List[BatchItemResult]

# ---------- Constants ----------
BSE_URL = "https://www.bseindia.com/corporates/Comp_Resultsnew.aspx"
BSE_HOME = "https://www.bseindia.com/"
SMART_API_PART = "/BseIndiaAPI/api/PeerSmartSearch/"

# ---------- Utils ----------
def normspace(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def extract_window_open_url(onclick: Optional[str]) -> Optional[str]:
    if not onclick:
        return None
    m = re.search(r"""(?:window\.)?open\(\s*(['"])(.*?)\1""", onclick, flags=re.I)
    if m:
        return m.group(2)
    return None

def looks_like_scrip(text: str) -> bool:
    """True if text is a pure 4–6 digit scrip code (e.g., 500325, 532540)."""
    return bool(re.fullmatch(r"\d{4,6}", (text or "").strip()))

# ---------- Direct scrip injection ----------
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
    ok = await page.evaluate("""
        () => {
            const b = document.getElementById('ContentPlaceHolder1_hf_scripcode');
            return !!(b && (b.value || '').trim().length > 0);
        }
    """)
    if not ok:
        raise RuntimeError("Failed to inject scrip code into hidden fields.")

# ---------- Page actions ----------
async def _wait_suggestions_have_text(page, sugg_box: str, timeout_ms: int = 600) -> bool:
    try:
        await page.wait_for_function(
            """(s) => {
                const box = document.querySelector(s);
                if (!box) return false;
                const style = window.getComputedStyle(box);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = box.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return false;
                const txt = (box.innerText || '').trim();
                return txt.length > 0;
            }""",
            arg=sugg_box, timeout=timeout_ms
        )
        return True
    except PWTimeoutError:
        return False

async def _dispatch_input_keyup(page, selector: str) -> None:
    try:
        await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'a', code: 'KeyA', keyCode: 65 }));
            }""",
            selector
        )
    except Exception:
        pass

async def _find_company_input(page) -> Optional[str]:
    candidates = [
        "#ContentPlaceHolder1_SmartSearch_smartSearch",
        'input[id*="SmartSearch"][id*="smartSearch"]',
        'input[placeholder*="Search" i]',
        'input[type="text"]',
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=2500)
            box = await loc.bounding_box()
            if box and box["width"] > 0 and box["height"] > 0:
                return sel
        except Exception:
            continue
    return None

async def fill_company_smart_search_and_pick_first(page, company: str) -> None:
    """If numeric scrip -> inject, else use Smart Search suggestions."""
    if looks_like_scrip(company):
        await page.wait_for_selector("#ContentPlaceHolder1_SmartSearch_smartSearch", timeout=4000)
        await inject_scrip_code(page, company)
        return

    input_sel = await _find_company_input(page)
    if not input_sel:
        raise RuntimeError("Smart Search input not found; selectors may need refresh.")

    sugg_box = "#ajax_response_smart"
    await page.click(input_sel, timeout=1500)
    await page.click(input_sel, click_count=3, timeout=800)
    await page.keyboard.press("Delete")

    company_for_typing = company if len(company) <= 5 else company[:5]
    await page.type(input_sel, company_for_typing, delay=10)

    has_suggestions = await _wait_suggestions_have_text(page, sugg_box, timeout_ms=600)
    if not has_suggestions:
        try:
            await page.type(input_sel, " ", delay=10)
            await page.keyboard.press("Backspace")
        except Exception:
            pass
        await _dispatch_input_keyup(page, input_sel)
        has_suggestions = await _wait_suggestions_have_text(page, sugg_box, timeout_ms=600)
    if not has_suggestions:
        try:
            await page.focus(input_sel)
            await page.keyboard.press("ArrowDown")
            has_suggestions = await _wait_suggestions_have_text(page, sugg_box, timeout_ms=500)
        except Exception:
            pass

    clicked = False
    if has_suggestions:
        suggestions = page.locator(f"{sugg_box} a, {sugg_box} li, {sugg_box} div, {sugg_box} span")
        try:
            await suggestions.first.wait_for(timeout=900)
            count = await suggestions.count()
            for i in range(count):
                el = suggestions.nth(i)
                try:
                    txt = (await el.inner_text() or "").strip()
                    visible = await el.is_visible()
                    if not txt or not visible:
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

    # best-effort hidden scrip check
    try:
        await page.wait_for_function(
            """() => {
                const a = document.getElementById('ContentPlaceHolder1_SmartSearch_hdnCode');
                const b = document.getElementById('ContentPlaceHolder1_hf_scripcode');
                const av = (a && a.value || '').trim();
                const bv = (b && b.value || '').trim();
                return (av.length > 0) || (bv.length > 0);
            }""",
            timeout=1600
        )
    except PWTimeoutError:
        pass

async def set_result_period_quarterly(page) -> None:
    sel = "#ContentPlaceHolder1_periioddd"
    await page.wait_for_selector(sel, timeout=1200)
    await page.select_option(sel, value="3")

async def set_broadcast_period_beyond_1yr(page) -> None:
    sel = "#ContentPlaceHolder1_broadcastdd"
    await page.wait_for_selector(sel, timeout=1200)
    await page.select_option(sel, value="7")

async def click_submit(page) -> None:
    btn_sel = '#ContentPlaceHolder1_btnSubmit'
    await page.wait_for_selector(btn_sel, timeout=1200)
    async with page.expect_navigation(wait_until="domcontentloaded"):
        await page.click(btn_sel)

async def wait_for_results(page) -> None:
    try:
        await page.wait_for_selector('#ContentPlaceHolder1_gvData', timeout=4000)
        return
    except PWTimeoutError:
        try:
            await page.get_by_text(re.compile(r"No\s+Record\s+Found", re.I)).first.wait_for(timeout=1200)
            return
        except PWTimeoutError:
            await page.screenshot(path="debug_wait_for_results.png", full_page=True)
            raise RuntimeError("Neither the results grid nor 'No Record Found' appeared.")

async def resolve_absolute_url(page, href: str) -> str:
    href = href or ""
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.bseindia.com" + href
    if href.startswith("../"):
        return "https://www.bseindia.com/corporates/" + href.replace("../", "")
    base = page.url.rstrip("/")
    return base + "/" + href

# ---------- FAST & CORRECT XBRL extraction ----------
async def get_first_xbrl_url(page) -> Optional[str]:
    # find grid
    grid_candidates = [
        '#ContentPlaceHolder1_gvData',
        'table:has(th:has-text("XBRL"))',
        'table:has-text("Std XBRL"), table:has-text("Con XBRL")',
    ]
    grid = None
    for sel in grid_candidates:
        try:
            await page.wait_for_selector(sel, timeout=800)
            grid = page.locator(sel).first
            break
        except PWTimeoutError:
            continue
    if grid is None:
        if await page.locator('text=/No\\s+Record\\s+Found/i').count():
            return None
        raise RuntimeError("Could not locate results table. Inspect DOM and update selectors.")

    # A) direct anchors (no click)
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
            return await resolve_absolute_url(page, href)

    # B) lnkXML / label-based
    candidate = grid.locator('a[id*="lnkXML"]').first
    if not await candidate.count():
        candidate = grid.locator("a").filter(has_text=re.compile(r"\bXBRL\b", re.I)).first

    if await candidate.count():
        href = ((await candidate.get_attribute("href")) or "").strip()
        onclick = ((await candidate.get_attribute("onclick")) or "").strip()

        if href and not href.lower().startswith("javascript:"):
            return await resolve_absolute_url(page, href)

        open_url = extract_window_open_url(onclick)
        if open_url:
            return await resolve_absolute_url(page, open_url)

        # javascript:__doPostBack(...) -> click & capture popup
        try:
            async with page.expect_popup() as pop_info:
                await candidate.click()
            pop = await pop_info.value
            try:
                await pop.wait_for_load_state("domcontentloaded", timeout=1200)
            except Exception:
                pass
            url = pop.url
            try:
                await pop.close()
            except Exception:
                pass
            if url and not url.startswith(("about:", "javascript:")):
                return url
        except Exception:
            try:
                await candidate.click()
                direct2 = grid.locator(direct_sel).first
                if await direct2.count():
                    href2 = (await direct2.get_attribute("href")) or ""
                    if href2 and not href2.lower().startswith("javascript:"):
                        return await resolve_absolute_url(page, href2)
            except Exception:
                pass

    return None

# ---------- Browser/context helpers ----------
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
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
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

    # Block heavy resources (keep HTML + XHR only)
    await page.route("**/*", lambda route, req:
        route.abort() if req.resource_type in ["image", "font", "media"] else route.continue_()
    )

    # Route SmartSearch via APIRequestContext to bypass CORS
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
                )
                body = await resp.body()
                status = resp.status
                await route.fulfill(status=status, body=body, headers={"content-type": "application/json"})
                return
            except Exception:
                pass
        await route.continue_()

    await page.route("**/BseIndiaAPI/api/PeerSmartSearch/**", smartsearch_proxy)
    return page

async def navigate_and_dismiss(page):
    async def goto_with_status(url: str, timeout_ms: int = 8000) -> int:
        resp = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        return resp.status if resp else 0

    status = 0
    try:
        status = await goto_with_status(BSE_URL, 8000)
    except Exception:
        pass

    if status == 403:
        try:
            await goto_with_status(BSE_HOME, 8000)
            await page.wait_for_timeout(1000)
            await goto_with_status(BSE_URL, 8000)
        except Exception:
            pass

    # Dismiss cookie/consent popups (best effort)
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

# ---------- Single-company using shared context ----------
async def fetch_xbrl_for_company(ctx, company: str) -> Optional[str]:
    page = await prepare_page(ctx)
    try:
        await navigate_and_dismiss(page)
        await fill_company_smart_search_and_pick_first(page, company)
        await set_result_period_quarterly(page)
        await set_broadcast_period_beyond_1yr(page)
        await click_submit(page)
        await wait_for_results(page)
        url = await get_first_xbrl_url(page)
        return url
    finally:
        try:
            await page.close()
        except Exception:
            pass

# ---------- Public single-company run (kept for compatibility) ----------
async def run(company: str) -> Optional[str]:
    async with async_playwright() as p:
        browser, ctx = await create_browser_and_context(p)
        try:
            url = await fetch_xbrl_for_company(ctx, company)
            return url
        finally:
            await ctx.close()
            await browser.close()

# ---------- FastAPI Endpoints ----------
@router.post("/get-xbrl-link", response_model=GetXBRLResponse)
async def get_xbrl_link(request: GetXBRLRequest):
    """
    Get the first XBRL link for a single company/scrip.
    Body: {"company": "<Name or BSE scrip code>"}
    """
    try:
        company = (request.company or "").strip()
        if not company:
            raise HTTPException(status_code=400, detail="company is required")
        xbrl_url = await run(company)
        return GetXBRLResponse(xbrl_url=xbrl_url)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/get-xbrl-links", response_model=BatchGetXBRLResponse)
async def get_xbrl_links(request: BatchGetXBRLRequest):
    """
    Batch: Get the first XBRL link for many companies/scrip codes.
    Body:
    {
      "companies": ["500325", "Tata Consultancy Services Ltd", "Hexaware Technologies Limited"],
      "parallel": 2
    }
    """
    companies = [c.strip() for c in (request.companies or []) if c and c.strip()]
    if not companies:
        raise HTTPException(status_code=400, detail="companies must be a non-empty list")

    parallel = request.parallel or 2
    results: List[BatchItemResult] = []

    async with async_playwright() as p:
        browser, ctx = await create_browser_and_context(p)
        sem = asyncio.Semaphore(parallel)

        async def work_one(name: str) -> BatchItemResult:
            started = time.perf_counter()
            try:
                async with sem:
                    url = await fetch_xbrl_for_company(ctx, name)
                dur = int((time.perf_counter() - started) * 1000)
                if url:
                    return BatchItemResult(company=name, xbrl_url=url, error=None, duration_ms=dur)
                return BatchItemResult(company=name, xbrl_url=None, error="No XBRL link found", duration_ms=dur)
            except Exception as e:
                dur = int((time.perf_counter() - started) * 1000)
                return BatchItemResult(company=name, xbrl_url=None, error=str(e), duration_ms=dur)

        try:
            tasks = [asyncio.create_task(work_one(c)) for c in companies]
            results = await asyncio.gather(*tasks)
        finally:
            await ctx.close()
            await browser.close()

    return BatchGetXBRLResponse(results=results)