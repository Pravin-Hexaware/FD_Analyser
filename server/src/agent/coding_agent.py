import json
import logging
import os
import sys
import time
import re
import ast
from pathlib import Path
from typing import Any, Dict, Optional
from typing_extensions import TypedDict

from langgraph.constants import START
from langgraph.graph import StateGraph
from llm.azure_llm import evaluate_with_azure_llm, extract_code_from_markdown, markdownify
from tools.executor import execute_generated_script

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

GENERATED_CODE_FILE = Path("automation/results_portal.py")
CODE_CACHE_FILE = CACHE_DIR / "code_generation.md"
EXECUTION_LOG_FILE = CACHE_DIR / "generated_code_run.log"
RUNTIME_LOG_FILE = CACHE_DIR / "generated_script_runtime.log"
LAST_AGENT_THOUGHTS: Optional[Any] = None
AGENT_STATE_MESSAGES: list[Dict[str, str]] = []


class CodingAgentState(TypedDict, total=False):
    old_code: str
    final_analysis: Any
    new_url: str
    feedback: Optional[str]
    previous_thoughts: list[Dict[str, str]]
    attempt: int
    test_input: str
    generated_path: str
    execution_log: str
    runtime_log: str
    stdout: str
    stderr: str
    exit_code: int
    status: str
    goal_achieved: bool


def build_coding_prompt(old_code: str, final_analysis: Any, new_url: str, feedback: Optional[str] = None, state_messages: Optional[list[Dict[str, str]]] = None) -> str:
    analysis_text = final_analysis
    mapping_text = None
    goal_text = None
    if isinstance(final_analysis, dict):
        goal_text = final_analysis.get("goal")
        elements = final_analysis.get("elements_to_replace")
        mapping = final_analysis.get("mapping")
        if elements is not None:
            payload = {"elements_to_replace": elements}
            if mapping is not None:
                payload["mapping"] = mapping
            analysis_text = markdownify(payload)
        else:
            analysis_text = markdownify(final_analysis)
        if mapping is not None:
            mapping_text = markdownify(mapping)

    return f"""
You are an expert Python Playwright module maintainer.

You are given:
1) The original Playwright portal module.
2) A final analysis describing UI behavior changes and replacement rules.
3) The target URL: {new_url}

GOAL: {goal_text or 'Use analysis to generate the updated script.'}

TASK:
- Return valid markdown output only, with no extra text.
- If you include code, wrap it in a fenced markdown code block (```python).
- Include a markdown section or bullet list for reasoning and agent thoughts.
- The code content should be provided as raw Python inside the code block, and any analysis or commentary should be in markdown sections.
- Rewrite the original module so it works against the updated UI.
- Use the provided analysis goal, element replacements, and mapping to choose the correct UI inputs and selectors.
- Use the single best selector provided for each element; do not generate or include a list of selectors.
- Ensure every selected selector is unique and matches exactly one visible target element in the current UI.
- Generate only the production-ready `results_portal.py` module that implements the existing portal contract methods.
- The generated module must configure Python logging and log exceptions with stack traces.
- The generated module must write a runtime action log file at cache/generated_script_runtime.log when exercised by the harness.
- If runtime log file writing fails, it must also print runtime action log lines to stdout with a distinct prefix like RUNTIME_ACTION_LOG.
- The runtime log must record each UI interaction step, the selector used, the action performed, and whether that action succeeded or failed.
- Additionally, the module must measure and record timings for every UI action and for table/grid loads:
    - Each runtime log entry must include an ISO8601 timestamp and a `duration_ms` field showing the elapsed time for the action.
    - For table/grid loads, record the time from the initiating action (click/submit) to the first valid row or anchor becoming visible and include `rows_count` when available.
    - Use `time.monotonic()` to compute durations and include explicit timeout markers when waits expire.
    - Ensure timing entries are machine-parseable (e.g., JSON lines) so they can be analyzed programmatically.
- The module must not depend on interactive stdin.
- If the harnessed module fails before achieving the goal, it must cause a nonzero process exit code.
- The module must not catch and swallow final errors in a way that returns exit code 0 on failure.
- Do not generate a standalone script, CLI, or main entrypoint.
        - Prefer robust selectors: when an element selector can match duplicates, scope selectors to a containing element or combine attributes to ensure uniqueness and verify connections between related elements.
        - For autocomplete / suggestion-driven inputs (type-to-search fields):
            - Prefer waiting for visible suggestion list items rather than relying solely on the container element, since duplicate or hidden containers may exist.
            - Prefer clicking a visible suggestion item; if no visible suggestion appears, fall back to keyboard navigation (repeat ArrowDown then Enter) and verify the selection by reading the input's value or other observed page changes.
            - Add short delays between keyboard navigation presses, limit iterations (for example, 3), and confirm the selection took effect before proceeding.
            - Log each attempt and fallback step to the runtime action log so failures are traceable.
        - When waiting for a results grid to change, do NOT rely on brittle innerHTML differences. Prefer waiting for row presence, anchors, or row-count changes and use explicit polling or anchored checks rather than raw HTML diffs.
        - After selecting any button, dropdown, or table control that triggers data loading, always wait for the real data to arrive before proceeding:
            - Immediately after the selection, include a short configurable delay (for example 0.5–2s) to avoid capturing default/placeholder UI data.
            - Then wait explicitly for concrete evidence of loaded data (visible rows, anchors, non-placeholder cell text, or increased row count) using polling up to a reasonable timeout.
            - If expected data does not appear, retry the selection up to a small number of times with incremental backoff, logging each attempt, wait duration, and outcome to the runtime action log.
            - Log the chosen wait time and whether the wait succeeded or expired; prefer waiting for content presence over fixed sleeps when possible.
- Do not include any explanatory text, markdown, or comments outside the Python code.

OLD SCRIPT:
{old_code}

ELEMENT REPLACEMENTS TO APPLY:
{analysis_text}

MAPPING FROM ANALYSIS:
{mapping_text or 'None'}

PREVIOUS HUMAN FEEDBACK:
{feedback or 'None'}

PREVIOUS AGENT THOUGHTS:
{format_state_messages(state_messages)}
"""


