from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from typing_extensions import TypedDict

from langgraph.constants import START
from langgraph.graph import StateGraph
from agent.heal_context import STAGING_MODULE, HealRunContext
from agent.portal_flow import BSE_RESULTS_CANONICAL_FLOW
from agent.portal_merge import build_staging_module, diagnose_harness_failure
from agent.schemas import (
    PORTAL_LOCATOR_FIELDS,
    ChangePlan,
    normalize_change_plan,
    validate_portal_locators_kwargs,
    validate_selector_uniqueness,
)
from llm.azure_llm import (
    evaluate_with_azure_llm,
    extract_code_from_markdown,
    markdownify,
    unwrap_llm_payload,
)
from prompts.loader import load_prompt
from services.logging_service import logging_service
from tools.executor import execute_generated_script

CACHE_DIR = Path(__file__).resolve().parents[1] / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

GENERATED_CODE_FILE = STAGING_MODULE
CODE_CACHE_FILE = CACHE_DIR / "code_generation.md"
FAILED_CODEGEN_RAW = CACHE_DIR / "failed_codegen_raw.md"
FIRST_GENERATED_FILE = CACHE_DIR / "first_generated_results_portal.py"
EXECUTION_LOG_FILE = CACHE_DIR / "generated_code_run.log"
RUNTIME_LOG_FILE = CACHE_DIR / "generated_script_runtime.log"

_MAX_LOG_CHARS = 12000
_MAX_THOUGHT_CHARS = 1500
_CODING_MAX_TOKENS = 16000


def _coding_system() -> str:
    return load_prompt("coding_system_prompt.md").strip()


def _portal_interaction_rules() -> str:
    return load_prompt(
        "coding_interaction_guards.md",
        canonical_flow=BSE_RESULTS_CANONICAL_FLOW,
    ).rstrip() + "\n"

class CodingAgentState(TypedDict, total=False):
    old_code: str
    final_analysis: Any
    new_url: str
    feedback: Optional[str]
    previous_thoughts: list
    attempt: int
    test_input: str
    deterministic_base: str
    generated_path: str
    execution_log: str
    runtime_log: str
    last_harness_log: str
    last_runtime_log: str
    last_coding_reasoning: str
    first_generated_code: str
    stdout: str
    stderr: str
    exit_code: int
    status: str
    goal_achieved: bool
    failure_phase: str


def _plan_from_analysis(final_analysis: Any, new_url: str) -> ChangePlan:
    return normalize_change_plan(final_analysis, default_goal=new_url)


def _clip(text: Any, limit: int = _MAX_LOG_CHARS) -> str:
    s = "" if text is None else str(text)
    if len(s) <= limit:
        return s
    head = limit // 2
    tail = limit - head
    return s[:head] + "\n\n...[truncated]...\n\n" + s[-tail:]


def _run_id(ctx: Optional[HealRunContext]) -> Optional[str]:
    return ctx.run_id if ctx else None


def log_agent_thoughts(
    agent: str,
    thoughts: Any,
    *,
    ctx: Optional[HealRunContext] = None,
    prefix: str = "",
) -> None:
    """Write thinking to application/agent-run logs — not the terminal."""
    if thoughts is None:
        return
    if isinstance(thoughts, (dict, list)):
        text = json.dumps(thoughts, ensure_ascii=False, indent=2)
    else:
        text = str(thoughts).strip()
    if not text:
        return
    logging_service.log_agent_thinking(agent, text, run_id=_run_id(ctx))
    if ctx:
        ctx.log("agent_thinking", agent=agent, thoughts=text[:_MAX_THOUGHT_CHARS], prefix=prefix or "")


def _status(msg: str, *, ctx: Optional[HealRunContext] = None) -> None:
    """Short progress line to terminal + app log."""
    logging_service.log_runtime(msg, echo=True)
    if ctx:
        ctx.log("status", message=msg)


