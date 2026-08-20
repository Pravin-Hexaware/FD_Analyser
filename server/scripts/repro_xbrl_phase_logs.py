#!/usr/bin/env python3
"""
One-scrip repro for XBRL phase logging (navigate + fill_search only).

Does NOT call heal_results_portal / LLM agent. Uses existing venv Playwright.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

SERVER_SRC = Path(__file__).resolve().parents[1] / "src"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))

from playwright.async_api import async_playwright

from automation.results_portal import PlaywrightHealRequired, ResultsPortal
from services.batch_xbrl_finder import create_browser_and_context
from services.logging_service import logging_service

SCRIP = "500002"


async def main() -> int:
    session_path = logging_service.start_application_session(
        repro="xbrl_phase_logs",
        company=SCRIP,
        note="navigate+fill_search only; no LLM heal",
    )
    print(f"Session log: {session_path}")
    print(f"Application log: {logging_service.app_log_path}")

    portal = ResultsPortal()
    outcome = "unknown"
    heal_reason = None

    async with async_playwright() as p:
        browser, ctx = await create_browser_and_context(p)
        page = None
        try:
            page = await portal.prepare_page(ctx)
            await portal.navigate(page)
            try:
                await portal.fill_search(page, SCRIP)
                outcome = "search_success"
            except PlaywrightHealRequired as exc:
                heal_reason = str(exc)
                outcome = "heal_triggered"
                print(f"PlaywrightHealRequired (expected if selectors drifted): {exc}")
                if getattr(exc, "phase", None):
                    print(f"  phase={exc.phase}")
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            await ctx.close()
            await browser.close()

    app_log = logging_service.app_log_path.read_text(encoding="utf-8", errors="replace")
    # Check only the tail so older runs do not pollute assertions.
    tail = app_log[-12000:] if len(app_log) > 12000 else app_log

    checks = {
        "navigate_started": "KEYWORD=PHASE_XBRL_NAVIGATE | status=started" in tail,
        "navigate_terminal": (
            "KEYWORD=PHASE_XBRL_NAVIGATE | status=success" in tail
            or "KEYWORD=PHASE_XBRL_NAVIGATE | status=failed" in tail
        ),
        "search_started": "KEYWORD=PHASE_XBRL_SEARCH | status=started" in tail,
        "search_terminal": (
            "KEYWORD=PHASE_XBRL_SEARCH | status=success" in tail
            or "KEYWORD=PHASE_XBRL_SEARCH | status=failed" in tail
        ),
    }
    if outcome == "heal_triggered":
        checks["heal_trigger"] = "KEYWORD=PLAYWRIGHT_HEAL_TRIGGER" in tail

    print("--- log checks ---")
    for name, ok in checks.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print(f"outcome={outcome}" + (f" reason={heal_reason}" if heal_reason else ""))

    if not all(checks.values()):
        print("FAIL: missing expected phase terminal status / heal trigger in logs")
        return 1
    print("PASS: phase logs have terminal status" + (" and heal trigger" if outcome == "heal_triggered" else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
