from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional, Set, TypedDict

# Must match automation.portal_contract.PortalLocators fields exactly.
PORTAL_LOCATOR_FIELDS: Set[str] = {
    "search_input",
    "suggestion_items",
    "result_period_dropdown",
    "industry_dropdown",
    "broadcast_dropdown",
    "submit_button",
    "results_grid",
}


class ElementReplacement(TypedDict, total=False):
    parameter: str
    change_type: str
    old_behavior: str
    new_behavior: str
    best_selector: str
    visible_match_count: int
    allow_multi_match: bool
    reason: str
    fallbacks: List[Any]


class ChangePlan(TypedDict, total=False):
    goal: str
    mapping: Any
    elements_to_replace: List[ElementReplacement]
    contract_locators: List[ElementReplacement]
    optional_controls: List[ElementReplacement]
    agent_thoughts: Any
    interaction_tweaks: List[str]


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_parameter_name(name: str) -> str:
    """
    Map LLM parameter labels onto PortalLocators / optional control names.
    Handles prefixes like locators.search_input, self.locators.foo, etc.
    """
    raw = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    # Strip common nesting prefixes from analysis LLM output
    for prefix in ("locators.", "self.locators.", "portal.locators.", "results_portal."):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    # If still dotted (e.g. xbrl_search.search_input), prefer last segment
    if "." in raw:
        parts = [p for p in raw.split(".") if p]
        for part in reversed(parts):
            if part in PORTAL_LOCATOR_FIELDS:
                raw = part
                break
        else:
            raw = parts[-1] if parts else raw

    aliases = {
        "search": "search_input",
        "scrip_search": "search_input",
        "scripsearch": "search_input",
        "security_name": "search_input",
        "suggestions": "suggestion_items",
        "suggestion": "suggestion_items",
        "suggestion_container": "suggestion_items",
        "suggestion_container_wrapper": "suggestion_items",
        "period": "result_period_dropdown",
        "result_period": "result_period_dropdown",
        "period_dropdown": "result_period_dropdown",
        "filter_result_period": "result_period_dropdown",
        "industry": "industry_dropdown",
        "filter_industry": "industry_dropdown",
        "broadcast": "broadcast_dropdown",
        "broadcast_period": "broadcast_dropdown",
        "filter_broadcast_period": "broadcast_dropdown",
        "submit": "submit_button",
        "submit_btn": "submit_button",
        "action_submit": "submit_button",
        "grid": "results_grid",
        "results": "results_grid",
        "results_table": "results_grid",
        "results_table_financial": "results_grid",
        "segment": "segment_dropdown",
        "filter_segment": "segment_dropdown",
    }
    return aliases.get(raw, raw)


def split_contract_and_optional(
    elements: List[ElementReplacement],
) -> tuple[List[ElementReplacement], List[ElementReplacement]]:
    contract: List[ElementReplacement] = []
    optional: List[ElementReplacement] = []
    for el in elements:
        param = _normalize_parameter_name(str(el.get("parameter") or ""))
        entry = {**el, "parameter": param}
        if param in PORTAL_LOCATOR_FIELDS:
            contract.append(entry)  # type: ignore[arg-type]
        else:
            optional.append(entry)  # type: ignore[arg-type]
    return contract, optional


