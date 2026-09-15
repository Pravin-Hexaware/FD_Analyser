from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import importlib
import os
import threading
from pathlib import Path
from typing import Any, Optional

from services.logging_service import logging_service

from agent.heal_context import (
    LAST_PRE_HEAL,
    PRODUCTION_MODULE,
    HealRunContext,
    list_agent_runs,
    list_baselines,
    mark_last_good,
    read_agent_run,
    resolve_baseline,
    snapshot_pre_heal,
)

_HEAL_LOCK = threading.RLock()
_HEAL_IN_PROGRESS = False


class PlaywrightHealBatchHalt(RuntimeError):
    """
    Signals the Fetch Filings WS loop that Playwright UI drift needs attention.

    - ``needs_heal=True``: run the coding agent outside the per-company timeout,
      recreate the browser, retry the current company, then continue the batch.
    - ``healed_path`` set: heal already promoted; recreate browser and retry.
    - Otherwise: skip/fail the current company (or halt if heal itself failed).
    """

    def __init__(
        self,
        reason: str,
        *,
        company: Optional[str] = None,
        healed_path: Optional[Path] = None,
        needs_heal: bool = False,
        failed_phase: Optional[str] = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.company = company
        self.healed_path = healed_path
        self.needs_heal = needs_heal
        self.failed_phase = failed_phase


class BseWebsiteDown(RuntimeError):
    """BSE landing grid is empty / outage — notify user; do not run the heal agent."""

    def __init__(self, detail: str, *, company: Optional[str] = None):
        super().__init__(detail)
        self.detail = detail
        self.company = company


def is_heal_in_progress() -> bool:
    return _HEAL_IN_PROGRESS


def _probe_landing_site_health_sync(target_url: str) -> Any:
    """Blocking landing-grid probe for heal_results_portal (runs outside agent pipeline)."""
    from automation.results_portal import SiteHealth, WEBSITE_DOWN_DETAIL, is_site_down
    from services.batch_xbrl_finder import create_browser_and_context, check_bse_landing_site_health

    async def _probe():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser, ctx = await create_browser_and_context(p)
            try:
                return await check_bse_landing_site_health(ctx)
            finally:
                try:
                    await ctx.close()
                except Exception:
                    pass
                try:
                    await browser.close()
                except Exception:
                    pass

    try:
        health = asyncio.run(_probe())
    except Exception as exc:
        logging_service.log_phase(
            "site_health",
            "failed",
            target_url=target_url,
            error=str(exc),
            detail="heal_entry_probe_failed_allow_heal",
        )
        from automation.results_portal import SiteHealth

        return SiteHealth.GRID_MISSING

    if is_site_down(health):
        logging_service.log_phase(
            "playwright_heal_trigger",
            "skipped",
            target_url=target_url,
            reason="bse_downtime",
            detail=WEBSITE_DOWN_DETAIL,
        )
        raise BseWebsiteDown(WEBSITE_DOWN_DETAIL)

    return health


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


def rebind_portal() -> None:
    """Reload results_portal and rebind batch_xbrl_finder.PORTAL to a fresh instance."""
    import services.batch_xbrl_finder as finder

    results_portal_module = importlib.reload(importlib.import_module("automation.results_portal"))
    ResultsPortal = results_portal_module.ResultsPortal
    # Critical: also refresh the exception class so `except PlaywrightHealRequired`
    # matches raises from the reloaded portal (otherwise heal is swallowed as generic Exception).
    finder.PlaywrightHealRequired = results_portal_module.PlaywrightHealRequired
    finder.SiteHealth = results_portal_module.SiteHealth
    finder.WEBSITE_DOWN_DETAIL = results_portal_module.WEBSITE_DOWN_DETAIL
    finder.is_site_down = results_portal_module.is_site_down
    finder.PORTAL = ResultsPortal(
        TARGET_URL=getattr(finder, "BSE_URL", ResultsPortal.TARGET_URL),
        HOME_URL=getattr(finder, "BSE_HOME", ResultsPortal.HOME_URL),
        USER_AGENT=getattr(finder, "USER_AGENT", ResultsPortal.USER_AGENT),
        NAV_TIMEOUT=getattr(finder, "NAV_TIMEOUT", 25_000),
        GRID_TIMEOUT=getattr(finder, "GRID_TIMEOUT", 18_000),
        XHR_TIMEOUT=getattr(finder, "XHR_TIMEOUT", 12_000),
        POPUP_TIMEOUT=getattr(finder, "POPUP_TIMEOUT", 4_000),
        POST_CLICK_SETTLE_MS=getattr(finder, "POST_CLICK_SETTLE_MS", 600),
    )
    logging_service.log_phase(
        "agent_swap",
        "success",
        detail="rebound_batch_xbrl_finder_PORTAL",
        portal_type=type(finder.PORTAL).__name__,
        heal_exc=finder.PlaywrightHealRequired.__name__,
    )


def promote_staging_to_production(staging_path: Path, production_path: Path) -> Path:
    """Atomic-ish promote: write temp beside production, then replace."""
    production_path.parent.mkdir(parents=True, exist_ok=True)
    text = staging_path.read_text(encoding="utf-8")
    tmp = production_path.with_suffix(production_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(production_path)
    return production_path


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def revert_results_portal(snapshot_id: Optional[str] = None) -> dict:
    """Restore production portal from a baseline snapshot and rebind PORTAL."""
    global _HEAL_IN_PROGRESS
    with _HEAL_LOCK:
        if _HEAL_IN_PROGRESS:
            raise RuntimeError("Cannot revert while a heal is in progress")
        baseline = resolve_baseline(snapshot_id)
        text = baseline.read_text(encoding="utf-8")
        PRODUCTION_MODULE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PRODUCTION_MODULE.with_suffix(PRODUCTION_MODULE.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(PRODUCTION_MODULE)
        rebind_portal()
        logging_service.log_phase(
            "agent_swap",
            "success",
            detail="reverted_results_portal",
            baseline=str(baseline),
            restored_path=str(PRODUCTION_MODULE),
            sha256=_file_sha256(PRODUCTION_MODULE),
        )
        return {
            "restored_path": str(PRODUCTION_MODULE),
            "baseline": str(baseline),
            "bytes": PRODUCTION_MODULE.stat().st_size,
            "sha256": _file_sha256(PRODUCTION_MODULE),
        }


def _run_heal_locked(target_url: str, old_module_path: Path, test_input: str) -> Path:
    import os
    import sys

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    logging_service.log_phase(
        "agent_analysis",
        "started",
        target_url=target_url,
        test_input=test_input,
        module_path=str(old_module_path),
        detail="heal_agent_pipeline_begin",
    )
    from agent.orchestrator import run_heal

    module_path = Path(old_module_path)
    if not module_path.is_absolute():
        module_path = PRODUCTION_MODULE if module_path.name == "results_portal.py" else module_path

    ctx = HealRunContext(target_url=target_url, test_input=test_input, trigger_reason="playwright_heal")
    try:
        from utils.llm_testing import get_llm_provider_name, MODEL_DEPLOYMENT
        from services.analysis_service import get_llm_id

        provider = get_llm_provider_name()
        llm_id = None
        try:
            llm_id = get_llm_id()
        except Exception:
            llm_id = None
        ctx.log(
            "llm_provider",
            provider=provider,
            deployment=MODEL_DEPLOYMENT,
            llm_id=llm_id,
        )
        logging_service.log_phase(
            "agent_analysis",
            "progress",
            detail="heal_llm_provider",
            provider=provider,
            deployment=MODEL_DEPLOYMENT,
            llm_id=llm_id,
            run_id=ctx.run_id,
        )
    except Exception as llm_meta_exc:
        ctx.log("llm_provider", error=str(llm_meta_exc))

    baseline = snapshot_pre_heal(module_path, ctx.run_id)
    ctx.baseline_path = baseline
    ctx.log("baseline_snapshot", path=str(baseline))

    old_code = module_path.read_text(encoding="utf-8")
    logging_service.log_phase(
        "agent_analysis",
        "progress",
        target_url=target_url,
        test_input=test_input,
        old_code_bytes=len(old_code.encode("utf-8")),
        detail="loaded_results_portal_source",
        run_id=ctx.run_id,
    )

    try:
        generated_path = run_heal(
            old_code,
            target_url,
            test_input=test_input,
            target_output_path=None,  # promote only after success inside orchestrator/heal
            ctx=ctx,
        )
        # Promote staging → production only after coding agent success.
        staging = Path(generated_path)
        promote_staging_to_production(staging, module_path)
        mark_last_good(module_path)
        rebind_portal()
        ctx.promoted = True
        ctx.finish("success", promoted_path=str(module_path), staging=str(staging))
        logging_service.log_phase(
            "agent_swap",
            "success",
            swapped_path=str(module_path),
            test_input=test_input,
            detail="promoted_staging_and_reloaded_portal",
            run_id=ctx.run_id,
        )
        return module_path
    except Exception as exc:
        ctx.finish("failed", error=str(exc))
        raise


def heal_results_portal(target_url: str, old_module_path: Path, test_input: str) -> Path:
    """
    Run the analysis/DOM/codegen heal pipeline and promote only on success.

    Safe to call from a running asyncio loop (e.g. FastAPI WebSocket handlers):
    the pipeline is executed in a worker thread so asyncio.run inside orchestrator works.

    Concurrent heal requests are rejected immediately (PlaywrightHealBatchHalt) so the
    batch does not queue multiple full agent runs.
    """
    global _HEAL_IN_PROGRESS

    if os.environ.get("FINBOT_HEAL_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        raise RuntimeError("heal_results_portal called while FINBOT_HEAL_DISABLED=1")

    acquired = _HEAL_LOCK.acquire(blocking=False)
    if not acquired:
        logging_service.log_phase(
            "playwright_heal_trigger",
            "failed",
            target_url=target_url,
            test_input=test_input,
            detail="heal_already_in_progress",
            loop_action="skip_concurrent_heal",
        )
        raise PlaywrightHealBatchHalt(
            "heal_already_in_progress",
            company=test_input,
        )
    try:
        if _HEAL_IN_PROGRESS:
            raise PlaywrightHealBatchHalt(
                "heal_already_in_progress",
                company=test_input,
            )
        _HEAL_IN_PROGRESS = True
        try:
            logging_service.log_phase(
                "playwright_heal_trigger",
                "started",
                target_url=target_url,
                test_input=test_input,
                detail="probing_landing_grid_before_heal",
            )
            # Defense in depth: refuse coding agent when BSE default grid is empty.
            _probe_landing_site_health_sync(target_url)
            logging_service.log_phase(
                "playwright_heal_trigger",
                "started",
                target_url=target_url,
                test_input=test_input,
                detail="invoking_coding_heal_agent",
            )
            try:
                asyncio.get_running_loop()
                in_async = True
            except RuntimeError:
                in_async = False

            if in_async:
                logging_service.log_phase(
                    "agent_analysis",
                    "progress",
                    detail="heal_running_in_worker_thread",
                    reason="asyncio_event_loop_already_running",
                )
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="heal-agent"
                ) as pool:
                    generated_path = pool.submit(
                        _run_heal_locked, target_url, old_module_path, test_input
                    ).result()
            else:
                generated_path = _run_heal_locked(target_url, old_module_path, test_input)
            logging_service.log_phase(
                "playwright_heal_trigger",
                "success",
                target_url=target_url,
                test_input=test_input,
                swapped_path=str(generated_path),
            )
            return generated_path
        except BseWebsiteDown:
            raise
        except Exception as exc:
            logging_service.log_phase(
                "playwright_heal_trigger",
                "failed",
                target_url=target_url,
                test_input=test_input,
                error=str(exc),
                detail="heal_agent_pipeline_failed",
            )
            raise
        finally:
            _HEAL_IN_PROGRESS = False
    finally:
        _HEAL_LOCK.release()


# Re-export demo helpers for routes
__all__ = [
    "PlaywrightHealBatchHalt",
    "BseWebsiteDown",
    "classify_playwright_failure",
    "trigger_playwright_heal",
    "heal_results_portal",
    "revert_results_portal",
    "rebind_portal",
    "is_heal_in_progress",
    "list_baselines",
    "list_agent_runs",
    "read_agent_run",
    "LAST_PRE_HEAL",
    "PRODUCTION_MODULE",
]
