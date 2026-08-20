import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import analysis_agent, coding_agent, dom_agent
from llm.azure_llm import parse_markdown_to_data
from services.logging_service import logging_service
from tools.screenshot_test import extract_dom_from_url


async def _run_heal_async(old_module_source: str, url: str, test_input: str = "500325") -> Path:
    logging_service.log_phase("agent_analysis", "started", target_url=url)
    understanding = analysis_agent.analyze_initial(old_module_source, url)

    logging_service.log_phase("agent_dom", "started", target_url=url)
    raw_dom = await extract_dom_from_url(url, headless=True)
    _, filtered_dom, dom_understanding = await dom_agent.run(raw_dom)

    final_result = analysis_agent.analyze_final(understanding, filtered_dom, dom_understanding, url)
    final_analysis_data: Any = final_result
    try:
        raw = analysis_agent.ANALYSIS_RESPONSE_FILE.read_text(encoding="utf-8")
        parsed = parse_markdown_to_data(raw)
        if isinstance(parsed, dict):
            final_analysis_data = parsed.get("final_analysis") or parsed
    except Exception:
        final_analysis_data = final_result

    logging_service.log_phase("agent_codegen", "started", target_url=url)
    generated_code_path = coding_agent.autonomous_coding_agent(old_module_source, final_analysis_data, url, test_input=test_input)
    logging_service.log_phase("agent_test", "success", generated_path=str(generated_code_path))
    return generated_code_path


def run_heal(old_module_source: str, url: str, test_input: str = "500325", target_output_path: Path | None = None) -> Path:
    generated_code_path = asyncio.run(_run_heal_async(old_module_source, url, test_input=test_input))
    if target_output_path and Path(generated_code_path) != target_output_path:
        target_output_path.write_text(Path(generated_code_path).read_text(encoding="utf-8"), encoding="utf-8")
        return target_output_path
    return Path(generated_code_path)


if __name__ == "__main__":
    sample_path = ROOT / "automation" / "results_portal.py"
    source = sample_path.read_text(encoding="utf-8") if sample_path.exists() else ""
    print(run_heal(source, "https://www.bseindia.com/corporates/comp_resultsnew"))