def build_coding_prompt(
    old_code: str,
    final_analysis: Any,
    new_url: str,
    feedback: Optional[str] = None,
    state_messages: Optional[list] = None,
) -> str:
    plan = _plan_from_analysis(final_analysis, new_url)
    warnings = validate_selector_uniqueness(plan)
    contract = plan.get("contract_locators") or []
    optional = plan.get("optional_controls") or []
    goal_text = plan.get("goal") or new_url
    tweaks = plan.get("interaction_tweaks") or []
    thoughts = plan.get("agent_thoughts")

    return load_prompt(
        "coding_prompt.md",
        new_url=new_url,
        goal_text=goal_text,
        portal_locator_fields=sorted(PORTAL_LOCATOR_FIELDS),
        contract=markdownify(contract),
        optional=markdownify(optional),
        tweaks=markdownify(tweaks) if tweaks else "None",
        thoughts=markdownify(thoughts) if thoughts else "None",
        warnings=markdownify(warnings) if warnings else "None",
        mapping=markdownify(plan.get("mapping")),
        state_messages=markdownify(state_messages) if state_messages else "None",
        feedback=feedback or "None",
        old_code=old_code,
        interaction_guards=_portal_interaction_rules(),
    )


def build_regeneration_prompt(
    old_code: str,
    final_analysis: Any,
    last_code: str,
    logs: str,
    runtime_log: str,
    new_url: str,
    state_messages: Optional[list] = None,
    failure_phase: str = "unknown",
    last_coding_reasoning: str = "",
    first_generated_code: str = "",
    test_input: str = "",
    deterministic_base: str = "",
) -> str:
    plan = _plan_from_analysis(final_analysis, new_url)
    goal_text = plan.get("goal") or new_url
    contract = plan.get("contract_locators") or []
    optional = plan.get("optional_controls") or []
    tweaks = plan.get("interaction_tweaks") or []
    failure_hints = diagnose_harness_failure(logs, runtime_log, test_input=test_input)

    first_ref = first_generated_code.strip() if first_generated_code else ""
    if not first_ref:
        first_ref = "(not available — use DETERMINISTIC BASE + LAST STAGING)"

    det_base = deterministic_base.strip() if deterministic_base else ""
    if not det_base:
        det_base = "(not available — use ORIGINAL MODULE)"

    return load_prompt(
        "coding_regeneration_prompt.md",
        new_url=new_url,
        goal_text=goal_text,
        failure_phase=failure_phase,
        contract=markdownify(contract),
        optional=markdownify(optional),
        tweaks=markdownify(tweaks) if tweaks else "None",
        last_coding_reasoning=_clip(last_coding_reasoning, _MAX_THOUGHT_CHARS)
        if last_coding_reasoning
        else "None",
        state_messages=markdownify(state_messages) if state_messages else "None",
        logs=_clip(logs),
        runtime_log=_clip(runtime_log),
        failure_hints=failure_hints,
        det_base=_clip(det_base, 14000),
        old_code=_clip(old_code, 8000),
        first_ref=_clip(first_ref, 14000),
        last_code=_clip(last_code, 14000),
        portal_locator_fields=sorted(PORTAL_LOCATOR_FIELDS),
        interaction_guards=_portal_interaction_rules(),
    )

def classify_harness_failure(stdout: str, stderr: str, status: str = "") -> str:
    text = f"{stdout or ''}\n{stderr or ''}\n{status or ''}".lower()
    if "codegen_error" in text or "non-python" in text or "refusing to stage" in text:
        return "codegen_error"
    if "portalocators" in text or "unexpected keyword" in text or "contract violation" in text:
        return "import_error"
    if "import_error" in text or "syntaxerror" in text or "typeerror" in text:
        return "import_error"
    if re.search(r"no\s*match\s*found", text) and "suggestion_items" in text:
        return "search"
    if "submit_did_not_refresh" in text or "did_not_refresh_results" in text:
        return "search"
    if "empty_results_grid" in text:
        return "empty_grid"
    if "heal_disabled_fail" in text:
        if "xbrl_search" in text or "search" in text:
            return "search"
        if "filter" in text:
            return "filters"
        if "submit" in text:
            return "search"
        return "search"
    if "harness_phase=submit" in text and ("fail" in text or "exception" in text):
        return "search"
    if "harness_phase=search" in text and ("fail" in text or "exception" in text):
        return "search"
    if "harness_phase=filters" in text and ("fail" in text or "exception" in text):
        return "filters"
    if "search_input" in text or "xbrl_search" in text:
        return "search"
    if "filter" in text or "xbrl_filters" in text:
        return "filters"
    if "gvdata" in text or ("tbody tr" in text and "timeout" in text):
        return "empty_grid"
    if status == "timeout" or "harness_timeout" in text:
        return "timeout"
    return "unknown"


