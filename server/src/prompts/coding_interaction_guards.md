{canonical_flow}

PORTAL INTERACTION GUARDS (mandatory — violations fail the harness):
- Type the BSE scrip code (4–6 digits) character-by-character in the Security Name field.
- Wait/poll for autocomplete; MUST click the FIRST real suggestion (#SearchQuotediv2 li).
- Skipping the autocomplete click leaves search unbound → EMPTY grid after Submit (FAIL).
- Never soft-pass with inject_hidden_scrip instead of clicking a suggestion.
- Broadcast Period MUST be "Beyond last 1 year" (value 7), NOT "Last 1 year".
- page.select_option(..., label=...) MUST be plain strings, never re.compile(...).
- fill_search(page, company, expected_scrip=None) must accept expected_scrip from CSV.
- If suggestions fail: type symbol from API, click first LI, or ArrowDown+Enter.
- Preserve all _log_field / logging_service.log_field calls.
