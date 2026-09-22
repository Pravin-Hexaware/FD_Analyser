from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.schemas import PORTAL_LOCATOR_FIELDS, normalize_change_plan
from agent.portal_flow import BSE_RESULTS_CANONICAL_FLOW
from llm.azure_llm import evaluate_with_azure_llm, markdownify, parse_markdown_to_data
from prompts.loader import load_prompt
from services.logging_service import logging_service

CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Single crisp artifact consumed by coding agent / orchestrator.
ANALYSIS_RESPONSE_FILE = CACHE_DIR / "analysis_final.md"
INITIAL_ANALYSIS_FILE = CACHE_DIR / "analysis_initial.md"


class AgentState(TypedDict, total=False):
    old_code: str
    new_url: str
    iteration: int
    analysis: Optional[Any]
    feedback: Optional[str]


def save_markdown(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = markdownify(payload) if isinstance(payload, (dict, list)) else str(payload)
    path.write_text(text, encoding="utf-8")
    logging_service.log_runtime(f"[ANALYSIS AGENT] Saved {path}", echo=True)


def log_agent_thoughts(result: Any, *, agent: str = "analysis") -> None:
    if not isinstance(result, dict):
        return
    thoughts = result.get("agent_thoughts") or result.get("reasoning")
    if not thoughts:
        return
    logging_service.log_agent_thinking(agent, thoughts)


def build_initial_prompt(old_code: str, new_url: str, feedback: Optional[str] = None) -> str:
    return load_prompt(
        "analysis_initial_prompt.md",
        old_code=old_code,
        new_url=new_url,
        feedback=feedback or "None",
        portal_locator_fields=sorted(PORTAL_LOCATOR_FIELDS),
    )


def build_final_prompt(
    understanding: Dict[str, Any],
    filtered_dom: Any,
    dom_understanding: Any,
    new_url: str,
    feedback: Optional[str] = None,
) -> str:
    structured = understanding.get("analysis") if isinstance(understanding, dict) else understanding
    return load_prompt(
        "analysis_final_prompt.md",
        canonical_flow=BSE_RESULTS_CANONICAL_FLOW,
        structured=markdownify(structured),
        filtered_dom=markdownify(filtered_dom),
        dom_understanding=markdownify(dom_understanding),
        new_url=new_url,
        feedback=feedback or "None",
        portal_locator_fields=sorted(PORTAL_LOCATOR_FIELDS),
    )


def analyze_initial(old_code: str, new_url: str, feedback: Optional[str] = None) -> Dict[str, Any]:
    prompt = build_initial_prompt(old_code, new_url, feedback)
    result = evaluate_with_azure_llm(
        prompt=prompt,
        cache_path=str(INITIAL_ANALYSIS_FILE),
        run_name="heal_analysis_initial",
        tags=["heal-agent", "analysis"],
    )
    log_agent_thoughts(result, agent="analysis")
    understanding = {
        "new_url": new_url,
        "analysis": result,
        "feedback": feedback,
    }
    # Overwrite cache with compact understanding (no full old_code dump)
    save_markdown(INITIAL_ANALYSIS_FILE, understanding)
    return {
        "old_code": old_code,
        "new_url": new_url,
        "analysis": result,
        "iteration": 1,
        "feedback": feedback,
    }


def analyze_final(
    understanding: Dict[str, Any],
    filtered_dom: Any,
    dom_understanding: Any,
    new_url: str,
    feedback: Optional[str] = None,
) -> Dict[str, Any]:
    prompt = build_final_prompt(understanding, filtered_dom, dom_understanding, new_url, feedback)
    result = evaluate_with_azure_llm(
        prompt=prompt,
        cache_path=str(ANALYSIS_RESPONSE_FILE),
        run_name="heal_analysis_final",
        tags=["heal-agent", "analysis"],
    )
    log_agent_thoughts(result, agent="analysis")

    unwrapped: Any = result
    derived_goal = None
    if isinstance(result, dict):
        derived_goal = result.get("goal") or result.get("inferred_goal")
    elif isinstance(result, str):
        try:
            parsed = parse_markdown_to_data(result)
            if isinstance(parsed, dict):
                unwrapped = parsed
                derived_goal = parsed.get("goal") or parsed.get("inferred_goal")
        except Exception:
            pass

    plan = normalize_change_plan(
        unwrapped if isinstance(unwrapped, dict) else {"goal": derived_goal or new_url},
        default_goal=str(derived_goal or new_url),
    )

    # Persist ONLY the normalized ChangePlan — no nested duplication
    save_markdown(ANALYSIS_RESPONSE_FILE, plan)
    return plan
