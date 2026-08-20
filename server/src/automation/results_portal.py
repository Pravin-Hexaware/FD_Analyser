from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, List, Any

from playwright.async_api import TimeoutError as PWTimeoutError

from automation.portal_contract import PortalLocators
from automation.unique_locator import first_unique_visible_locator
from services.logging_service import logging_service


class PlaywrightHealRequired(RuntimeError):
    """Raised when the portal UI appears to have drifted and needs healing."""


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

    def _raise_heal(self, reason: str, **details: Any) -> None:
        logging_service.log_heal_trigger(reason, target_url=self.TARGET_URL, **details)
        raise PlaywrightHealRequired(reason)

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
            return selector
        self._raise_heal("search_input_missing", phase="xbrl_search")

    async def fill_search(self, page, company: str) -> None:
        self._log_phase("xbrl_search", "started", company=company)
        needle = (company or "").strip()
        if not needle:
            raise RuntimeError("Empty company / scrip")

        input_selector = await self._search_input_selector(page)
        input_box = page.locator(input_selector).last
        match_key = needle
        type_string = needle
        if not re.fullmatch(r"\d{4,6}", needle):
            resolved = await self.resolve_scrip_via_api(page.context, needle)
            if resolved:
                type_string = resolved.strip()
                match_key = type_string

        try:
            await input_box.wait_for(state="visible", timeout=10_000)
            await input_box.click()
            for ch in type_string:
                await input_box.type(str(ch), delay=150)
        except Exception as exc:
            self._raise_heal("search_interaction_failed", phase="xbrl_search", company=company, error=str(exc))

        items = page.locator(self.locators.suggestion_items)
        try:
            await page.wait_for_selector(self.locators.suggestion_items, state="visible", timeout=10_000)
        except Exception:
            pass

        suggestions: List[str] = []
        try:
            if await items.count() > 0:
                suggestions = await items.all_inner_texts()
        except Exception:
            suggestions = []

        selected = False
        lowered = match_key.lower()
        for index, text in enumerate(suggestions):
            if lowered in (text or "").lower():
                await items.nth(index).click()
                selected = True
                break

        if not selected and await items.count() > 0:
            try:
                await items.nth(0).click()
                selected = True
            except Exception:
                selected = False

        if not selected:
            if re.fullmatch(r"\d{4,6}", type_string):
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
                            const ids = ['ContentPlaceHolder1_hf_scripcode', 'ContentPlaceHolder1_SmartSearch_hdnCode', 'hf_scripcode'];
                            for (const id of ids) {
                                const h = document.getElementById(id);
                                if (h) {
                                    h.value = code;
                                    h.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                            }
                        }""",
                        [type_string],
                    )
                    await self._inject_scrip_code(page, type_string, display_name=type_string)
                    selected = True
                except Exception as exc:
                    self._raise_heal("search_hidden_fields_failed", phase="xbrl_search", company=company, error=str(exc))
            else:
                try:
                    await input_box.press("ArrowDown")
                    await input_box.press("Enter")
                    selected = True
                except Exception as exc:
                    self._raise_heal("search_suggestion_selection_failed", phase="xbrl_search", company=company, error=str(exc))

        self._log_phase("xbrl_search", "success", company=company, selected=selected)

    async def apply_filters(self, page) -> None:
        self._log_phase("xbrl_filters", "started")
        try:
            await page.wait_for_selector(self.locators.result_period_dropdown, timeout=10_000)
            await page.select_option(self.locators.result_period_dropdown, label="ALL")
            await page.wait_for_selector(self.locators.industry_dropdown, timeout=10_000)
            await page.select_option(self.locators.industry_dropdown, label="ALL")
        except Exception as exc:
            self._raise_heal("filters_missing_or_changed", phase="xbrl_filters", error=str(exc))

        try:
            await page.wait_for_selector(self.locators.broadcast_dropdown, timeout=10_000)
            await page.select_option(self.locators.broadcast_dropdown, label="Beyond last 1 year")
        except Exception as exc:
            self._raise_heal("broadcast_filter_missing_or_changed", phase="xbrl_filters", error=str(exc))
        self._log_phase("xbrl_filters", "success")

    async def submit(self, page) -> None:
        self._log_phase("xbrl_submit", "started")
        try:
            await page.bring_to_front()
            submit_button = page.locator(self.locators.submit_button)
            await submit_button.wait_for(state="visible", timeout=10_000)
            await submit_button.scroll_into_view_if_needed()
            await submit_button.focus()
        except Exception as exc:
            self._raise_heal("submit_button_missing_or_changed", phase="xbrl_submit", error=str(exc))

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
        except Exception as exc:
            self._raise_heal("submit_did_not_refresh_results", phase="xbrl_submit", error=str(exc))

        try:
            await page.wait_for_load_state("networkidle", timeout=60_000)
        except Exception:
            pass
        self._log_phase("xbrl_submit", "success")

    async def wait_results(self, page) -> None:
        self._log_phase("xbrl_grid", "started")
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
