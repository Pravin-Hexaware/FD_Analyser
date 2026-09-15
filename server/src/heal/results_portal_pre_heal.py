from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, List, Any
from enum import Enum
from playwright.async_api import TimeoutError as PWTimeoutError

from automation.portal_contract import PortalLocators
from automation.unique_locator import first_unique_visible_locator
from services.logging_service import logging_service


class PlaywrightHealRequired(RuntimeError):
    """Raised when the portal UI appears to have drifted and needs healing."""

    def __init__(self, reason: str, phase: Optional[str] = None):
        super().__init__(reason)
        self.reason = reason
        self.phase = phase

class SiteHealth(str, Enum):
    """Landing-page grid status before search (BSE downtime vs UI drift)."""

    UP = "up"
    DOWN = "down"
    GRID_MISSING = "grid_missing"


def site_health_value(health: Any) -> str:
    """Normalize SiteHealth / str after portal rebind (enum class identity may change)."""
    if health is None:
        return ""
    return str(getattr(health, "value", health)).strip().lower()


def is_site_down(health: Any) -> bool:
    return site_health_value(health) == SiteHealth.DOWN.value


def is_site_up(health: Any) -> bool:
    return site_health_value(health) == SiteHealth.UP.value


WEBSITE_DOWN_DETAIL = (
    "The website is currently not working. Please try again later."
)

_NO_RECORDS_RE = re.compile(r"No\s+Records?\s+Found", re.I)




