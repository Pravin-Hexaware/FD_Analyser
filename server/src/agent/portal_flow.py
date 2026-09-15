"""
Canonical BSE Financial Results automation flow.

Loaded from ``prompts/orchestration_portal_canonical_flow.md`` and
``prompts/orchestration_heal_goal.md`` so prompt text can be edited without
touching Python.
"""

from __future__ import annotations

from prompts.loader import load_prompt


def get_canonical_flow() -> str:
    return load_prompt("orchestration_portal_canonical_flow.md").rstrip() + "\n"


def get_heal_goal_template() -> str:
    return load_prompt("orchestration_heal_goal.md").strip()


# Back-compat aliases used across the codebase (re-read from disk each access
# would require property wrappers; modules that need live edits should call
# get_*(). These module-level names are refreshed at import / reload.)
BSE_RESULTS_CANONICAL_FLOW = get_canonical_flow()
HEAL_GOAL_TEMPLATE = get_heal_goal_template()
