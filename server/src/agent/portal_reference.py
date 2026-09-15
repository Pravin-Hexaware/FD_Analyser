"""
Canonical portal interaction snippets used by deterministic heal merge.

These are agent-owned references — not production automation — so the coding
agent can promote working code without relying on LLM to reinvent search/inject.
"""

from __future__ import annotations

CANONICAL_RESOLVE_SYMBOL_VIA_API = '''
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
                        if token and not re.fullmatch(r"\\d{4,6}", token):
                            return token
                for value in item.values():
                    text = str(value or "").strip()
                    if text and not re.fullmatch(r"\\d{4,6}", text) and len(text) >= 2:
                        return text
        except Exception:
            return None
        return None
'''

# MUST click first autocomplete suggestion before filters/submit.
# Inject alone leaves search unbound → empty grid after Submit.
CANONICAL_FILL_SEARCH = '''
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
                    if re.search(r"no\\s*match\\s*found", txt, re.I):
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
            if expected_scrip and re.fullmatch(r"\\d{4,6}", str(expected_scrip).strip()):
                type_string = str(expected_scrip).strip()
                self._log_field(
                    "search_input",
                    "pass",
                    action="use_expected_scrip",
                    selector=input_selector,
                    value=type_string,
                )
            if type_string is None:
                if re.fullmatch(r"\\d{4,6}", needle):
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
                if not re.fullmatch(r"\\d{4,6}", needle):
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
'''

CANONICAL_APPLY_FILTERS_SEGMENT_PREFIX = '''
            # Optional Segment dropdown -> Equity (container-scoped; not Result Period)
            try:
                seg_selector = "{segment_selector}"
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
                    selector="{segment_selector}",
                    error=str(exc),
                )

'''