def save_generated_code(code: str) -> Path:
    GENERATED_CODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GENERATED_CODE_FILE, "w", encoding="utf-8") as f:
        f.write(code)
    return GENERATED_CODE_FILE


def print_agent_thoughts(result: Any, prefix: str = "[CODING AGENT THINKING]"):
    if isinstance(result, dict):
        thoughts = result.get("agent_thoughts")
        if thoughts:
            print(f"\n{prefix}")
            if isinstance(thoughts, (dict, list)):
                print(json.dumps(thoughts, indent=2))
            else:
                print(thoughts)


def append_agent_state_message(result: Any, source: str, state_messages: list[Dict[str, str]]) -> None:
    if isinstance(result, dict):
        thoughts = result.get("agent_thoughts")
        if thoughts:
            state_messages.append({
                "source": source,
                "agent_thoughts": thoughts,
            })


def format_state_messages(state_messages: Optional[list[Dict[str, str]]]) -> str:
    if not state_messages:
        return "None"
    return json.dumps(state_messages, indent=2)


def build_langraph_coding_agent() -> Any:
    graph = StateGraph(
        state_schema=CodingAgentState,
        input_schema=CodingAgentState,
        output_schema=CodingAgentState,
    )

    def iteration_node(state: CodingAgentState, runtime: Any) -> CodingAgentState:
        state_messages = state.get("previous_thoughts") or []
        attempt = state.get("attempt", 1)
        feedback = state.get("feedback")
        test_input = state.get("test_input", "INFY")

        if attempt == 1:
            generated_path = generate_code_from_analysis(
                state["old_code"],
                state["final_analysis"],
                state["new_url"],
                feedback=feedback,
                state_messages=state_messages,
            )
        else:
            logs = state.get("execution_log", "")
            runtime_log = state.get("runtime_log", "")
            generated_path = regenerate_code_with_logs(
                state["old_code"],
                state["final_analysis"],
                state["new_url"],
                logs,
                runtime_log,
                state_messages=state_messages,
            )

        execution = run_generated_script(test_input=test_input)
        goal = None
        if isinstance(state.get("final_analysis"), dict):
            goal = state["final_analysis"].get("goal")
        goal_achieved = goal_was_achieved(execution["stdout"], execution["runtime_log"], goal=goal)

        return {
            **state,
            "previous_thoughts": state_messages,
            "generated_path": str(generated_path),
            "execution_log": execution.get("stdout", "") + "\n" + execution.get("stderr", ""),
            "runtime_log": execution.get("runtime_log", ""),
            "stdout": execution.get("stdout", ""),
            "stderr": execution.get("stderr", ""),
            "exit_code": execution.get("exit_code", -1),
            "status": execution.get("status", "failed"),
            "goal_achieved": goal_achieved,
        }

    graph.add_node("iteration", iteration_node)
    graph.add_edge(START, "iteration")
    graph.set_finish_point("iteration")
    return graph.compile()