def save_generated_code(code: str, staging_path: Optional[Path] = None) -> Path:
    target = Path(staging_path) if staging_path else GENERATED_CODE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    if "ERROR: Generated code was not runnable" in (code or "") or "LLM RAW OUTPUT" in (code or ""):
        failed_path = CACHE_DIR / "failed_codegen_stub.py"
        failed_path.write_text(code, encoding="utf-8")
        raise RuntimeError(
            f"Coding agent produced non-runnable output; refused to write staging module. "
            f"Stub saved to {failed_path}"
        )
    if "class ResultsPortal" not in (code or "") or "PortalLocators" not in (code or ""):
        failed_path = CACHE_DIR / "failed_codegen_invalid_module.py"
        failed_path.write_text(code or "", encoding="utf-8")
        raise RuntimeError(
            f"Coding agent output missing ResultsPortal contract; refused to write staging. "
            f"Saved to {failed_path}"
        )
    stripped = (code or "").lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        failed_path = CACHE_DIR / "failed_codegen_json_dump.py"
        failed_path.write_text(code or "", encoding="utf-8")
        raise RuntimeError(
            f"Coding agent output looks like JSON, not Python; refused to write staging. "
            f"Saved to {failed_path}"
        )

    locator_errors = validate_portal_locators_kwargs(code)
    if locator_errors:
        failed_path = CACHE_DIR / "failed_codegen_locator_contract.py"
        failed_path.write_text(code or "", encoding="utf-8")
        raise RuntimeError(
            "PortalLocators contract violation: " + "; ".join(locator_errors)
        )

    target.write_text(code, encoding="utf-8")
    return target