@dataclass
class ResultsPortal:
    TARGET_URL: str = "https://www.bseindia.com/corporates/comp_resultsnew"
    HOME_URL: str = "https://www.bseindia.com/"
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
    NAV_TIMEOUT: int = 25_000
    GRID_TIMEOUT: int = 18_000
    XHR_TIMEOUT: int = 12_000
    POPUP_TIMEOUT: int = 4_000
    POST_CLICK_SETTLE_MS: int = 600
    locators: PortalLocators = PortalLocators(
        search_input="#scripsearchtxtbx",
        suggestion_items="li.quotemenu",
        result_period_dropdown="#ContentPlaceHolder1_periioddd",
        industry_dropdown="#dllindustry",
        broadcast_dropdown="#ddlBrodCastPeriod",
        submit_button="#ContentPlaceHolder1_btnSubmit",
        results_grid="#ContentPlaceHolder1_gvData",
    )

    def _log_phase(self, phase: str, status: str, **details: Any) -> None:
        logging_service.log_phase(phase, status, target_url=self.TARGET_URL, **details)

    def _log_field(
        self,
        field: str,
        status: str,
        *,
        action: str = "interact",
        selector: str = "",
        value: Any = None,
        error: Any = None,
        **details: Any,
    ) -> None:
        """Per dropdown/input/button pass/fail — visible in SessionLog + AgentSession + runtime FIELD lines."""
        logging_service.log_field(
            field,
            status,
            action=action,
            selector=selector or "",
            value=value,
            error=error,
            target_url=self.TARGET_URL,
            **details,
        )


    def _raise_heal(self, reason: str, **details: Any) -> None:
        phase = details.get("phase")
        field = details.get("field")
        if field:
            self._log_field(
                str(field),
                "fail",
                action=str(details.get("action") or "interact"),
                selector=str(details.get("selector") or ""),
                value=details.get("value"),
                error=reason,
                phase_hint=phase,
            )

        if phase:
            fail_details = {k: v for k, v in details.items() if k != "phase"}
            if "error" not in fail_details:
                fail_details["error"] = reason
            self._log_phase(phase, "failed", reason=reason, **fail_details)
        logging_service.log_heal_trigger(reason, target_url=self.TARGET_URL, **details)
        raise PlaywrightHealRequired(reason, phase=phase)

    async def prepare_page(self, ctx):
        page = await ctx.new_page()
        await page.add_init_script(
            """
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
            """
        )

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

    async def navigate(self, page) -> None:
        self._log_phase("xbrl_navigate", "started")
        status = 0
        try:
            resp = await page.goto(self.TARGET_URL, timeout=self.NAV_TIMEOUT)
            status = resp.status if resp else 0
        except Exception as exc:
            self._log_phase("xbrl_navigate", "failed", error=str(exc))
            raise

        if status == 403:
            try:
                await page.goto(self.HOME_URL, timeout=self.NAV_TIMEOUT)
                await page.wait_for_timeout(1200)
                await page.goto(self.TARGET_URL, timeout=self.NAV_TIMEOUT)
            except Exception as exc:
                self._log_phase("xbrl_navigate", "failed", error=str(exc), response_status=status)
                raise

        try:
            await page.wait_for_load_state("networkidle", timeout=60_000)
        except Exception as exc:
            self._log_phase("xbrl_navigate", "warning", warning="networkidle_wait_failed", error=str(exc))

        try:
            await page.mouse.move(300, 300)
            await page.mouse.click(300, 300)
        except Exception:
            pass

        for sel in [
            'button:has-text("Accept")',
            'button:has-text("I Agree")',
            'a:has-text("Accept")',
            'a:has-text("I Agree")',
            "#onetrust-accept-btn-handler",
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
        self._log_phase("xbrl_navigate", "success")


    async def check_landing_site_health(self, page) -> SiteHealth:
        """
        Inspect the DEFAULT landing results grid with NO company search applied.

        - UP: grid present with at least one meaningful data row → site is serving data
        - UP: grid has at least one meaningful data row
        - GRID_MISSING: grid is absent or has no default rows → continue to search/heal
        - DOWN is reserved for an explicit transport/outage check, not an empty query
        """
        self._log_phase("site_health", "started")
        grid_sel = self.locators.results_grid
        try:
            try:
                await page.wait_for_selector(grid_sel, timeout=min(self.GRID_TIMEOUT, 12_000))
            except PWTimeoutError:
                try:
                    if await page.get_by_text(_NO_RECORDS_RE).first.is_visible(timeout=1500):
                        self._log_phase(
                            "site_health",
                            "success",
                            health=SiteHealth.GRID_MISSING.value,
                            detail="no_records_banner_without_grid",
                        )
                        return SiteHealth.GRID_MISSING
                except Exception:
                    pass
                self._log_phase(
                    "site_health",
                    "success",
                    health=SiteHealth.GRID_MISSING.value,
                    detail="results_grid_selector_missing",
                )
                return SiteHealth.GRID_MISSING

            grid = page.locator(grid_sel).first
            try:
                grid_text = (await grid.inner_text(timeout=3000)) or ""
            except Exception:
                grid_text = ""

            if _NO_RECORDS_RE.search(grid_text):
                self._log_phase(
                    "site_health",
                    "success",
                    health=SiteHealth.GRID_MISSING.value,
                    detail="grid_shows_no_records",
                )
                return SiteHealth.GRID_MISSING

            try:
                if await page.get_by_text(_NO_RECORDS_RE).first.is_visible(timeout=800):
                    self._log_phase(
                        "site_health",
                        "success",
                        health=SiteHealth.GRID_MISSING.value,
                        detail="page_shows_no_records",
                    )
                    return SiteHealth.GRID_MISSING
            except Exception:
                pass

            rows = await self.data_rows(grid)
            try:
                row_count = await rows.count()
            except Exception:
                row_count = 0

            meaningful = 0
            for i in range(min(row_count, 25)):
                try:
                    row = rows.nth(i)
                    cells = row.locator("td")
                    cell_count = await cells.count()
                    if cell_count < 2:
                        continue
                    text = ((await row.inner_text()) or "").strip()
                    if not text or _NO_RECORDS_RE.search(text):
                        continue
                    # Skip pure header-ish rows with no digit (scrip / period tokens)
                    if not re.search(r"\d", text):
                        continue
                    meaningful += 1
                    if meaningful >= 1:
                        break
                except Exception:
                    continue

            if meaningful > 0:
                self._log_phase(
                    "site_health",
                    "success",
                    health=SiteHealth.UP.value,
                    meaningful_rows=meaningful,
                )
                return SiteHealth.UP

            self._log_phase(
                "site_health",
                "success",
                health=SiteHealth.GRID_MISSING.value,
                detail="grid_present_without_default_rows",
                row_count=row_count,
            )
            return SiteHealth.GRID_MISSING
        except Exception as exc:
            self._log_phase("site_health", "failed", error=str(exc))
            # Ambiguous failure — treat as UI drift so heal remains available.
            return SiteHealth.GRID_MISSING

    async def resolve_scrip_via_api(self, ctx, query: str) -> Optional[str]:
        url = f"https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w?Type=EQ&text={query}"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.bseindia.com",
            "Referer": self.TARGET_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            resp = await ctx.request.get(url, headers=headers, timeout=self.XHR_TIMEOUT)
            if resp.status != 200:
                return None
            data = await resp.json()
            items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
            for item in items:
                for key, value in item.items():
                    if re.search(r"(scrip|security.*code|code)$", key, re.I):
                        token = str(value).strip()
                        if re.fullmatch(r"\d{4,6}", token):
                            return token
                blob = " ".join(str(v or "") for v in item.values())
                match = re.search(r"(?<!\d)(\d{4,6})(?!\d)", blob)
                if match:
                    return match.group(1)
        except Exception:
            return None
        return None

    async def resolve_expected_scrip(self, ctx, company: str) -> Optional[str]:
        text = (company or "").strip()
        if not text:
            return None
        if re.fullmatch(r"\d{4,6}", text):
            return text
        return await self.resolve_scrip_via_api(ctx, text)

    async def _inject_scrip_code(self, page, scrip_code: str, display_name: Optional[str] = None) -> None:
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

    async def resolve_symbol_via_api(self, ctx, query: str) -> Optional[str]:
        """Resolve BSE trading symbol (e.g. RELIANCE) from company name or scrip via PeerSmartSearch."""
        url = f"https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w?Type=EQ&text={query}"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.bseindia.com",
            "Referer": self.TARGET_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            resp = await ctx.request.get(url, headers=headers, timeout=self.XHR_TIMEOUT)
            if resp.status != 200:
                return None
            data = await resp.json()
            items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
            for item in items:
                for key, value in item.items():
                    if re.search(r"(symbol|security.*name|name)$", key, re.I):
                        token = str(value or "").strip()
                        if token and not re.fullmatch(r"\d{4,6}", token):
                            return token
                for value in item.values():
                    text = str(value or "").strip()
                    if text and not re.fullmatch(r"\d{4,6}", text) and len(text) >= 2:
                        return text
        except Exception:
            return None
        return None

    async def _search_input_selector(self, page) -> str:
        selector = await first_unique_visible_locator(
            page,
            [
                self.locators.search_input,
                'form input[name="scripsearchtxtbx"]',
                'input[placeholder*="search" i]',
                'input[type="text"]',
            ],
        )
        if selector:
            self._log_field("search_input", "pass", action="locate", selector=selector)
            return selector
        self._raise_heal(
            "search_input_missing",
            phase="xbrl_search",
            field="search_input",
            action="locate",
            selector=self.locators.search_input,
        )

    async def _click_first_autocomplete(self, page, typed_value: str = "") -> bool:
        """
        Wait for BSE autocomplete LIs and click the FIRST real suggestion.
        Skips "No Match Found". Returns True only when a suggestion was clicked.
        """
        # Overlay list often lives OUTSIDE the form container — prefer global IDs first.
        selectors = [
            "#SearchQuotediv2 #ulSearchQuote2 li",
            "#SearchQuotediv2 li",
            "ul#ulSearchQuote2 li",
            "#ulSearchQuote2 li",
            "li.quotemenu",
            getattr(self.locators, "suggestion_items", "") or "",
        ]
        seen: List[str] = []
        for sel in selectors:
            if sel and sel not in seen:
                seen.append(sel)

        # Autocomplete is AJAX-driven — poll up to ~12s (do not require CSS :visible).
        deadline_ms = 12_000
        poll_ms = 400
        elapsed = 0
        while elapsed <= deadline_ms:
            for sel in seen:
                items = page.locator(sel)
                try:
                    count = await items.count()
                except Exception:
                    count = 0
                if count <= 0:
                    continue
                texts: List[str] = []
                try:
                    texts = await items.all_inner_texts()
                except Exception:
                    texts = []
                for index in range(count):
                    try:
                        txt = (
                            texts[index]
                            if index < len(texts)
                            else (await items.nth(index).inner_text())
                        )
                        txt = (txt or "").strip()
                    except Exception:
                        txt = ""
                    if not txt:
                        continue
                    if re.search(r"no\s*match\s*found", txt, re.I):
                        continue
                    item = items.nth(index)
                    try:
                        await item.scroll_into_view_if_needed(timeout=2_000)
                    except Exception:
                        pass
                    # Prefer Playwright click; fall back to DOM click (ASP.NET menus).
                    clicked = False
                    try:
                        await item.click(timeout=3_000, force=True)
                        clicked = True
                    except Exception:
                        try:
                            await page.evaluate(
                                """([sel, idx]) => {
                                    const nodes = document.querySelectorAll(sel);
                                    const el = nodes[idx];
                                    if (el) { el.click(); return true; }
                                    return false;
                                }""",
                                [sel, index],
                            )
                            clicked = True
                        except Exception as exc:
                            self._log_field(
                                "suggestion_items",
                                "fail",
                                action="click_candidate",
                                selector=sel,
                                value=txt[:120],
                                error=str(exc),
                            )
                            continue
                    if clicked:
                        self._log_field(
                            "suggestion_items",
                            "pass",
                            action="click_first",
                            selector=sel,
                            value=(txt or typed_value)[:120],
                        )
                        await page.wait_for_timeout(400)
                        return True
            await page.wait_for_timeout(poll_ms)
            elapsed += poll_ms
        self._log_field(
            "suggestion_items",
            "fail",
            action="wait_click",
            selector=seen[0] if seen else "",
            error="no_real_suggestion_clicked",
            value=typed_value,
        )
        return False

    async def fill_search(self, page, company: str, expected_scrip: Optional[str] = None) -> None:
        self._log_phase("xbrl_search", "started", company=company)
        try:
            needle = (company or "").strip()
            if not needle and not expected_scrip:
                raise RuntimeError("Empty company / scrip")

            input_selector = await self._search_input_selector(page)
            input_box = page.locator(input_selector).last

            type_string = None
            if expected_scrip and re.fullmatch(r"\d{4,6}", str(expected_scrip).strip()):
                type_string = str(expected_scrip).strip()
                self._log_field(
                    "search_input",
                    "pass",
                    action="use_expected_scrip",
                    selector=input_selector,
                    value=type_string,
                )
            if type_string is None:
                if re.fullmatch(r"\d{4,6}", needle):
                    type_string = needle
                else:
                    resolved = await self.resolve_scrip_via_api(page.context, needle)
                    if resolved:
                        type_string = resolved.strip()
                        self._log_field(
                            "search_input",
                            "pass",
                            action="resolve_scrip",
                            selector=input_selector,
                            value=type_string,
                        )
                    else:
                        type_string = needle

            await input_box.wait_for(state="visible", timeout=10_000)
            await input_box.click()
            await input_box.fill("")
            # Char-by-char so BSE PeerSmartSearch autocomplete fires.
            for ch in type_string:
                await input_box.type(str(ch), delay=130)
            await page.wait_for_timeout(700)  # debounce before list appears
            self._log_field(
                "search_input",
                "pass",
                action="type",
                selector=input_selector,
                value=type_string,
            )

            selected = await self._click_first_autocomplete(page, typed_value=type_string)

            # Keyboard select first highlighted suggestion (ASP.NET SmartSearch).
            if not selected:
                try:
                    await input_box.focus()
                    await input_box.press("ArrowDown")
                    await page.wait_for_timeout(250)
                    await input_box.press("Enter")
                    await page.wait_for_timeout(400)
                    selected = True
                    self._log_field(
                        "suggestion_items",
                        "pass",
                        action="keyboard_select",
                        selector=input_selector,
                        value=type_string,
                    )
                except Exception as exc:
                    self._log_field(
                        "suggestion_items",
                        "fail",
                        action="keyboard_select",
                        selector=input_selector,
                        error=str(exc),
                    )
                    selected = False

            # Symbol fallback: clear, type trading name, click first suggestion.
            if not selected:
                symbol = None
                if not re.fullmatch(r"\d{4,6}", needle):
                    symbol = needle
                if not symbol and hasattr(self, "resolve_symbol_via_api"):
                    symbol = await self.resolve_symbol_via_api(page.context, needle or type_string)
                if symbol:
                    try:
                        await input_box.fill("")
                        for ch in symbol:
                            await input_box.type(str(ch), delay=120)
                        await page.wait_for_timeout(700)
                        self._log_field(
                            "search_input",
                            "pass",
                            action="type_symbol_fallback",
                            selector=input_selector,
                            value=symbol,
                        )
                        selected = await self._click_first_autocomplete(page, typed_value=symbol)
                        if not selected:
                            await input_box.press("ArrowDown")
                            await page.wait_for_timeout(200)
                            await input_box.press("Enter")
                            selected = True
                            self._log_field(
                                "suggestion_items",
                                "pass",
                                action="keyboard_select",
                                selector=input_selector,
                                value=symbol,
                            )
                    except Exception as exc:
                        self._log_field(
                            "search_input",
                            "fail",
                            action="type_symbol_fallback",
                            selector=input_selector,
                            error=str(exc),
                        )

            # Do NOT soft-pass via inject — unbound search → empty gvData after Submit.
            if not selected:
                self._raise_heal(
                    "search_unbound_autocomplete_failed",
                    phase="xbrl_search",
                    company=company,
                    field="suggestion_items",
                    action="click_first",
                    selector=self.locators.suggestion_items,
                    value=type_string,
                    error="must_click_autocomplete_before_submit",
                )

            self._log_phase("xbrl_search", "success", company=company, selected=True)
        except PlaywrightHealRequired:
            raise
        except Exception as exc:
            self._log_phase("xbrl_search", "failed", company=company, error=str(exc))
            raise

    async def apply_filters(self, page) -> None:
        self._log_phase("xbrl_filters", "started")
        try:
            # Optional Segment dropdown -> Equity (container-scoped; not Result Period)
            try:
                seg_selector = "div.get-drop-section.c-sm-mb select#ContentPlaceHolder1_periioddd"
                seg = page.locator(seg_selector)
                if await seg.count() > 0 and await seg.first.is_visible():
                    await page.select_option(seg_selector, label="Equity")
                    self._log_field(
                        "segment_dropdown",
                        "pass",
                        action="select",
                        selector=seg_selector,
                        value="Equity",
                    )
            except Exception as exc:
                self._log_field(
                    "segment_dropdown",
                    "fail",
                    action="select",
                    selector="div.get-drop-section.c-sm-mb select#ContentPlaceHolder1_periioddd",
                    error=str(exc),
                )


            try:
                await page.wait_for_selector(self.locators.result_period_dropdown, timeout=10_000)
                await page.select_option(self.locators.result_period_dropdown, label="ALL")
                self._log_field(
                    "result_period_dropdown",
                    "pass",
                    action="select",
                    selector=self.locators.result_period_dropdown,
                    value="ALL",
                )
                await page.wait_for_selector(self.locators.industry_dropdown, timeout=10_000)
                await page.select_option(self.locators.industry_dropdown, label="ALL")
                self._log_field(
                    "industry_dropdown",
                    "pass",
                    action="select",
                    selector=self.locators.industry_dropdown,
                    value="ALL",
                )
            except Exception as exc:
                self._raise_heal(
                    "filters_missing_or_changed",
                    phase="xbrl_filters",
                    error=str(exc),
                    field="result_period_dropdown",
                    action="select",
                    selector=self.locators.result_period_dropdown,
                    value="ALL",
                )

            try:
                await page.wait_for_selector(self.locators.broadcast_dropdown, timeout=10_000)
                await page.select_option(self.locators.broadcast_dropdown, label="Beyond last 1 year")
                self._log_field(
                    "broadcast_dropdown",
                    "pass",
                    action="select",
                    selector=self.locators.broadcast_dropdown,
                    value="Beyond last 1 year",
                )
            except Exception as exc:
                self._raise_heal(
                    "broadcast_filter_missing_or_changed",
                    phase="xbrl_filters",
                    error=str(exc),
                    field="broadcast_dropdown",
                    action="select",
                    selector=self.locators.broadcast_dropdown,
                    value="Beyond last 1 year",
                )
            self._log_phase("xbrl_filters", "success")
        except PlaywrightHealRequired:
            raise
        except Exception as exc:
            self._log_phase("xbrl_filters", "failed", error=str(exc))
            raise

    async def submit(self, page) -> None:
        self._log_phase("xbrl_submit", "started")
        try:
            try:
                await page.bring_to_front()
                submit_button = page.locator(self.locators.submit_button)
                await submit_button.wait_for(state="visible", timeout=10_000)
                await submit_button.scroll_into_view_if_needed()
                await submit_button.focus()
                self._log_field(
                    "submit_button",
                    "pass",
                    action="locate",
                    selector=self.locators.submit_button,
                )
            except Exception as exc:
                self._raise_heal(
                    "submit_button_missing_or_changed",
                    phase="xbrl_submit",
                    error=str(exc),
                    field="submit_button",
                    action="locate",
                    selector=self.locators.submit_button,
                )

            old_table_html = None
            if await page.locator(self.locators.results_grid).count() > 0:
                try:
                    old_table_html = await page.locator(self.locators.results_grid).first.inner_html()
                except Exception:
                    old_table_html = None

            try:
                await page.evaluate(
                    f"() => {{ const b = document.querySelector('{self.locators.submit_button}'); if (b) b.click(); }}"
                )
                self._log_field(
                    "submit_button",
                    "pass",
                    action="click",
                    selector=self.locators.submit_button,
                )
                await page.wait_for_timeout(20_000)
                if old_table_html is None:
                    await page.wait_for_selector(self.locators.results_grid, timeout=30_000)
                else:
                    await page.wait_for_function(
                        """([selector, oldHtml]) => {
                            const el = document.querySelector(selector);
                            return el && el.innerHTML !== oldHtml;
                        }""",
                        arg=[self.locators.results_grid, old_table_html],
                        timeout=30_000,
                    )
                self._log_field(
                    "results_grid",
                    "pass",
                    action="wait_refresh",
                    selector=self.locators.results_grid,
                )
            except Exception as exc:
                self._raise_heal(
                    "submit_did_not_refresh_results",
                    phase="xbrl_submit",
                    error=str(exc),
                    field="results_grid",
                    action="wait_refresh",
                    selector=self.locators.results_grid,
                )

            try:
                await page.wait_for_load_state("networkidle", timeout=60_000)
            except Exception:
                pass
            self._log_phase("xbrl_submit", "success")
        except PlaywrightHealRequired:
            raise
        except Exception as exc:
            self._log_phase("xbrl_submit", "failed", error=str(exc))
            raise

    async def wait_results(self, page) -> None:
        self._log_phase("xbrl_grid", "started")
        try:
            try:
                await page.wait_for_selector(self.locators.results_grid, timeout=self.GRID_TIMEOUT)
                await page.wait_for_timeout(1000)
            except PWTimeoutError:
                try:
                    await page.get_by_text(re.compile(r"No\s+Record\s+Found", re.I)).first.wait_for(timeout=2000)
                    self._log_phase("xbrl_grid", "success", no_records=True)
                    return
                except PWTimeoutError as exc:
                    await page.screenshot(path="debug_wait_for_results.png", full_page=True)
                    self._raise_heal("results_grid_missing_or_changed", phase="xbrl_grid", error=str(exc))
            self._log_phase("xbrl_grid", "success")
        except PlaywrightHealRequired:
            raise
        except Exception as exc:
            self._log_phase("xbrl_grid", "failed", error=str(exc))
            raise

    async def results_container(self, page):
        return page.locator(self.locators.results_grid).first

    async def data_rows(self, grid):
        tbody_rows = grid.locator("tbody tr")
        if await tbody_rows.count() > 0:
            return tbody_rows
        return grid.locator("tr:has(td)")

    async def document_anchors(self, scope):
        return scope.locator(
            'a[href*="XBRLFILES" i], a[href$=".xml" i], a[href$=".html" i], a[href$=".zip" i]'
        )

    async def resolve_absolute_url(self, page, href: str) -> str:
        href = (href or "").strip()
        if href.startswith(("http", "https")):
            return href
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return "https://www.bseindia.com" + href
        if href.startswith("../"):
            return "https://www.bseindia.com/corporates/" + href.replace("../", "")
        return page.url.rstrip("/") + "/" + href
