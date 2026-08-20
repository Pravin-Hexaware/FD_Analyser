from __future__ import annotations

import importlib
import threading
from pathlib import Path
from typing import Optional

from automation.results_portal import PlaywrightHealRequired
from services.logging_service import logging_service

_HEAL_LOCK = threading.RLock()


def classify_playwright_failure(error: Exception | str) -> str:
    text = str(error).lower()
    transient_markers = ("403", "networkidle", "net::", "timeout 30000", "connection")
    if any(marker in text for marker in transient_markers):
        return "transient"
    ui_drift_markers = ("selector", "strict mode", "option", "visible", "grid", "submit", "search")
    if any(marker in text for marker in ui_drift_markers):
        return "ui_drift"
    return "unknown"


def trigger_playwright_heal(reason: str, *, company: Optional[str] = None, target_url: Optional[str] = None) -> None:
    logging_service.log_heal_trigger(reason, company=company, target_url=target_url)


def heal_results_portal(target_url: str, old_module_path: Path, test_input: str) -> Path:
    with _HEAL_LOCK:
        logging_service.log_phase("agent_analysis", "started", target_url=target_url, test_input=test_input)
        from agent.orchestrator import run_heal

        old_code = old_module_path.read_text(encoding="utf-8")
        generated_path = run_heal(old_code, target_url, test_input=test_input, target_output_path=old_module_path)
        import automation.results_portal as results_portal_module

        importlib.reload(results_portal_module)
        logging_service.log_phase("agent_swap", "success", swapped_path=str(generated_path))
        return generated_path
