from __future__ import annotations

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import analysis_agent, coding_agent, dom_agent
from agent.heal_context import PLANS_DIR, STAGING_MODULE, HealRunContext
from agent.portal_flow import BSE_RESULTS_CANONICAL_FLOW, get_heal_goal_template
from utils.langsmith_tracing import traceable_run
from agent.schemas import normalize_change_plan, validate_selector_uniqueness
from llm.azure_llm import unwrap_llm_payload
from services.logging_service import logging_service
from tools.screenshot_test import extract_dom_from_url


def _thought_from_payload(agent: str, payload: Any) -> tuple[str, list[str]]:
    decisions: list[str] = []
    summary = f"{agent} completed"
    data = unwrap_llm_payload(payload)
    if isinstance(data, dict):
        thoughts = data.get("agent_thoughts") or data.get("reasoning")
        if thoughts is not None:
            if isinstance(thoughts, (dict, list)):
                summary = json.dumps(thoughts, ensure_ascii=False)[:500]
            else:
                summary = str(thoughts)[:500]
        for key in ("goal", "best_selector", "intent"):
            if data.get(key):
                decisions.append(f"{key}={data.get(key)}")
        elements = data.get("elements_to_replace")
        if isinstance(elements, list):
            decisions.append(f"elements_to_replace={len(elements)}")
    elif isinstance(data, str):
        summary = data[:500]
    return summary, decisions


async def _run_heal_async(
    old_module_source: str,
    url: str,
    test_input: str = "500325",
    ctx: Optional[HealRunContext] = None,
) -> Path:
    if ctx is None:
        ctx = HealRunContext(target_url=url, test_input=test_input)

    logging_service.log_phase(
        "agent_analysis",
        "started",
        target_url=url,
        test_input=test_input,
        detail="initial_portal_module_analysis",
        old_code_chars=len(old_module_source or ""),
        run_id=ctx.run_id,
    )

    loop = asyncio.get_running_loop()

    # Parallel: old-code analysis (sync LLM) + live DOM extract
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="heal-parallel") as pool:
        analysis_future = loop.run_in_executor(
            pool, analysis_agent.analyze_initial, old_module_source, url
        )
        dom_future = extract_dom_from_url(url)  # FINBOT_HEADLESS controls headed vs headless
        understanding, raw_dom = await asyncio.gather(analysis_future, dom_future)

    summary, decisions = _thought_from_payload("analysis", understanding.get("analysis") if isinstance(understanding, dict) else understanding)
    ctx.add_thought("analysis", summary=summary, decisions=decisions)
    logging_service.log_phase(
        "agent_analysis",
        "success",
        target_url=url,
        detail="initial_analysis_complete",
        understanding_type=type(understanding).__name__,
        run_id=ctx.run_id,
    )

    logging_service.log_phase("agent_dom", "started", target_url=url, detail="filter_live_dom", run_id=ctx.run_id)
    _, filtered_dom, dom_understanding = await dom_agent.run(raw_dom)
    summary, decisions = _thought_from_payload("dom", dom_understanding)
    ctx.add_thought("dom", summary=summary, decisions=decisions)
    logging_service.log_phase(
        "agent_dom",
        "success",
        target_url=url,
        detail="dom_filtered_and_understood",
        filtered_dom_chars=len(filtered_dom or "") if isinstance(filtered_dom, str) else None,
        dom_understanding_type=type(dom_understanding).__name__,
        run_id=ctx.run_id,
    )

    logging_service.log_phase(
        "agent_analysis",
        "started",
        target_url=url,
        detail="final_analysis_with_dom",
        run_id=ctx.run_id,
    )
    # analyze_final already returns a normalized ChangePlan (also cached as analysis_final.md)
    final_result = analysis_agent.analyze_final(understanding, filtered_dom, dom_understanding, url)
    plan = normalize_change_plan(final_result, default_goal=url)
    summary, decisions = _thought_from_payload("analysis", plan)
    ctx.add_thought("analysis", summary=summary, decisions=decisions)
    logging_service.log_phase(
        "agent_analysis",
        "progress",
        target_url=url,
        detail="final_change_plan_ready",
        analysis_keys=list(plan.keys()) if isinstance(plan, dict) else None,
        contract_locators_count=len(plan.get("contract_locators") or []),
        optional_controls_count=len(plan.get("optional_controls") or []),
        run_id=ctx.run_id,
    )
    # Operational goal for coding/harness — canonical BSE flow (type scrip → first suggestion → submit).
    plan["goal"] = get_heal_goal_template().format(test_input=test_input)
    plan.setdefault("interaction_tweaks", [])
    if BSE_RESULTS_CANONICAL_FLOW not in plan["interaction_tweaks"]:
        plan["interaction_tweaks"].append(
            "Type scrip code char-by-char; click first autocomplete row; Broadcast Beyond last 1 year; submit; extract Std XBRL."
        )
    warnings = validate_selector_uniqueness(plan)
    plan_path = PLANS_DIR / f"change_plan_{ctx.run_id}.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    ctx.add_thought(
        "merge",
        summary="Merged old-code analysis with live DOM into ChangePlan",
        decisions=[
            f"goal={plan.get('goal')}",
            f"contract_locators={len(plan.get('contract_locators') or [])}",
            f"optional_controls={len(plan.get('optional_controls') or [])}",
            f"elements={len(plan.get('elements_to_replace') or [])}",
            f"plan_path={plan_path}",
        ],
        warnings=warnings,
    )
    logging_service.log_phase(
        "agent_analysis",
        "success",
        target_url=url,
        detail="selector_replacement_plan",
        elements_to_replace_count=len(plan.get("elements_to_replace") or []),
        contract_locators_count=len(plan.get("contract_locators") or []),
        optional_controls_count=len(plan.get("optional_controls") or []),
        mapping_count=len(plan.get("mapping")) if isinstance(plan.get("mapping"), (dict, list)) else None,
        goal=str(plan.get("goal") or "")[:500] or None,
        uniqueness_warnings=len(warnings),
        run_id=ctx.run_id,
    )

    logging_service.log_phase(
        "agent_codegen",
        "started",
        target_url=url,
        test_input=test_input,
        detail="coding_agent_stage_results_portal",
        run_id=ctx.run_id,
    )
    generated_code_path = coding_agent.autonomous_coding_agent(
        old_module_source,
        plan,
        url,
        test_input=test_input,
        ctx=ctx,
    )
    logging_service.log_phase(
        "agent_codegen",
        "success",
        target_url=url,
        generated_path=str(generated_code_path),
        detail="coding_agent_wrote_staging_module",
        run_id=ctx.run_id,
    )
    logging_service.log_phase(
        "agent_test",
        "success",
        generated_path=str(generated_code_path),
        test_input=test_input,
        detail="heal_pipeline_staging_ready",
        run_id=ctx.run_id,
    )
    return Path(generated_code_path)


