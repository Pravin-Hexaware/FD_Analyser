"""
Deterministic portal module merge — applies ChangePlan selectors and canonical
search/inject without waiting for LLM codegen.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from agent.portal_reference import (
    CANONICAL_APPLY_FILTERS_SEGMENT_PREFIX,
    CANONICAL_FILL_SEARCH,
    CANONICAL_RESOLVE_SYMBOL_VIA_API,
)
from agent.schemas import ChangePlan, PORTAL_LOCATOR_FIELDS, normalize_change_plan


def locator_map_from_plan(plan: ChangePlan) -> Dict[str, str]:
    """Extract best_selector for each PortalLocators contract field."""
    normalized = normalize_change_plan(plan)
    mapping: Dict[str, str] = {}
    for source in (normalized.get("contract_locators") or [], normalized.get("elements_to_replace") or []):
        for entry in source:
            param = str(entry.get("parameter") or "").strip()
            if param not in PORTAL_LOCATOR_FIELDS:
                continue
            selector = str(entry.get("best_selector") or "").strip()
            if selector:
                mapping[param] = selector
    raw_mapping = normalized.get("mapping")
    if isinstance(raw_mapping, list):
        for row in raw_mapping:
            param = str(row.get("parameter") or "").strip()
            selector = str(row.get("best_selector") or "").strip()
            if param in PORTAL_LOCATOR_FIELDS and selector:
                mapping.setdefault(param, selector)
    return mapping


def optional_segment_selector(plan: ChangePlan) -> Optional[str]:
    normalized = normalize_change_plan(plan)
    for source in (normalized.get("optional_controls") or [], normalized.get("elements_to_replace") or []):
        for entry in source:
            if str(entry.get("parameter") or "").strip() == "segment_dropdown":
                sel = str(entry.get("best_selector") or "").strip()
                if sel:
                    return sel
    return "div.get-drop-section.c-sm-mb select#ContentPlaceHolder1_periioddd"


def patch_portal_locators(source: str, locator_map: Dict[str, str]) -> str:
    """Replace PortalLocators(...) kwargs from the change plan."""
    if not locator_map:
        return source

    def _replace_field(block: str, field: str, selector: str) -> str:
        safe = selector.replace("\\", "\\\\").replace('"', '\\"')
        pattern = rf"({field}\s*=\s*)([\"'])(?:\\.|(?!\2).)*?\2"
        if re.search(pattern, block):
            return re.sub(pattern, lambda m: f'{m.group(1)}"{safe}"', block, count=1)
        inner = block.rstrip()
        if inner.endswith(")"):
            inner = inner[:-1].rstrip()
            if not inner.endswith("("):
                inner += ","
            inner += f'\n        {field}="{safe}"\n    )'
            return inner
        return block

    portal_match = re.search(
        r"locators:\s*PortalLocators\s*=\s*PortalLocators\s*\((.*?)\)",
        source,
        re.DOTALL,
    )
    if not portal_match:
        return source
    full = portal_match.group(0)
    patched = full
    for field, selector in locator_map.items():
        patched = _replace_field(patched, field, selector)
    return source.replace(full, patched, 1)


def _normalize_method_block(method_source: str) -> str:
    """Preserve 4-space class-method indent (do not str.strip() — it removes it)."""
    text = method_source.strip("\n\r")
    lines = text.splitlines()
    normalized: list[str] = []
    for line in lines:
        if line.strip():
            normalized.append(line if line.startswith("    ") else f"    {line.lstrip()}")
        else:
            normalized.append("")
    return "\n".join(normalized).rstrip() + "\n"


def _replace_async_method(source: str, method_name: str, new_method: str) -> str:
    """Replace one async method on ResultsPortal (4-space indent)."""
    new_method = _normalize_method_block(new_method)
    # Match both `def foo(...):` and `def foo(...) -> None:`.
    pattern = (
        rf"(    async def {re.escape(method_name)}\([^)]*\)(?:\s*->\s*[^:]+)?:)\n"
        rf"(?:.*?(?=\n    (?:async )?def |\nclass |\Z))"
    )
    match = re.search(pattern, source, re.DOTALL)
    if match:
        return source[: match.start()] + new_method + source[match.end() :]
    insert_at = source.rfind("\n    async def ")
    if insert_at == -1:
        return source + "\n" + new_method
    return source[:insert_at] + "\n" + new_method + source[insert_at:]


def _ensure_method(source: str, method_name: str, method_source: str) -> str:
    block = _normalize_method_block(method_source)
    if re.search(rf"async def {re.escape(method_name)}\(", source):
        return _replace_async_method(source, method_name, block)
    insert_at = source.rfind("\n    async def _search_input_selector")
    if insert_at == -1:
        insert_at = source.rfind("\n    async def fill_search")
    if insert_at == -1:
        return source + "\n" + block
    return source[:insert_at] + "\n" + block + source[insert_at:]


def patch_apply_filters_segment(source: str, segment_selector: str) -> str:
    if "segment_dropdown" in source and 'label="Equity"' in source:
        return source
    snippet = CANONICAL_APPLY_FILTERS_SEGMENT_PREFIX.format(segment_selector=segment_selector)
    marker = "async def apply_filters(self, page) -> None:"
    idx = source.find(marker)
    if idx == -1:
        return source
    try_start = source.find("try:", idx)
    if try_start == -1:
        return source
    insert_pos = try_start + len("try:")
    return source[:insert_pos] + snippet + source[insert_pos:]


def build_staging_module(old_code: str, plan: Any) -> str:
    """
    Deterministic heal: patch locators from ChangePlan + canonical fill_search that
    MUST click the first autocomplete suggestion before filters/submit.
    """
    normalized = normalize_change_plan(plan)
    code = old_code or ""
    locator_map = locator_map_from_plan(normalized)
    # Overlay list is outside the form — prefer global SearchQuotediv2 LIs.
    locator_map["suggestion_items"] = "#SearchQuotediv2 #ulSearchQuote2 li"
    code = patch_portal_locators(code, locator_map)
    code = _ensure_method(code, "resolve_symbol_via_api", CANONICAL_RESOLVE_SYMBOL_VIA_API)
    # Drop prior helper so re-merge does not duplicate it.
    code = re.sub(
        r"\n    async def _click_first_autocomplete\([\s\S]*?(?=\n    (?:async )?def )",
        "\n",
        code,
        count=1,
    )
    # CANONICAL_FILL_SEARCH includes _click_first_autocomplete + fill_search.
    code = _replace_async_method(code, "fill_search", CANONICAL_FILL_SEARCH)
    seg = optional_segment_selector(normalized)
    code = patch_apply_filters_segment(code, seg)
    return code


def diagnose_harness_failure(stdout: str, runtime_log: str, *, test_input: str = "") -> str:
    """Structured hints for LLM regen — derived from harness evidence."""
    text = f"{stdout or ''}\n{runtime_log or ''}".lower()
    hints = []

    if "unexpected keyword argument 'expected_scrip'" in text:
        hints.append("fill_search MUST accept expected_scrip: Optional[str] = None (batch passes it).")
    if "must_click_autocomplete" in text or "search_unbound_autocomplete_failed" in text:
        hints.append(
            "CRITICAL: After typing the scrip you MUST click the first autocomplete LI "
            "(#SearchQuotediv2 #ulSearchQuote2 li). Skipping the click → empty grid after Submit. "
            "Poll up to 12s, skip 'No Match Found', use force/DOM click, then ArrowDown+Enter."
        )
    if "inject_hidden_scrip" in text and "click_first" not in text and "keyboard_select" not in text:
        hints.append(
            "FIELD logs show inject_hidden_scrip without suggestion click — that is INVALID. "
            "Remove inject soft-pass; require click_first or keyboard_select before filters."
        )
    if "empty_results_grid" in text or "harness_row_count=0" in text:
        hints.append(
            "Empty grid almost always means search was not bound via autocomplete click. "
            "Fix fill_search to click first suggestion before Broadcast/Submit."
        )
    if "no_real_suggestion" in text or "no match found" in text:
        hints.append(
            "If scrip shows only 'No Match Found', clear and type company SYMBOL from "
            "PeerSmartSearch API, then click the first real LI (never inject-only)."
        )
    if "heal_disabled_fail" in text and "xbrl_search" in text:
        hints.append("Harness failed during search phase — fix fill_search / suggestion click first.")
    if test_input and str(test_input).isdigit():
        hints.append(
            f"Harness scrip={test_input}: FIELD must include suggestion_items action=click_first "
            f"(or keyboard_select). inject_hidden_scrip alone is NOT enough."
        )
    if not hints:
        hints.append("Compare deterministic merge vs staging; keep autocomplete click mandatory.")
    return "\n".join(f"- {h}" for h in hints)