def _extract_reasoning_from_text(raw: str) -> str:
    if not raw:
        return ""
    # Prefer REASONING: ... before the python fence
    fence = re.search(r"```(?:python|py)\b", raw, re.IGNORECASE)
    head = raw[: fence.start()] if fence else raw
    m = re.search(r"REASONING\s*:\s*(.*)", head, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()[:_MAX_THOUGHT_CHARS]
    # JSON-shaped fallback
    parsed = unwrap_llm_payload(raw)
    if isinstance(parsed, dict):
        reasoning = parsed.get("reasoning") or parsed.get("agent_thoughts")
        if reasoning is not None:
            if isinstance(reasoning, (dict, list)):
                return json.dumps(reasoning, ensure_ascii=False)[:_MAX_THOUGHT_CHARS]
            return str(reasoning)[:_MAX_THOUGHT_CHARS]
    return head.strip()[:_MAX_THOUGHT_CHARS]


def _extract_python_code_from_text(raw: str) -> str:
    if not isinstance(raw, str):
        return ""
    raw = raw.strip()
    if not raw:
        return ""

    # 1) Preferred: ```python ... ``` (even if closing fence missing / truncated)
    m = re.search(r"```(?:python|py)\s*\n(.*?)(?:```|$)", raw, re.DOTALL | re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        if candidate:
            return candidate

    # 2) Generic fence
    fenced = extract_code_from_markdown(raw)
    if fenced:
        return fenced

    # 3) JSON {"code": "..."}
    parsed = unwrap_llm_payload(raw)
    if isinstance(parsed, dict):
        for key in ("code", "script", "generated_code"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                inner = value.strip()
                if "```" in inner:
                    nested = extract_code_from_markdown(inner)
                    if nested:
                        return nested
                return inner

    # 4) Raw module text
    if any(
        keyword in raw
        for keyword in ("class ResultsPortal", "def ", "async def ", "from automation")
    ):
        # Drop a leading REASONING header if present
        if re.match(r"(?is)^\s*REASONING\s*:", raw):
            rest = re.split(r"(?is)^\s*REASONING\s*:.*?(?=\n(?:from |import |class ))", raw, maxsplit=1)
            if len(rest) == 2 and rest[1].strip():
                return rest[1].strip()
        return raw
    return ""


def _is_valid_python_code(code: str) -> bool:
    if not code or not isinstance(code, str):
        return False
    try:
        compile(code, "<generated>", "exec")
        return True
    except SyntaxError:
        return False


def parse_coding_agent_response(raw: Any) -> Tuple[str, str]:
    """
    Returns (reasoning, python_code).
    Raises RuntimeError if no valid Python module can be extracted.
    """
    if isinstance(raw, dict):
        reasoning = ""
        r = raw.get("reasoning") or raw.get("agent_thoughts")
        if r is not None:
            reasoning = (
                json.dumps(r, ensure_ascii=False)
                if isinstance(r, (dict, list))
                else str(r)
            )[:_MAX_THOUGHT_CHARS]
        for key in ("code", "script", "generated_code"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                code = _extract_python_code_from_text(value)
                if _is_valid_python_code(code):
                    return reasoning, code
        # Fall through: stringify and salvage
        raw = markdownify(raw)

    text = raw if isinstance(raw, str) else str(raw)
    reasoning = _extract_reasoning_from_text(text)
    code = _extract_python_code_from_text(text)
    if _is_valid_python_code(code):
        return reasoning, code

    FAILED_CODEGEN_RAW.write_text(text, encoding="utf-8")
    raise RuntimeError(
        "Coding agent returned non-Python output; refusing to stage. "
        f"Raw saved to {FAILED_CODEGEN_RAW}"
    )


def _field_lines(text: str) -> List[str]:
    lines: List[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("FIELD ") or " FIELD field=" in f" {stripped}":
            lines.append(stripped)
        elif "field=" in stripped and "action=" in stripped and "status=" in stripped:
            # tolerate harness / app-log variants without FIELD prefix
            lines.append(stripped)
    return lines


def _has_no_match_found_pass(text: str) -> bool:
    """True if suggestion_items logged No Match Found as status=pass (unsafe promote)."""
    for line in _field_lines(text):
        low = line.lower()
        if "field=suggestion_items" not in low:
            continue
        if "status=pass" not in low:
            continue
        if re.search(r"no\s*match\s*found", low):
            return True
    return False


def _scrip_bound_in_logs(text: str, test_input: str) -> bool:
    """
    Require FIELD evidence that autocomplete was selected (not inject-only):
    - suggestion_items click_first / click_match / keyboard_select, or
    - inject alone is NOT enough (leaves empty grid on live BSE).
    """
    scrip = (test_input or "").strip()
    saw_suggestion_select = False
    saw_scrip_type = False
    for line in _field_lines(text):
        low = line.lower()
        if "status=pass" not in low:
            continue
        if "field=search_input" in low and "action=type" in low:
            if not scrip or scrip.lower() in low or "type_symbol" in low:
                saw_scrip_type = True
        if "field=suggestion_items" not in low:
            continue
        if re.search(r"no\s*match\s*found", low):
            continue
        if any(
            act in low
            for act in (
                "action=click_first",
                "action=click_match",
                "action=keyboard_select",
                "action=click",
            )
        ):
            saw_suggestion_select = True
            if not scrip or scrip.lower() in low:
                return True
    # Real suggestion click after typing is enough even if value text lacks digits.
    return bool(saw_suggestion_select and (saw_scrip_type or not scrip))


def goal_was_achieved(
    stdout: str,
    runtime_log: str,
    goal: Optional[Any] = None,
    test_input: Optional[str] = None,
) -> bool:
    """
    Strict harness success: HEALED_MODULE_OK + real xbrl_url + autocomplete click proof.
    Reject inject-only runs (they produce empty grids after Submit).
    """
    text = f"{stdout or ''}\n{runtime_log or ''}"
    if "HEALED_MODULE_OK" not in text:
        return False
    if _has_no_match_found_pass(text):
        return False
    # Inject without suggestion click is a false success — reject.
    low = text.lower()
    if "inject_hidden_scrip" in low and "action=click_first" not in low and "keyboard_select" not in low:
        if "action=click_match" not in low:
            return False
    m = re.search(r"xbrl_url\s*=\s*(\S+)", text, re.IGNORECASE)
    if not m:
        return False
    url = m.group(1).strip().strip('"').strip("'")
    if not url or url.lower() in {"none", "null", ""}:
        return False
    if not url.lower().startswith("http"):
        return False
    scrip = (test_input or "").strip()
    if scrip and not _scrip_bound_in_logs(text, scrip):
        return False
    return True


def _invoke_coding_llm(prompt: str, *, ctx: Optional[HealRunContext] = None) -> Tuple[str, str]:
    raw = evaluate_with_azure_llm(
        prompt=prompt,
        cache_path=str(CODE_CACHE_FILE),
        max_tokens=_CODING_MAX_TOKENS,
        system=_coding_system(),
        parse_json=False,
        run_name="heal_coding",
        tags=["heal-agent", "coding"],
        metadata={"run_id": _run_id(ctx)},
    )
    reasoning, code = parse_coding_agent_response(raw)
    if reasoning:
        log_agent_thoughts("coding", reasoning, ctx=ctx, prefix="coding_reasoning")
    return reasoning, code


def generate_code_from_analysis(
    old_code: str,
    final_analysis: Any,
    new_url: str,
    feedback: Optional[str] = None,
    state_messages: Optional[list] = None,
    staging_path: Optional[Path] = None,
    ctx: Optional[HealRunContext] = None,
) -> Tuple[Path, str, str]:
    _status("[CODING AGENT] Generating code from analysis", ctx=ctx)
    prompt = build_coding_prompt(
        old_code, final_analysis, new_url, feedback, state_messages=state_messages
    )
    reasoning, code = _invoke_coding_llm(prompt, ctx=ctx)
    path = save_generated_code(code, staging_path=staging_path)
    FIRST_GENERATED_FILE.write_text(code, encoding="utf-8")
    if ctx:
        ctx.add_thought(
            "coding",
            summary=f"Wrote staging module ({path.name})",
            decisions=[reasoning] if reasoning else [f"staged={path}"],
        )
        ctx.log("codegen_written", path=str(path), bytes=path.stat().st_size)
    return path, reasoning, code


def regenerate_code_with_logs(
    old_code: str,
    final_analysis: Any,
    new_url: str,
    logs: str,
    runtime_log: str,
    state_messages: Optional[list] = None,
    staging_path: Optional[Path] = None,
    ctx: Optional[HealRunContext] = None,
    failure_phase: str = "unknown",
    last_coding_reasoning: str = "",
    first_generated_code: str = "",
    test_input: str = "",
    deterministic_base: str = "",
) -> Tuple[Path, str, str]:
    staging = Path(staging_path) if staging_path else GENERATED_CODE_FILE
    last_code = staging.read_text(encoding="utf-8") if staging.exists() else old_code
    if not first_generated_code and FIRST_GENERATED_FILE.exists():
        first_generated_code = FIRST_GENERATED_FILE.read_text(encoding="utf-8")

    _status(f"[CODING AGENT] Regenerating code (failure_phase={failure_phase})", ctx=ctx)
    prompt = build_regeneration_prompt(
        old_code,
        final_analysis,
        last_code,
        logs,
        runtime_log,
        new_url,
        state_messages=state_messages,
        failure_phase=failure_phase,
        last_coding_reasoning=last_coding_reasoning,
        first_generated_code=first_generated_code,
        test_input=test_input,
        deterministic_base=deterministic_base,
    )
    reasoning, code = _invoke_coding_llm(prompt, ctx=ctx)
    path = save_generated_code(code, staging_path=staging)
    if ctx:
        ctx.add_thought(
            "regen",
            summary=f"Regenerated staging module (phase={failure_phase})",
            decisions=[reasoning] if reasoning else [],
            warnings=["previous_attempt_failed", f"phase={failure_phase}"],
        )
        ctx.log(
            "codegen_regenerated",
            path=str(path),
            bytes=path.stat().st_size,
            failure_phase=failure_phase,
        )
    return path, reasoning, code


def run_generated_script(test_input: str = "INFY", staging_path: Optional[Path] = None) -> Dict[str, Any]:
    EXECUTION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        EXECUTION_LOG_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        # Fresh FIELD= lines for this harness run
        RUNTIME_LOG_FILE.write_text("", encoding="utf-8")
    except Exception:
        try:
            RUNTIME_LOG_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    module_path = Path(staging_path) if staging_path else GENERATED_CODE_FILE
    result = execute_generated_script(str(module_path), test_input)
    exit_code = result.get("exit_code", -1)
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    command = result.get("command", "")
    status = result.get("status", "failed")

    log_text = (
        f"COMMAND: {command}\n"
        f"EXIT_CODE: {exit_code}\n"
        f"STDOUT:\n{stdout}\n"
        f"STDERR:\n{stderr}\n"
    )
    EXECUTION_LOG_FILE.write_text(log_text, encoding="utf-8")

    runtime_log_text = ""
    if RUNTIME_LOG_FILE.exists():
        last_size = -1
        stable_count = 0
        for _ in range(8):
            try:
                size = RUNTIME_LOG_FILE.stat().st_size
            except Exception:
                size = -1
            if size == last_size and size > 0:
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= 2:
                break
            last_size = size
            time.sleep(0.25)
        try:
            runtime_log_text = RUNTIME_LOG_FILE.read_text(encoding="utf-8")
        except Exception:
            runtime_log_text = result.get("runtime_log", "")
    else:
        runtime_log_text = result.get("runtime_log", "")

    return {
        "status": status,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "command": command,
        "log_path": str(EXECUTION_LOG_FILE),
        "runtime_log_path": str(RUNTIME_LOG_FILE),
        "runtime_log": runtime_log_text,
    }


def build_langraph_coding_agent(
    ctx: Optional[HealRunContext] = None,
    *,
    deterministic_base: str = "",
) -> Any:
    staging_path = ctx.staging_path if ctx else GENERATED_CODE_FILE

    graph = StateGraph(
        state_schema=CodingAgentState,
        input_schema=CodingAgentState,
        output_schema=CodingAgentState,
    )

    def iteration_node(state: CodingAgentState, runtime: Any = None) -> CodingAgentState:
        state_messages = list(state.get("previous_thoughts") or [])
        attempt = state.get("attempt", 1)
        feedback = state.get("feedback")
        test_input = state.get("test_input", "INFY")
        last_reasoning = state.get("last_coding_reasoning") or ""
        first_code = state.get("first_generated_code") or ""
        det_base = state.get("deterministic_base") or deterministic_base or ""

        harness_log = state.get("last_harness_log") or state.get("execution_log") or ""
        runtime_log = state.get("last_runtime_log") or state.get("runtime_log") or ""

        try:
            if attempt == 1 and det_base:
                regen_logs = harness_log or state.get("execution_log") or ""
                generated_path, reasoning, code = regenerate_code_with_logs(
                    state["old_code"],
                    state["final_analysis"],
                    state["new_url"],
                    regen_logs,
                    runtime_log,
                    state_messages=state_messages,
                    staging_path=staging_path,
                    ctx=ctx,
                    failure_phase=state.get("failure_phase") or "unknown",
                    last_coding_reasoning=last_reasoning,
                    first_generated_code=det_base,
                    test_input=test_input,
                    deterministic_base=det_base,
                )
                first_code = det_base
            elif attempt == 1:
                generated_path, reasoning, code = generate_code_from_analysis(
                    det_base or state["old_code"],
                    state["final_analysis"],
                    state["new_url"],
                    feedback=feedback,
                    state_messages=state_messages,
                    staging_path=staging_path,
                    ctx=ctx,
                )
                first_code = code
            else:
                regen_logs = harness_log
                prior_exec = state.get("execution_log") or ""
                if prior_exec and prior_exec not in regen_logs:
                    regen_logs = (prior_exec + "\n\n" + regen_logs).strip()
                generated_path, reasoning, code = regenerate_code_with_logs(
                    state["old_code"],
                    state["final_analysis"],
                    state["new_url"],
                    regen_logs,
                    runtime_log,
                    state_messages=state_messages,
                    staging_path=staging_path,
                    ctx=ctx,
                    failure_phase=state.get("failure_phase") or "unknown",
                    last_coding_reasoning=last_reasoning,
                    first_generated_code=first_code,
                    test_input=test_input,
                    deterministic_base=det_base,
                )
                if not first_code:
                    first_code = code
        except Exception as gen_exc:
            err = f"CODEGEN_ERROR: {gen_exc}"
            phase = classify_harness_failure(err, err, status="failed")
            if ctx:
                ctx.log("codegen_error", attempt=attempt, error=str(gen_exc), failure_phase=phase)
                ctx.add_thought(
                    "coding" if attempt == 1 else "regen",
                    summary="Code generation failed",
                    warnings=[str(gen_exc)[:400]],
                )
            combined = f"{harness_log}\n\n{err}".strip() if harness_log else err
            thoughts = state_messages + [
                {
                    "agent": "coding",
                    "summary": "codegen_failed",
                    "decisions": [str(gen_exc)[:500]],
                    "warnings": [phase],
                }
            ]
            return {
                **state,
                "previous_thoughts": thoughts[-12:],
                "generated_path": str(staging_path),
                "execution_log": err,
                "runtime_log": runtime_log,
                "last_harness_log": harness_log,
                "last_runtime_log": runtime_log,
                "last_coding_reasoning": last_reasoning or str(gen_exc)[:_MAX_THOUGHT_CHARS],
                "first_generated_code": first_code,
                "stdout": "",
                "stderr": err,
                "exit_code": 1,
                "status": "failed",
                "goal_achieved": False,
                "failure_phase": phase,
            }

        execution = run_generated_script(test_input=test_input, staging_path=staging_path)
        plan = _plan_from_analysis(state.get("final_analysis"), state.get("new_url", ""))
        goal = plan.get("goal")
        goal_achieved = goal_was_achieved(
            execution["stdout"],
            execution["runtime_log"],
            goal=goal,
            test_input=test_input,
        )
        exec_blob = (execution.get("stdout", "") or "") + "\n" + (execution.get("stderr", "") or "")
        failure_phase = classify_harness_failure(
            exec_blob,
            execution.get("stderr", ""),
            status=str(execution.get("status") or ""),
        )
        if ctx:
            ctx.log(
                "harness_result",
                attempt=attempt,
                exit_code=execution.get("exit_code"),
                goal_achieved=goal_achieved,
                status=execution.get("status"),
                failure_phase=failure_phase,
            )

        thoughts = state_messages + [
            {
                "agent": "coding" if attempt == 1 else "regen",
                "summary": "harness_ok" if goal_achieved else f"harness_fail:{failure_phase}",
                "decisions": [reasoning] if reasoning else [],
                "warnings": [] if goal_achieved else [failure_phase, _clip(exec_blob, 400)],
            }
        ]

        return {
            **state,
            "previous_thoughts": thoughts[-12:],
            "generated_path": str(generated_path),
            "execution_log": exec_blob,
            "runtime_log": execution.get("runtime_log", ""),
            "last_harness_log": exec_blob,
            "last_runtime_log": execution.get("runtime_log", ""),
            "last_coding_reasoning": reasoning,
            "first_generated_code": first_code,
            "stdout": execution.get("stdout", ""),
            "stderr": execution.get("stderr", ""),
            "exit_code": execution.get("exit_code", -1),
            "status": execution.get("status", "failed"),
            "goal_achieved": goal_achieved,
            "failure_phase": failure_phase,
        }

    graph.add_node("iteration", iteration_node)
    graph.add_edge(START, "iteration")
    graph.set_finish_point("iteration")
    return graph.compile()


def autonomous_coding_agent(
    old_code: str,
    final_analysis: Any,
    new_url: str,
    test_input: str = "INFY",
    max_attempts: int = 5,
    ctx: Optional[HealRunContext] = None,
) -> Path:
    """
    Generate and test staging module until goal achieved or max attempts.
    Never writes production results_portal.py — only staging.

    Phase 0 (deterministic): merge ChangePlan locators + canonical fill_search without LLM.
    Phase 1+: LLM patches only if harness still fails.
    """
    plan = _plan_from_analysis(final_analysis, new_url)
    goal = plan.get("goal")
    warnings = validate_selector_uniqueness(plan)
    staging_path = ctx.staging_path if ctx else GENERATED_CODE_FILE

    deterministic_base = build_staging_module(old_code, plan)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_text(deterministic_base, encoding="utf-8")

    logging.info("Coding Agent: running deterministic merge harness")
    if ctx:
        ctx.add_thought(
            "merge",
            summary="Deterministic portal merge (ChangePlan locators + canonical fill_search)",
            decisions=[
                f"staging={staging_path}",
                f"locators={len(plan.get('contract_locators') or [])}",
            ],
        )
        ctx.log("deterministic_merge", path=str(staging_path), bytes=staging_path.stat().st_size)

    det_exec = run_generated_script(test_input=test_input, staging_path=staging_path)
    det_goal = goal_was_achieved(
        det_exec["stdout"],
        det_exec.get("runtime_log", ""),
        goal=goal,
        test_input=test_input,
    )
    if det_goal and det_exec.get("exit_code") == 0:
        logging.info("Deterministic merge passed harness — skipping LLM codegen")
        if ctx:
            ctx.add_thought(
                "coding",
                summary="Deterministic merge passed harness; staging ready for promote",
                decisions=[f"path={staging_path}"],
            )
        return staging_path

    logging.info("Deterministic merge failed harness — starting LLM coding loop")
    if ctx:
        ctx.add_thought(
            "coding",
            summary="Deterministic merge failed; LLM will patch locators/interactions",
            warnings=[classify_harness_failure(det_exec.get("stdout", ""), det_exec.get("stderr", ""))],
        )

    logging.info("Coding Agent Initialization goal=%s", goal)
    if ctx:
        ctx.add_thought(
            "coding",
            summary="Starting coding agent loop",
            decisions=[
                f"goal={goal}",
                f"contract={len(plan.get('contract_locators') or [])}",
                f"optional={len(plan.get('optional_controls') or [])}",
            ],
            warnings=warnings,
        )

    run_thoughts: List[Any] = []
    if ctx:
        run_thoughts = [t.to_dict() for t in ctx.thoughts]

    attempt = 1
    compiled_graph = build_langraph_coding_agent(ctx=ctx, deterministic_base=deterministic_base)
    state: CodingAgentState = {
        "old_code": old_code,
        "final_analysis": plan,
        "new_url": new_url,
        "feedback": diagnose_harness_failure(
            det_exec.get("stdout", ""),
            det_exec.get("runtime_log", ""),
            test_input=test_input,
        ),
        "previous_thoughts": run_thoughts,
        "attempt": attempt,
        "test_input": test_input,
        "deterministic_base": deterministic_base,
        "last_harness_log": (det_exec.get("stdout", "") or "") + "\n" + (det_exec.get("stderr", "") or ""),
        "last_runtime_log": det_exec.get("runtime_log", ""),
        "first_generated_code": deterministic_base,
        "last_coding_reasoning": "",
    }

    while attempt <= max_attempts:
        logging.info("Coding attempt %s/%s", attempt, max_attempts)
        state["attempt"] = attempt
        state["test_input"] = test_input
        if ctx:
            ctx_thoughts = [t.to_dict() for t in ctx.thoughts][-6:]
            loop_thoughts = list(state.get("previous_thoughts") or [])[-6:]
            merged = ctx_thoughts + [t for t in loop_thoughts if t not in ctx_thoughts]
            state["previous_thoughts"] = merged[-12:]

        graph_config = {
            "run_name": "heal_coding_graph",
            "tags": ["heal-agent", "coding", "langgraph"],
            "metadata": {
                "run_id": _run_id(ctx),
                "attempt": attempt,
                "test_input": test_input,
            },
        }
        state = compiled_graph.invoke(state, config=graph_config)
        generated_path = Path(state.get("generated_path", str(GENERATED_CODE_FILE)))
        exit_code = state.get("exit_code", -1)
        goal_achieved = bool(state.get("goal_achieved"))
        if not goal_achieved:
            goal_achieved = goal_was_achieved(
                state.get("stdout", ""),
                state.get("runtime_log", ""),
                goal=goal,
                test_input=test_input,
            )

        logging.info(
            "Attempt %s exit_code=%s goal_achieved=%s failure_phase=%s",
            attempt,
            exit_code,
            goal_achieved,
            state.get("failure_phase"),
        )

        if goal_achieved and exit_code == 0:
            if ctx:
                ctx.add_thought(
                    "coding",
                    summary="Harness succeeded; staging ready for promote",
                    decisions=[f"path={generated_path}"],
                )
            return generated_path

        if attempt >= max_attempts:
            raise RuntimeError(
                f"Coding agent failed after {max_attempts} attempts. "
                f"Exit code {exit_code}. Goal not achieved. See {EXECUTION_LOG_FILE}."
            )
        attempt += 1

    raise RuntimeError("Coding agent exited without success")
