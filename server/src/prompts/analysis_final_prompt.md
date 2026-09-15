You produce a ChangePlan for a coding agent that will surgically patch ResultsPortal.

{canonical_flow}

OLD MODULE UNDERSTANDING (crisp):
{structured}

FILTERED DOM:
{filtered_dom}

DOM UNDERSTANDING:
{dom_understanding}

TARGET URL: {new_url}
FEEDBACK: {feedback}

CONTRACT LOCATOR NAMES (parameter MUST be exactly one of these when it is a PortalLocators field):
{portal_locator_fields}

Anything else (segment_dropdown, consent, reset, etc.) is an OPTIONAL control — use snake_case names NOT in the list above.

Return ONE JSON object only:
{{
  "goal": "one sentence operational goal for extracting XBRL from the results grid",
  "mapping": [{{"parameter": "...", "old_selector": "...", "best_selector": "...", "change_type": "..."}}],
  "elements_to_replace": [
    {{
      "parameter": "search_input",
      "change_type": "selector_drift|new_required_control|removed_control|merged_control|unchanged",
      "old_behavior": "<=12 words",
      "new_behavior": "<=12 words",
      "best_selector": "unique CSS/role selector",
      "visible_match_count": 1,
      "reason": "<=20 words",
      "fallbacks": ["optional alternate unique selector"]
    }}
  ],
  "interaction_tweaks": ["short actionable bullet for coding agent"],
  "agent_thoughts": ["2-5 crisp bullets: what coding agent must do"]
}}

CRITICAL RULES:
- parameter names for PortalLocators fields MUST be exact contract names (search_input, NOT locators.search_input).
- suggestion_items must target the clickable LI/option items (or a selector that yields those items), not only a wrapper.
- Prefer one unique container-scoped selector when IDs are duplicated.
- Include EVERY contract field that the old module uses, even if unchanged.
- New required dropdowns (e.g. Segment) go as optional parameter names with change_type new_required_control and a safe default in new_behavior.
- Keep agent_thoughts and reasons SHORT — coding agent will follow this plan literally.
- Prefer selectors that work on the live DOM; do not invent IDs.
- Output is for a coding agent that will ONLY patch locators/interactions — be directive, not narrative.
- interaction_tweaks MUST include: type scrip char-by-char; MUST click FIRST real autocomplete LI in #SearchQuotediv2 (never skip; never "No Match Found"; inject-only is FAIL); Broadcast Period = Beyond last 1 year (value 7); submit then wait for gvData; fill_search(page, company, expected_scrip=); preserve _log_field.
