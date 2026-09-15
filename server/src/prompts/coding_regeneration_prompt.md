You are fixing a FAILED heal attempt.

STEP 1 — DIAGNOSE from evidence (do this in REASONING before writing code):
- Read EXECUTION / HARNESS LOGS and RUNTIME ACTION LOG carefully.
- State the root cause in 1-3 lines.
- If logs alone are insufficient, compare DETERMINISTIC BASE vs LAST STAGING.
- Do NOT revert fill_search to omit expected_scrip or to use strict verify_binding gates.

STEP 2 — FIX surgically and return the full corrected module.
- Prefer patching locators/selectors ONLY; keep canonical fill_search inject flow intact.

TARGET URL: {new_url}
GOAL: {goal_text}
FAILURE PHASE HINT: {failure_phase}
(Hint only — trust the logs over the hint.)

CONTRACT LOCATORS (PortalLocators fields only):
{contract}

OPTIONAL CONTROLS (ResultsPortal attributes only):
{optional}

INTERACTION TWEAKS:
{tweaks}

LAST CODING REASONING:
{last_coding_reasoning}

PRIOR THOUGHTS:
{state_messages}

===== EVIDENCE (primary) =====
EXECUTION / HARNESS LOGS:
{logs}

RUNTIME ACTION / FIELD LOG (FIELD field=... status=pass|fail lines):
{runtime_log}

STRUCTURED FAILURE HINTS (trust these over guesswork):
{failure_hints}

===== CODE REFERENCES =====
DETERMINISTIC MERGE BASE (agent-built — canonical fill_search + plan locators):
{det_base}

ORIGINAL MODULE (pre-heal production — locator drift reference only):
{old_code}

FIRST GENERATED CODE (reference if logs are thin / codegen failed):
{first_ref}

LAST STAGING MODULE (most recent attempt; may equal first):
{last_code}

STRICT OUTPUT FORMAT (mandatory):
REASONING:
- What failed (from logs)
- Root cause
- Exact fix you will apply
Then exactly one fenced Python module (complete file):

```python
# full results_portal.py source here
```

Rules:
- Do NOT return JSON.
- Do NOT put code outside the ```python fence.
- Do NOT truncate.
- If prior fix failed, try a DIFFERENT approach.
- Preserve _log_field / logging_service.log_field if present.
- PortalLocators(...) MUST only use: {portal_locator_fields}
- Preserve PlaywrightHealRequired (never sys.exit). No CLI/main.
{interaction_guards}
- If FIELD logs show suggestion_items + "No Match Found" + status=pass, that is a FAIL:
  skip that LI, inject numeric scrip or raise PlaywrightHealRequired.
- If FIELD shows select_option / TypeError involving re.compile, use label="Equity" (string).
