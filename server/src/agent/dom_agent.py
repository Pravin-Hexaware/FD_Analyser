import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm.azure_llm import markdownify, parse_markdown_to_data
from tools.screenshot_test import extract_dom_from_url, analyze_dom_combined

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

FULL_DOM_FILE = CACHE_DIR / "Full_dom.md"
FILTERED_DOM_FILE = CACHE_DIR / "filtered_dom.md"
DOM_UNDERSTANDING_FILE = CACHE_DIR / "dom_understanding.md"
OUTPUTS_INDEX = CACHE_DIR / "outputs_index.md"


def save_markdown(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(payload, (dict, list)):
            f.write(markdownify(payload))
        else:
            f.write(str(payload))
    print(f"[DOM AGENT] Saved {path}")


def load_markdown(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    parsed = parse_markdown_to_data(content)
    if parsed is None:
        raise ValueError(f"Unable to parse markdown cache at {path}")
    return parsed


def update_outputs_index(updates: Dict[str, str]):
    data: Dict[str, str] = {}
    if OUTPUTS_INDEX.exists():
        try:
            data = load_markdown(OUTPUTS_INDEX)
        except Exception:
            data = {}
    data.update(updates)
    with open(OUTPUTS_INDEX, "w", encoding="utf-8") as f:
        if isinstance(data, (dict, list)):
            f.write(markdownify(data))
        else:
            f.write(str(data))


def print_agent_thoughts(result: Any, prefix: str = "[DOM AGENT THINKING]"):
    if isinstance(result, dict):
        thoughts = result.get("agent_thoughts")
        if thoughts:
            print(f"\n{prefix}")
            if isinstance(thoughts, (dict, list)):
                print(json.dumps(thoughts, indent=2))
            else:
                print(thoughts)


def build_filtered_dom(dom_data: Dict[str, Any]) -> Dict[str, Any]:
    print("[DOM AGENT] Sending full DOM + screenshot to LLM for combined analysis")
    analysis = analyze_dom_combined(dom_data, cache_path=str(CACHE_DIR / "dom_analysis_combined.md"))
    print_agent_thoughts(analysis)
    
    filtered_dom = analysis.get("filtered_dom", {})
    dom_understanding = analysis.get("dom_understanding", {})
    
    return filtered_dom, dom_understanding


def load_full_dom(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    parsed = parse_markdown_to_data(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"Unable to parse markdown cache at {path}")
    return parsed


async def run(full_dom_data: Dict[str, Any]):
    print("[DOM AGENT] Filtering provided full DOM markdown + screenshot")
    save_markdown(FULL_DOM_FILE, full_dom_data)

    filtered_dom, dom_understanding = build_filtered_dom(full_dom_data)
    save_markdown(FILTERED_DOM_FILE, filtered_dom)
    save_markdown(DOM_UNDERSTANDING_FILE, dom_understanding)

    update_outputs_index({
        "full_dom_md": str(FULL_DOM_FILE),
        "filtered_dom_md": str(FILTERED_DOM_FILE),
        "dom_understanding_md": str(DOM_UNDERSTANDING_FILE)
    })

    print(f"[DOM AGENT] full_dom saved to {FULL_DOM_FILE}")
    print(f"[DOM AGENT] filtered_dom saved to {FILTERED_DOM_FILE}")
    print(f"[DOM AGENT] dom_understanding saved to {DOM_UNDERSTANDING_FILE}")
    return full_dom_data, filtered_dom, dom_understanding


async def run_from_url(url: str, headless: bool = True):
    print(f"[DOM AGENT] Extracting full DOM from URL: {url}")
    dom_data = await extract_dom_from_url(url, headless=headless)
    return await run(dom_data)


if __name__ == "__main__":
    asyncio.run(run_from_url("https://www.bseindia.com/corporates/comp_resultsnew", headless=True))
