Apply the ChangePlan surgically to the EXISTING ResultsPortal module.
Update locators and broken interaction steps only.
Preserve portal contract, imports, logging_service, PlaywrightHealRequired (never sys.exit).

TARGET URL: {new_url}
GOAL: {goal_text}

CONTRACT LOCATORS (ONLY these may be PortalLocators kwargs):
Allowed: {portal_locator_fields}
{contract}

OPTIONAL CONTROLS (ResultsPortal attributes — never PortalLocators kwargs):
{optional}

INTERACTION TWEAKS:
{tweaks}

ANALYSIS THOUGHTS:
{thoughts}

UNIQUENESS WARNINGS:
{warnings}

MAPPING:
{mapping}

UPSTREAM THOUGHTS:
{state_messages}

FEEDBACK:
{feedback}

OLD MODULE (edit this — do not invent a new architecture):
{old_code}

STRICT OUTPUT FORMAT (mandatory):
REASONING:
- 3 to 8 short bullet lines: what you change and why
Then exactly one fenced Python module (full file):

```python
# full results_portal.py source here
```

Rules:
- Do NOT return JSON.
- Do NOT put code outside the ```python fence.
- Do NOT truncate the module; include the complete file.
- PortalLocators(...) ONLY uses the 7 contract fields above.
- Preserve _log_field / logging_service.log_field calls if present (per-control pass/fail logs).
- suggestion_items must match clickable LI/option rows after typing.
- After submit, wait until the results grid has real data rows.
{interaction_guards}