@traceable_run("heal_run", run_type="chain", tags=["heal-agent"])
def run_heal(
    old_module_source: str,
    url: str,
    test_input: str = "500325",
    target_output_path: Path | None = None,
    ctx: Optional[HealRunContext] = None,
) -> Path:
    """
    Run heal pipeline. Returns staging module path on success.
    Promotion to production is handled by heal_service (not here), unless
    target_output_path is explicitly provided for legacy callers.
    """
    if ctx is None:
        ctx = HealRunContext(target_url=url, test_input=test_input)

    logging_service.log_phase(
        "agent_analysis",
        "started",
        target_url=url,
        test_input=test_input,
        detail="run_heal_entry",
        has_target_output=bool(target_output_path),
        run_id=ctx.run_id,
    )
    generated_code_path = asyncio.run(
        _run_heal_async(old_module_source, url, test_input=test_input, ctx=ctx)
    )
    generated_code_path = Path(generated_code_path)

    # Legacy optional copy — avoid writing production unless caller insists AND path differs from staging.
    if target_output_path and Path(target_output_path).resolve() != generated_code_path.resolve():
        # Only allow copy when caller is not pointing at production automation path during failed heals.
        # heal_service now promotes explicitly after success; keep this for scripts that pass a custom path.
        if Path(target_output_path).resolve() == (ROOT / "automation" / "results_portal.py").resolve():
            logging_service.log_phase(
                "agent_swap",
                "warning",
                detail="skipped_direct_production_copy_use_heal_service_promote",
                staging=str(generated_code_path),
            )
        else:
            Path(target_output_path).write_text(
                generated_code_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            logging_service.log_phase(
                "agent_swap",
                "progress",
                swapped_path=str(target_output_path),
                source_path=str(generated_code_path),
                detail="copied_generated_module_to_target",
            )
            return Path(target_output_path)
    return generated_code_path


if __name__ == "__main__":
    sample_path = ROOT / "automation" / "results_portal.py"
    source = sample_path.read_text(encoding="utf-8") if sample_path.exists() else ""
    print(run_heal(source, "https://www.bseindia.com/corporates/comp_resultsnew"))