def _extract_python_code_from_text(raw: str) -> str:
    if not isinstance(raw, str):
        return ""
    raw = raw.strip()
    if not raw:
        return ""

    if "```python" in raw or "```py" in raw or raw.startswith("```"):
        code = extract_code_from_markdown(raw)
        if code:
            return code

    if any(keyword in raw for keyword in ("def ", "async def ", "import ", "from ", "class ", "await ", "async ", "playwright")):
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


def _build_error_script(raw_output: str) -> str:
    safe_raw = json.dumps(raw_output)
    return (
        "import os\n"
        "import sys\n"
        "os.makedirs('cache', exist_ok=True)\n"
        "with open('cache/generated_script_runtime.log', 'w', encoding='utf-8') as f:\n"
        "    f.write('ERROR: Generated code was not runnable.\\n')\n"
        "    f.write('LLM RAW OUTPUT:\\n')\n"
        f"    f.write({safe_raw} + '\\n')\n"
        "print('ERROR: Generated code was not runnable.')\n"
        "print('LLM RAW OUTPUT:')\n"
        f"print({safe_raw})\n"
        "sys.exit(1)\n"
    )


def extract_code_from_result(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("code", "script", "generated_code"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                candidate = _extract_python_code_from_text(value)
                if _is_valid_python_code(candidate):
                    return candidate
        for key in ("answer", "content"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                candidate = _extract_python_code_from_text(value)
                if _is_valid_python_code(candidate):
                    return candidate
        # if any string values exist, choose the longest one and attempt to extract code from it
        string_values = [v for v in result.values() if isinstance(v, str) and v.strip()]
        for value in sorted(string_values, key=len, reverse=True):
            candidate = _extract_python_code_from_text(value)
            if _is_valid_python_code(candidate):
                return candidate
        raw = result.get("answer") or result.get("content") or json.dumps(result, indent=2)
        return _build_error_script(str(raw))
    raw = str(result)
    candidate = _extract_python_code_from_text(raw)
    if _is_valid_python_code(candidate):
        return candidate
    return _build_error_script(raw)


def goal_was_achieved(stdout: str, runtime_log: str, goal: Optional[Any] = None) -> bool:
    """
    Detect if the automation goal was achieved.
    
    Goal achievement is determined by:
    1. Presence of success indicators in stdout/runtime_log (goal was accomplished)
    2. Absence of UNRECOVERED failures (script recovered or no FAIL markers found)
    3. Output evidence matching the goal
    
    Args:
        stdout: Standard output from the script
        runtime_log: Runtime action log showing step-by-step execution
        goal: Goal description from analysis (string, dict, or list)
    
    Returns:
        True if goal was achieved, False otherwise
    """
    stdout_lower = stdout.lower()
    runtime_log_lower = runtime_log.lower()

    success_indicators = [
        "healed_module_ok",
        "module_test_success",
        "run success",
        "xbrl_url=",
        "http",
    ]
    
    has_success_indicator = any(indicator in stdout_lower or indicator in runtime_log_lower for indicator in success_indicators)
    
    # If we have success indicators, check for uncovered failures
    if has_success_indicator:
        # Check if the last FAIL was recovered (i.e., there's a SUCCESS after it)
        if "| fail |" in runtime_log_lower:
            # Find the position of the last FAIL
            last_fail_pos = runtime_log_lower.rfind("| fail |")
            # Check if there's any SUCCESS after the last FAIL
            after_fail = runtime_log_lower[last_fail_pos:]
            if "| success |" in after_fail:
                # Script recovered after failure
                return True
            else:
                # Last operation was a failure - goal not achieved
                return False
        # No FAIL markers, just success indicators - goal achieved
        return True
    
    # Detect partial outcomes: rows saved but no anchors/XBRL => not a full success
    rl = runtime_log.lower() if runtime_log else ""
    if "saved rows to" in rl:
        # If anchors were explicitly reported and are zero, treat as failure
        m = re.search(r"anchors found in grid:\s*(\d+)", rl)
        if m and int(m.group(1)) == 0:
            return False
        # If a later select/click for anchors failed, treat as failure
        if "no anchors available" in rl or ("select selector" in rl and "success=false" in rl):
            return False

    # No success indicators found - normalize the goal if it is not a string
    if isinstance(goal, dict):
        goal = goal.get("goal") or goal.get("description") or json.dumps(goal, indent=2)
    elif isinstance(goal, list):
        goal = " ".join(str(item) for item in goal if item is not None)
    elif goal is not None:
        goal = str(goal)

    # If goal is specified, verify it appears in output/logs
    if goal and goal.strip():
        goal_lower = goal.lower().strip()
        
        # Check if any key words from goal appear in output
        goal_keywords = goal_lower.split()
        # Look for meaningful keywords (at least 3 chars, not articles/prepositions)
        meaningful_keywords = [
            kw for kw in goal_keywords 
            if len(kw) >= 3 and kw not in ("the", "and", "from", "into", "with", "for", "that")
        ]
        
        found_evidence = False
        if meaningful_keywords:
            for keyword in meaningful_keywords:
                if keyword in stdout_lower or keyword in runtime_log_lower:
                    found_evidence = True
                    break

        if not found_evidence:
            # Fallback: treat explicit success markers in runtime output as evidence
            if (
                "run success" in stdout_lower
                or "run success" in runtime_log_lower
                or "xbrl_url=" in stdout_lower
                or "xbrl_url=" in runtime_log_lower
                or "final result" in stdout_lower
                or "final result" in runtime_log_lower
            ):
                return True
            return False

        return True

    # If no goal is provided and no success indicators, do not assume success
    # As a final fallback, ask the LLM to judge success based on the provided logs.
    try:
        prompt = (
            "You are an automated judge. Given the following program output and runtime action log, "
            "return ONLY a JSON object with the keys: achieved (true/false), confidence (0..1 float), reason (short string).\n\n"
            f"STDOUT:\n" + stdout + "\n\n" +
            f"RUNTIME_LOG:\n" + runtime_log + "\n\n"
            "Return only JSON. Do not include any explanatory text."
        )
        llm_resp = evaluate_with_azure_llm(prompt=prompt, cache_path=str(CODE_CACHE_FILE))
        parsed = None
        # Try to robustly parse the LLM response
        if isinstance(llm_resp, dict):
            parsed = llm_resp
        else:
            text = str(llm_resp).strip()
            try:
                parsed = json.loads(text)
            except Exception:
                try:
                    parsed = ast.literal_eval(text)
                except Exception:
                    parsed = None

        if isinstance(parsed, dict):
            # Accept common boolean keys
            for key in ("achieved", "goal_achieved", "success"):
                if key in parsed:
                    try:
                        return bool(parsed.get(key))
                    except Exception:
                        return False
            # If explicit key not found, look for textual yes/no
            txt = json.dumps(parsed).lower()
            if "true" in txt and "false" not in txt:
                return True
            return False
    except Exception:
        # If LLM fallback fails, conservatively return False
        return False

    return False


def generate_code_from_analysis(old_code: str, final_analysis: Any, new_url: str, feedback: Optional[str] = None, state_messages: Optional[list[Dict[str, str]]] = None) -> Path:
    global LAST_AGENT_THOUGHTS
    state_messages = state_messages or []
    print("[CODING AGENT] Generating code from analysis")
    prompt = build_coding_prompt(old_code, final_analysis, new_url, feedback, state_messages=state_messages)
    result = evaluate_with_azure_llm(
        prompt=prompt,
        cache_path=str(CODE_CACHE_FILE)
    )
    print_agent_thoughts(result)
    if isinstance(result, dict):
        LAST_AGENT_THOUGHTS = result.get("agent_thoughts")
        append_agent_state_message(result, source="initial_generation", state_messages=state_messages)

    code = extract_code_from_result(result)
    generated_path = save_generated_code(code)
    return generated_path


def run_generated_script(test_input: str = "INFY") -> Dict[str, Any]:
    EXECUTION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Clear previous logs before each execution so regeneration uses only the latest diagnostics.
    try:
        EXECUTION_LOG_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        Path(RUNTIME_LOG_FILE).unlink(missing_ok=True)
    except Exception:
        pass

    result = execute_generated_script(str(GENERATED_CODE_FILE), test_input)
    exit_code = result.get("exit_code", -1)
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    command = result.get("command", f"{sys.executable} {GENERATED_CODE_FILE} {test_input}")
    status = result.get("status", "failed")

    log_text = (
        f"COMMAND: {command}\n"
        f"EXIT_CODE: {exit_code}\n"
        f"STDOUT:\n{stdout}\n"
        f"STDERR:\n{stderr}\n"
    )
    with open(EXECUTION_LOG_FILE, "w", encoding="utf-8") as f:
        f.write(log_text)

    runtime_log_text = ""
    runtime_log_path = str(RUNTIME_LOG_FILE)
    # If the runtime log file was written by the generated script, wait a short
    # time for it to stabilize (avoid reading a partially written file).
    if RUNTIME_LOG_FILE.exists():
        last_size = -1
        stable_count = 0
        # Poll for up to ~2 seconds (8 * 0.25s)
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
        "runtime_log_path": runtime_log_path,
        "runtime_log": runtime_log_text,
    }


def build_regeneration_prompt(old_code: str, final_analysis: Any, last_code: str, logs: str, runtime_log: str, new_url: str, state_messages: Optional[list[Dict[str, str]]] = None) -> str:
    analysis_text = final_analysis
    mapping_text = None
    goal_text = None
    if isinstance(final_analysis, dict):
        goal_text = final_analysis.get("goal")
        elements = final_analysis.get("elements_to_replace")
        mapping = final_analysis.get("mapping")
        payload = {}
        if elements is not None:
            payload["elements_to_replace"] = elements
        if mapping is not None:
            payload["mapping"] = mapping
        if payload:
            analysis_text = markdownify(payload)
        else:
            analysis_text = markdownify(final_analysis)
        if mapping is not None:
            mapping_text = markdownify(mapping)

    return f"""
You are an expert Python Playwright module maintainer and problem solver.

The previously generated portal module encountered errors during execution.
Analyze the failure, understand the root cause, and generate a FIXED version.

TARGET URL: {new_url}

GOAL: {goal_text or 'Achieve the goal defined in the analysis.'}

CRITICAL INSTRUCTION:
Continue regenerating and retesting until the goal is achieved.
Do NOT accept partial success - the goal must be fully completed.

FAILURE ANALYSIS:
1. Examine the RUNTIME ACTION LOG to identify which step FAILED (look for status=FAIL).
2. Understand the error (timeout, selector not found, element not visible, etc.).
3. Determine what was attempted and why it failed.
4. Consult ELEMENT REPLACEMENTS and MAPPING FROM ANALYSIS for alternative approaches.
5. Implement a FIXED version that addresses the root cause.

- If a selector failed:
- Try alternative selector from analysis
- Verify element is visible and accessible
- Add wait/retry logic
- Check if interaction method needs adjustment
- For autocomplete/suggestion failures specifically:
 - For autocomplete/suggestion failures specifically:
     - Prefer waiting for visible suggestion items first, then fall back to presence checks for list items if necessary.
     - If clicking suggestions consistently fails, implement a keyboard-navigation fallback (repeat a small number of down-arrow presses followed by Enter) and verify the selection by reading the input value or observing the resulting UI change.
     - Avoid relying on an unscoped "first" element when duplicate containers may exist; scope selection to the nearest logical container when possible.

OLD SCRIPT:
{old_code}

ELEMENT REPLACEMENTS TO APPLY:
{analysis_text}

MAPPING FROM ANALYSIS:
{mapping_text or 'None'}

LAST GENERATED MODULE:
{last_code}

EXECUTION LOGS:
{logs}

RUNTIME ACTION LOG:
{runtime_log}

PREVIOUS AGENT THOUGHTS:
{format_state_messages(state_messages)}

TASK:
- Return valid markdown output only, with no extra text.
- If you include code, wrap it in a fenced markdown code block (```python).
- Include a markdown section or bullet list summarizing what failed, why it failed, and how it was fixed.
- The code content should be provided as raw Python inside the code block, and any analysis or commentary should be in markdown sections.
- Regenerate the module addressing the identified failure.
- Use the single best selector provided for each element.
- Ensure every selected selector is unique and matches exactly one visible target element.
- Refer to the ELEMENT REPLACEMENTS and MAPPING directly for alternatives when a selector/interaction fails.
- New controls may be added or old controls may be removed; adapt the module according to the analysis rather than preserving old steps blindly.
- Include robust error handling, waits, and visibility checks.
- When implementing keyboard fallbacks (ArrowDown/Enter), limit iterations (e.g., 3) and verify selection by reading the input value or observing a visible selected suggestion.
            - When waiting for result-grid updates, prefer explicit checks such as waiting for rows or anchors to appear, or perform row-count polling to detect changes; avoid raw innerHTML comparisons.
            - After any click/selection of buttons, dropdowns, or table controls that trigger loading, follow the same wait-and-verify pattern described above: short configurable sleep, then explicit polling for loaded data, with retries and detailed runtime logging.
- Generate a complete `results_portal.py` module that implements the contract methods used by the production finder.
        - The module must write a runtime action log file to cache/generated_script_runtime.log when exercised by the harness.
        - If runtime log file writing fails, it must also print runtime log lines to stdout with a distinct prefix like RUNTIME_ACTION_LOG.
        - The module must log each step clearly to runtime_log so failures are visible.
        - Timing requirements:
            - Measure and log the elapsed time for every UI interaction (click/type/select) and every table/grid load or data refresh.
            - Log entries must include: ISO8601 timestamp, action name, selector, success/failure, duration_ms, and when relevant `rows_count` or `anchor_count`.
            - Use `time.monotonic()` to compute durations and include explicit timeout markers when waits expire.
            - Prefer JSON-lines format for timing entries so downstream tooling can parse them reliably.
- If the module fails before achieving the goal, the harness must exit with a nonzero process exit code.
- The module must not catch and swallow final errors in a way that returns exit code 0 on failure.
- Do not generate a standalone CLI or main function.
- Do not return any text outside the Python source code.
"""


def regenerate_code_with_logs(old_code: str, final_analysis: Any, new_url: str, logs: str, runtime_log: str, state_messages: Optional[list[Dict[str, str]]] = None) -> Path:
    global LAST_AGENT_THOUGHTS
    state_messages = state_messages or []
    with GENERATED_CODE_FILE.open("r", encoding="utf-8") as f:
        last_code = f.read()

    print("[CODING AGENT] Regenerating code with execution logs")
    prompt = build_regeneration_prompt(
        old_code,
        final_analysis,
        last_code,
        logs,
        runtime_log,
        new_url,
        state_messages=state_messages,
    )
    result = evaluate_with_azure_llm(
        prompt=prompt,
        cache_path=str(CODE_CACHE_FILE)
    )
    print_agent_thoughts(result)
    if isinstance(result, dict):
        LAST_AGENT_THOUGHTS = result.get("agent_thoughts")
        append_agent_state_message(result, source="regeneration", state_messages=state_messages)

    code = extract_code_from_result(result)
    generated_path = save_generated_code(code)
    return generated_path


def autonomous_coding_agent(old_code: str, final_analysis: Any, new_url: str, test_input: str = "INFY", max_attempts: int = 5) -> Path:
    """
    Autonomously generate and test code until goal is achieved or max attempts reached.
    
    Success criteria:
    1. Exit code == 0 (script completed without unhandled exception)
    2. Goal was achieved (extracted from final_analysis, verified in logs/stdout)
    
    Regeneration triggers:
    - Goal was NOT achieved, OR
    - Exit code != 0
    
    Each regeneration analyzes errors and attempts to fix them.
    """
    # Extract goal from analysis
    goal = None
    if isinstance(final_analysis, dict):
        goal = final_analysis.get("goal")
    
    logging.info(f"\n{'='*60}")
    logging.info(f"Coding Agent Initialization")
    logging.info(f"Goal: {goal}")
    logging.info(f"{'='*60}\n")
    
    attempt = 1
    compiled_graph = build_langraph_coding_agent()
    state: CodingAgentState = {
        "old_code": old_code,
        "final_analysis": final_analysis,
        "new_url": new_url,
        "feedback": None,
        "previous_thoughts": AGENT_STATE_MESSAGES,
        "attempt": attempt,
        "test_input": test_input,
    }
    execution = None

    while attempt <= max_attempts:
        logging.info(f"\n{'='*60}")
        logging.info(f"Attempt {attempt}/{max_attempts}")
        logging.info(f"{'='*60}")

        state["attempt"] = attempt
        state["test_input"] = test_input
        state = compiled_graph.invoke(state)
        AGENT_STATE_MESSAGES[:] = state.get("previous_thoughts", AGENT_STATE_MESSAGES)

        generated_path = Path(state.get("generated_path", "scripts/generated_script.py"))
        logging.info(f"Generated code: {generated_path}")

        execution = {
            "stdout": state.get("stdout", ""),
            "stderr": state.get("stderr", ""),
            "exit_code": state.get("exit_code", -1),
            "status": state.get("status", "failed"),
            "runtime_log": state.get("runtime_log", ""),
            "log_path": str(EXECUTION_LOG_FILE),
        }

        logging.info(f"Exit code: {execution['exit_code']}, Status: {execution['status']}")
        
        goal_achieved = state.get("goal_achieved", False)
        if not goal_achieved:
            # Fallback to explicit log-based detection if needed
            goal_achieved = goal_was_achieved(execution['stdout'], execution['runtime_log'], goal=goal)
        logging.info(f"Goal achieved: {goal_achieved}")
        
        # Success: goal achieved is confirmed and script exited cleanly
        if goal_achieved and execution['exit_code'] == 0:
            logging.info("\n" + "="*60)
            logging.info("SUCCESS: Goal achieved with exit code 0")
            if LAST_AGENT_THOUGHTS is not None:
                print_agent_thoughts({"agent_thoughts": LAST_AGENT_THOUGHTS}, prefix="[CODING AGENT FINAL THOUGHTS]")
            logging.info("="*60)
            return generated_path

        if goal_achieved and execution['exit_code'] != 0:
            logging.warning("\nGoal evidence was found, but the generated script exited with a nonzero code.")
            logging.warning("Continuing regeneration to secure a clean execution.")

        # Failure: prepare for regeneration or exit if max attempts
        if attempt < max_attempts:
            failure_reason = ""
            if execution['exit_code'] != 0:
                failure_reason = f"Exit code {execution['exit_code']}"
            if not goal_achieved:
                if failure_reason:
                    failure_reason += " AND goal not achieved"
                else:
                    failure_reason = "Goal not achieved"
            
            logging.warning(f"\nAttempt {attempt} failed: {failure_reason}")
            logging.warning(f"Will regenerate for attempt {attempt + 1}/{max_attempts}...\n")
        else:
            logging.error(f"\nMax attempts ({max_attempts}) reached. Goal not achieved.")
            failure_reason = ""
            if execution['exit_code'] != 0:
                failure_reason = f"Exit code {execution['exit_code']}. "
            failure_reason += "Goal not achieved."
            raise RuntimeError(
                f"Coding agent failed after {max_attempts} attempts. {failure_reason} See {EXECUTION_LOG_FILE} for details."
            )

        attempt += 1