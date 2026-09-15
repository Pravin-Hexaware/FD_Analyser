from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm.azure_llm import markdownify, parse_markdown_to_data
from services.logging_service import logging_service
from tools.screenshot_test import extract_dom_from_url, analyze_dom_combined

CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FILTERED_DOM_FILE = CACHE_DIR / "filtered_dom.md"
DOM_UNDERSTANDING_FILE = CACHE_DIR / "dom_understanding.md"
DOM_COMBINED_CACHE = CACHE_DIR / "dom_analysis_combined.md"


def save_markdown(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = markdownify(payload) if isinstance(payload, (dict, list)) else str(payload)
    path.write_text(text, encoding="utf-8")
    logging_service.log_runtime(f"[DOM AGENT] Saved {path}", echo=True)


def log_agent_thoughts(result: Any) -> None:
    if not isinstance(result, dict):
        return
    thoughts = result.get("agent_thoughts")
    if not thoughts:
        return
    logging_service.log_agent_thinking("dom", thoughts)


def build_filtered_dom(dom_data: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    logging_service.log_runtime(
        "[DOM AGENT] Sending full DOM + screenshot to LLM for combined analysis", echo=True
    )
    analysis = analyze_dom_combined(dom_data, cache_path=str(DOM_COMBINED_CACHE))
    log_agent_thoughts(analysis)

    if isinstance(analysis, str):
        parsed = parse_markdown_to_data(analysis)
        if isinstance(parsed, dict) and (
            "filtered_dom" in parsed or "dom_understanding" in parsed or "elements_to_replace" in parsed
        ):
            analysis = parsed
        else:
            analysis = {
                "filtered_dom": {
                    "source": "llm_dom_combined_markdown",
                    "url": dom_data.get("url"),
                    "markdown": analysis,
                    "raw_dom_summary": {
                        "cluster_count": len((dom_data.get("dom") or {}).get("clusters") or []),
                        "page_text_preview": (dom_data.get("text") or "")[:1000],
                    },
                },
                "dom_understanding": {
                    "source": "llm_dom_combined_markdown",
                    "markdown": analysis,
                    "page_text_preview": (dom_data.get("text") or "")[:1000],
                },
            }

    if not isinstance(analysis, dict):
        analysis = {
            "filtered_dom": {"raw": str(analysis)},
            "dom_understanding": {"raw": str(analysis)},
        }

    filtered_dom = analysis.get("filtered_dom", analysis)
    dom_understanding = analysis.get("dom_understanding", analysis)
    if not isinstance(filtered_dom, dict):
        filtered_dom = {"raw": filtered_dom}
    if not isinstance(dom_understanding, dict):
        dom_understanding = {"raw": dom_understanding}

    return filtered_dom, dom_understanding


async def run(full_dom_data: Dict[str, Any]):
    logging_service.log_runtime(
        "[DOM AGENT] Filtering provided full DOM markdown + screenshot", echo=True
    )
    # Do not persist Full_dom.md (large / redundant); LLM cache holds combined analysis.
    filtered_dom, dom_understanding = build_filtered_dom(full_dom_data)
    save_markdown(FILTERED_DOM_FILE, filtered_dom)
    save_markdown(DOM_UNDERSTANDING_FILE, dom_understanding)
    logging_service.log_runtime(f"[DOM AGENT] filtered_dom saved to {FILTERED_DOM_FILE}", echo=True)
    logging_service.log_runtime(
        f"[DOM AGENT] dom_understanding saved to {DOM_UNDERSTANDING_FILE}", echo=True
    )
    return full_dom_data, filtered_dom, dom_understanding


async def run_from_url(url: str, headless: bool = True):
    logging_service.log_runtime(f"[DOM AGENT] Extracting full DOM from URL: {url}", echo=True)
    dom_data = await extract_dom_from_url(url, headless=headless)
    return await run(dom_data)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_from_url("https://www.bseindia.com/corporates/comp_resultsnew", headless=True))