def normalize_change_plan(raw: Any, *, default_goal: str = "") -> ChangePlan:
    """
    Coerce LLM / cache payloads into a ChangePlan dict.
    Splits elements into contract_locators (PortalLocators fields) vs optional_controls.
    """
    from llm.azure_llm import parse_markdown_to_data, unwrap_llm_payload

    data: Any = unwrap_llm_payload(raw)
    if isinstance(data, str):
        parsed = parse_markdown_to_data(data)
        data = parsed if parsed is not None else {"content": data}

    if not isinstance(data, dict):
        return {
            "goal": default_goal,
            "elements_to_replace": [],
            "contract_locators": [],
            "optional_controls": [],
            "mapping": None,
            "agent_thoughts": str(data)[:2000],
        }

    if "final_analysis" in data and not data.get("elements_to_replace"):
        nested = unwrap_llm_payload(data.get("final_analysis"))
        if isinstance(nested, str):
            nested = parse_markdown_to_data(nested) or {"content": nested}
        if isinstance(nested, dict):
            merged = {**nested}
            if data.get("goal") and not merged.get("goal"):
                merged["goal"] = data["goal"]
            data = merged

    elements = data.get("elements_to_replace")
    if elements is None and isinstance(data.get("replacements"), list):
        elements = data.get("replacements")
    elements = _as_list(elements)

    normalized_elements: List[ElementReplacement] = []
    for item in elements:
        if not isinstance(item, dict):
            continue
        entry: ElementReplacement = {
            "parameter": str(item.get("parameter") or item.get("name") or item.get("role") or ""),
            "change_type": str(item.get("change_type") or item.get("status") or "selector_drift"),
            "old_behavior": str(item.get("old_behavior") or item.get("old_usage") or ""),
            "new_behavior": str(item.get("new_behavior") or item.get("new_dom_match") or ""),
            "best_selector": str(
                item.get("best_selector")
                or item.get("selector")
                or item.get("new_selector")
                or ""
            ),
            "reason": str(item.get("reason") or ""),
        }
        vmc = item.get("visible_match_count")
        if vmc is not None:
            try:
                entry["visible_match_count"] = int(vmc)
            except Exception:
                pass
        if "allow_multi_match" in item:
            entry["allow_multi_match"] = bool(item.get("allow_multi_match"))
        if item.get("fallbacks") is not None:
            entry["fallbacks"] = _as_list(item.get("fallbacks"))
        normalized_elements.append(entry)

    # Always re-split after normalizing names. Pre-split lists from older caches
    # may have misclassified locators.* names into optional_controls.
    combined: List[ElementReplacement] = []
    seen_params: Set[str] = set()

    def _absorb(items: List[Any]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            # Normalize parameter name up front for dedupe key
            param = _normalize_parameter_name(str(item.get("parameter") or ""))
            if not param or param in seen_params:
                continue
            seen_params.add(param)
            entry = {**item, "parameter": param}
            combined.append(entry)  # type: ignore[arg-type]

    _absorb(normalized_elements)
    _absorb(_as_list(data.get("contract_locators")))
    _absorb(_as_list(data.get("optional_controls")))

    contract, optional = split_contract_and_optional(combined)
    if not normalized_elements:
        normalized_elements = list(combined)
    else:
        # Prefer normalized names on the public elements list
        normalized_elements = list(combined)

    goal = data.get("goal") or data.get("inferred_goal") or default_goal
    plan: ChangePlan = {
        "goal": str(goal) if goal is not None else default_goal,
        "elements_to_replace": normalized_elements,
        "contract_locators": contract,
        "optional_controls": optional,
        "mapping": data.get("mapping"),
        "agent_thoughts": data.get("agent_thoughts"),
    }
    tweaks = data.get("interaction_tweaks")
    if tweaks is not None:
        plan["interaction_tweaks"] = [str(x) for x in _as_list(tweaks)]
    return plan


def validate_selector_uniqueness(plan: ChangePlan) -> List[str]:
    """Return warnings for selectors that claim uniqueness incorrectly."""
    warnings: List[str] = []
    for el in (plan.get("contract_locators") or plan.get("elements_to_replace") or []):
        selector = (el.get("best_selector") or "").strip()
        param = el.get("parameter")
        if not selector:
            warnings.append(f"Missing best_selector for parameter={param}")
            continue
        # suggestion lists are often hidden until typing — allow count 0
        if param == "suggestion_items":
            continue
        vmc = el.get("visible_match_count")
        allow_multi = bool(el.get("allow_multi_match"))
        if vmc is not None and int(vmc) != 1 and not allow_multi:
            warnings.append(
                f"Selector for {param} reports visible_match_count={vmc}; "
                "prefer a container-scoped unique selector."
            )
    return warnings


def validate_portal_locators_kwargs(code: str) -> List[str]:
    """
    AST-check that every PortalLocators(...) call only uses the 7 contract fields.
    Returns a list of error messages (empty = ok).
    """
    errors: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"SyntaxError while validating PortalLocators: {exc}"]

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name != "PortalLocators":
            continue
        for kw in node.keywords:
            if kw.arg is None:
                errors.append("PortalLocators() uses **kwargs; only explicit contract fields allowed")
                continue
            if kw.arg not in PORTAL_LOCATOR_FIELDS:
                errors.append(
                    f"PortalLocators() unexpected field '{kw.arg}'. "
                    f"Allowed: {sorted(PORTAL_LOCATOR_FIELDS)}. "
                    "Put extra selectors on ResultsPortal attributes instead."
                )
    return errors
