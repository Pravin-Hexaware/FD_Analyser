import asyncio
import json
import sys
from pathlib import Path
from typing import TypedDict, Optional, Any, Dict
from langgraph.graph import StateGraph, END

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm.azure_llm import evaluate_with_azure_llm, markdownify, parse_markdown_to_data


# =========================
# ✅ CACHE FILE
# =========================
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

ANALYSIS_FILE = CACHE_DIR / "Analysis.md"
ANALYSIS_RESPONSE_FILE = CACHE_DIR / "analysis_final.md"
OUTPUTS_INDEX = CACHE_DIR / "outputs_index.md"


# =========================
# ✅ STATE
# =========================
class AgentState(TypedDict):
    old_code: str
    new_url: str
    iteration: int
    analysis: Optional[str]
    feedback: Optional[str]


# =========================
# ✅ CACHE HELPERS
# =========================

def save_markdown(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(payload, (dict, list)):
            f.write(markdownify(payload))
        else:
            f.write(str(payload))
    print(f"[ANALYSIS AGENT] Saved {path}")


def update_outputs_index(updates: Dict[str, str]):
    data: Dict[str, str] = {}
    if OUTPUTS_INDEX.exists():
        try:
            data = load_markdown(OUTPUTS_INDEX)
        except Exception:
            data = {}
    data.update(updates)
    save_markdown(OUTPUTS_INDEX, data)


def print_agent_thoughts(result: Any, prefix: str = "[ANALYSIS AGENT THINKING]"):
    if isinstance(result, dict):
        thoughts = result.get("agent_thoughts")
        if thoughts:
            print(f"\n{prefix}")
            if isinstance(thoughts, (dict, list)):
                print(json.dumps(thoughts, indent=2))
            else:
                print(thoughts)


def load_markdown(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    parsed = parse_markdown_to_data(content)
    if parsed is None:
        raise ValueError(f"Unable to parse markdown cache at {path}")
    return parsed


# =========================
# ✅ ANALYSIS HELPERS
# =========================

def build_final_prompt(
    understanding: Dict[str, Any],
    filtered_dom: Dict[str, Any],
    dom_understanding: Dict[str, Any],
    new_url: str,
    feedback: Optional[str] = None
):
    structured_understanding = understanding.get("analysis")

    if isinstance(structured_understanding, dict):
        structured_understanding = markdownify(structured_understanding)

    structured_dom_understanding = dom_understanding
    if isinstance(structured_dom_understanding, dict):
        structured_dom_understanding = markdownify(structured_dom_understanding)

    return f"""
You are an expert automation migration analyst.

You are given:
1) Structured understanding of OLD SCRIPT (logic, flow, parameters)
2) FILTERED DOM of NEW PAGE (available UI elements)
3) DOM UNDERSTANDING from screenshot analysis (roles + selectors)

====================================
OLD SCRIPT STRUCTURED UNDERSTANDING:
{structured_understanding}
====================================

NEW PAGE FILTERED DOM:
{markdownify(filtered_dom)}
====================================

NEW PAGE DOM UNDERSTANDING:
{structured_dom_understanding}
====================================

NEW URL:
{new_url}

PREVIOUS HUMAN FEEDBACK:
{feedback or 'None'}
====================================

TASK:

Use structured reasoning to map the old automation to the new UI.
- Compare the old script intent and execution steps to the new page roles.
- Identify which selectors or UI inputs must change.
- Classify each changed step as exactly one of: `selector_drift`, `new_required_control`, `removed_control`, `merged_control`, or `unchanged`.
- For each element replacement, choose a single best selector, using a combined selector if needed to avoid duplicates.
- The chosen `best_selector` must be unique and target exactly one visible element in the new DOM.
- Prefer this uniqueness order: unique `#id`, then unique `[name=...]`, then `get_by_role`/label semantics, then container-scoped combined selectors.
- Avoid returning selector lists; provide one best selector per element in the output.
- If the selector is not unique, prefer a container-scoped or combined selector that guarantees uniqueness.
- If an old mandatory field is gone, mark it as `removed_control` and explain why it can be safely skipped.
- If a new required dropdown or input appears, mark it as `new_required_control` and choose the safest default option from the DOM.
- If two old steps map to one new control, mark them as `merged_control`.
- Explain why each replacement is required.

OUTPUT FORMAT:
- Return valid markdown output only, with no extra text.
- Use markdown headings and bullet lists for structure.
- If you need to provide machine-readable data, show it clearly in markdown sections.

Example structure:
- goal: ...
- mapping:
  - parameter_name: ...
    old_usage: ...
    new_dom_match: ...
    status: matched | changed | missing
    reason: ...
- elements_to_replace:
  - parameter: ...
    change_type: selector_drift | new_required_control | removed_control | merged_control | unchanged
    old_behavior: ...
    new_behavior: ...
    best_selector: ...
    visible_match_count: 1
    fallbacks:
      - id_selector: ...
      - class_selector: ...
      - combined_selector: ...
    reason: ...
- agent_thoughts: ...

RULES:
- RETURN ONLY MARKDOWN
- DO NOT OUTPUT RAW JSON
- DO NOT OUTPUT TEXT OUTSIDE MARKDOWN
- BE PRACTICAL
- ALWAYS EXPLAIN WHY
"""

def analyze_initial(old_code: str, new_url: str, feedback: Optional[str] = None) -> Dict[str, Any]:
    state = {
        "old_code": old_code,
        "new_url": new_url,
        "iteration": 1,
        "analysis": None,
        "feedback": feedback
    }
    result = analyze_code(state)
    understanding = {
        "old_code": old_code,
        "new_url": new_url,
        "analysis": result["analysis"],
        "iteration": 1,
        "feedback": feedback
    }
    save_markdown(ANALYSIS_FILE, understanding)
    update_outputs_index({
        "analysis_md": str(ANALYSIS_FILE)
    })
    return understanding


def analyze_final(understanding: Dict[str, Any], filtered_dom: Dict[str, Any], dom_understanding: Dict[str, Any], new_url: str, feedback: Optional[str] = None) -> Dict[str, Any]:
    prompt = build_final_prompt(understanding, filtered_dom, dom_understanding, new_url, feedback)
    result = evaluate_with_azure_llm(
        prompt=prompt,
        cache_path=str(CACHE_DIR / "analysis_final.md")
    )

    if isinstance(result, dict):
        agent_thoughts = result.get("agent_thoughts")
        if agent_thoughts:
            print("\n[ANALYSIS AGENT THINKING]")
            if isinstance(agent_thoughts, (dict, list)):
                print(json.dumps(agent_thoughts, indent=2))
            else:
                print(agent_thoughts)

    # Ask the LLM-generated analysis to include an `inferred_goal` describing
    # the expected output shape and success conditions of the old script.
    derived_goal = None
    if isinstance(result, dict):
        # Prefer explicit inferred_goal field from structured result
        derived_goal = result.get("inferred_goal") or result.get("goal")
    elif isinstance(result, str):
        # Try to parse markdown output to find a goal field
        try:
            parsed = parse_markdown_to_data(result)
            if isinstance(parsed, dict):
                derived_goal = parsed.get("inferred_goal") or parsed.get("goal")
        except Exception:
            derived_goal = None

    final_result = {
        "goal": derived_goal or new_url,
        "old_script_inferred_goal": derived_goal,
        "final_analysis": result,
        "iteration": 1,
        "feedback": feedback
    }
    save_markdown(ANALYSIS_RESPONSE_FILE, final_result)
    update_outputs_index({
        "analysis_final_md": str(ANALYSIS_RESPONSE_FILE)
    })
    return final_result


# =========================
# ✅ ANALYSIS NODE
# =========================
def analyze_code(state: AgentState):
    prompt = """
You are an expert Playwright automation analyst.

Your task is to convert a raw automation script into a structured abstraction.

====================================
OLD SCRIPT:
<<OLD_CODE>>
====================================

NEW URL:
<<NEW_URL>>

PREVIOUS HUMAN FEEDBACK:
<<FEEDBACK>>
====================================

TASK:

Break down the script into structured understanding.

OUTPUT FORMAT:
- Return valid markdown output only, with no extra text.
- Use markdown headings, bullet lists, and code fences for structure.
- Prefer readable markdown sections for intent, steps, techniques, details, and agent thoughts.

Example structure:
- intent: ...
- steps:
  - ...
  - ...
- techniques:
  - ...
- details:
  - flow:
    - ...
  - steps_detailed:
    - step: ...
      action: ...
      element_type: ...
      selector_used: ...
      purpose: ...
  - parameters_used:
    - parameter_name: ...
      value: ...
      type: input | dropdown | api | hidden_field | selector
      purpose: ...
  - approach_type: UI | API | HYBRID
  - reusable_components:
    - ...
  - non_reusable_components:
    - ...
- agent_thoughts: ...
"""
    prompt = prompt.replace("<<OLD_CODE>>", state['old_code'])
    prompt = prompt.replace("<<NEW_URL>>", state['new_url'])
    feedback_value = state.get('feedback') if state.get('feedback') is not None else 'None'
    prompt = prompt.replace("<<FEEDBACK>>", feedback_value)

    result = evaluate_with_azure_llm(
        prompt=prompt,
        cache_path="cache/analysis_agent_initial.md"
    )

    print_agent_thoughts(result)

    return {
        "analysis": result
    }



# =========================
# ✅ HUMAN LOOP
# =========================
def human_loop(state: AgentState):
    print("\n============================")
    print(f"🔁 ITERATION: {state['iteration']}")
    print("============================\n")

    print(state["analysis"])

    feedback = input("\n👉 Enter feedback (type 'ok' if satisfied): ")

    return {
        "feedback": feedback,
        "iteration": state["iteration"] + 1
    }


# =========================
# ✅ ITERATIVE ANALYSIS LOOPS
# =========================

def initial_analysis_loop(old_code: str, new_url: str):
    iteration = 1
    feedback = None

    while True:
        state = {
            "old_code": old_code,
            "new_url": new_url,
            "iteration": iteration,
            "analysis": None,
            "feedback": feedback
        }
        result = analyze_code(state)
        analysis = result.get("analysis")

        print("\n============================")
        print(f"🔍 INITIAL ANALYSIS ITERATION: {iteration}")
        print("============================\n")
        print(analysis)

        feedback = input("\n👉 Enter feedback for initial analysis (type 'ok' if satisfied): ")
        understanding = {
            "old_code": old_code,
            "new_url": new_url,
            "analysis": analysis,
            "iteration": iteration,
            "feedback": feedback
        }
        save_markdown(ANALYSIS_FILE, understanding)

        if feedback.strip().lower() == "ok":
            return understanding

        iteration += 1
        print("[ANALYSIS AGENT] Re-running initial analysis with human feedback...\n")


def final_analysis_loop(understanding: Dict[str, Any], filtered_dom: Dict[str, Any], dom_understanding: Dict[str, Any], new_url: str):
    iteration = 1
    feedback = None

    while True:
        result = analyze_final(understanding, filtered_dom, dom_understanding, new_url, feedback)
        analysis = result.get("final_analysis")

        print("\n============================")
        print(f"🔍 FINAL ANALYSIS ITERATION: {iteration}")
        print("============================\n")
        print(json.dumps(analysis, indent=2) if isinstance(analysis, dict) else analysis)

        feedback = input("\n👉 Enter feedback for final analysis (type 'ok' if satisfied): ")
        final_state = {
            "understanding": understanding,
            "filtered_dom": filtered_dom,
            "dom_understanding": dom_understanding,
            "analysis": analysis,
            "iteration": iteration,
            "feedback": feedback
        }
        save_markdown(ANALYSIS_RESPONSE_FILE, final_state)

        if feedback.strip().lower() == "ok":
            return final_state

        iteration += 1
        print("[ANALYSIS AGENT] Re-running final analysis with human feedback...\n")


# =========================
# ✅ LOOP CONTROL
# =========================
def should_continue(state: AgentState):
    if state["feedback"].strip().lower() == "ok":
        return "end"
    return "analyze"


# =========================
# ✅ BUILD GRAPH
# =========================
def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("analyze", analyze_code)
    builder.add_node("human", human_loop)

    builder.set_entry_point("analyze")

    builder.add_edge("analyze", "human")

    builder.add_conditional_edges(
        "human",
        should_continue,
        {
            "analyze": "analyze",
            "end": END
        }
    )

    return builder.compile()


# =========================
# ✅ MAIN
# =========================
async def main():
    old_script_path = r"C:\Users\2000166072\PycharmProjects\Analysis_Agent\scripts\old_script1.py"

    if not Path(old_script_path).exists():
        print("❌ File not found")
        return

    old_code = Path(old_script_path).read_text(encoding="utf-8")

    new_url = "https://www.bseindia.com/corporates/comp_resultsnew"

    graph = build_graph()

    await graph.ainvoke({
        "old_code": old_code,
        "new_url": new_url,
        "iteration": 1,
        "analysis": None,
        "feedback": None
    })


# =========================
# ✅ RUN
# =========================
if __name__ == "__main__":
    asyncio.run(main())