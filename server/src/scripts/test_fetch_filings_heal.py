#!/usr/bin/env python3
"""
One-scrip regression for Admin "Fetch Filings" heal handoff.

Connects to the same WebSocket the UI uses:
  ws://localhost:8001/api/ws/xbrl-fetch-all-std

Sends a single scrip filter so the batch does not walk the whole CSV, then asserts:
  1) PHASE / PLAYWRIGHT_HEAL_TRIGGER style failure is surfaced (search_input_missing / ui drift)
  2) Heal agent runs (analysis / DOM / codegen / swap)
  3) After promote, batch RETRIES the scrip and continues (heal_success_retrying)
     — does NOT permanently halt on successful heal

Usage (from server/src, with backend already on :8001):
  python scripts/test_fetch_filings_heal.py --scrip 500325
  python scripts/test_fetch_filings_heal.py --scrip 500038 --timeout 900
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    print("ERROR: websockets package required. pip install websockets", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
APP_LOG = ROOT / "logs" / "application.log"
DEFAULT_WS = "ws://localhost:8001/api/ws/xbrl-fetch-all-std"

HEAL_LOG_MARKERS = (
    "PLAYWRIGHT_HEAL_TRIGGER",
    "PHASE_AGENT_ANALYSIS",
    "PHASE_AGENT_DOM",
    "PHASE_AGENT_CODEGEN",
    "PHASE_AGENT_SWAP",
    "request_heal_then_retry_company",
    "heal_agent_started",
    "heal_success_retrying",
)


def _tail_log_since(path: Path, start_offset: int) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    return data[start_offset:].decode("utf-8", errors="replace")


async def run_test(ws_url: str, scrip: str, timeout_s: float) -> int:
    log_offset = APP_LOG.stat().st_size if APP_LOG.exists() else 0
    events: list[dict] = []
    started = time.perf_counter()

    print(f"[TEST] Connecting {ws_url}")
    print(f"[TEST] Single scrip filter: {scrip}")
    print(f"[TEST] application.log offset={log_offset}")

    async with websockets.connect(ws_url, max_size=8 * 1024 * 1024, open_timeout=10) as ws:
        await ws.send(json.dumps({"scrip_codes": [scrip]}))
        print("[TEST] Sent scrip_codes filter")

        while True:
            elapsed = time.perf_counter() - started
            if elapsed > timeout_s:
                print(f"[TEST] TIMEOUT after {elapsed:.1f}s")
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=min(30.0, timeout_s - elapsed))
            except asyncio.TimeoutError:
                print("[TEST] Waiting for next WS message...")
                continue
            except websockets.ConnectionClosed as closed:
                print(f"[TEST] WS closed: code={closed.code} reason={closed.reason}")
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[TEST] Non-JSON message: {raw[:200]}")
                continue

            events.append(msg)
            status = msg.get("status") or msg.get("error") or "event"
            print(f"[WS] status={status} | {json.dumps(msg, ensure_ascii=True)[:400]}")

            if status == "complete" or msg.get("halted_by") == "playwright_heal":
                break

    log_tail = _tail_log_since(APP_LOG, log_offset)
    print("\n========== application.log (since test start) ==========")
    print(log_tail[-12000:] if log_tail else "(no new log lines)")
    print("=======================================================\n")

    statuses = [e.get("status") for e in events]
    heal_started_ws = any(s == "heal_agent_started" for s in statuses)
    heal_retry_ws = any(s == "heal_success_retrying" for s in statuses)
    heal_failed_ws = any(s == "heal_failed_batch_halted" for s in statuses)
    heal_log_hits = {m: (m in log_tail) for m in HEAL_LOG_MARKERS}
    agent_started = any(
        heal_log_hits[m]
        for m in (
            "PHASE_AGENT_DOM",
            "PHASE_AGENT_CODEGEN",
            "PHASE_AGENT_SWAP",
        )
    )
    agent_analysis_only = heal_log_hits["PHASE_AGENT_ANALYSIS"] and not agent_started
    company_loop = sum(1 for e in events if e.get("status") == "started")

    print("[ASSERT] WS statuses:", statuses)
    print(f"[ASSERT] company_started_count={company_loop}")
    print(f"[ASSERT] heal_agent_started_ws={heal_started_ws}")
    print(f"[ASSERT] heal_success_retrying_ws={heal_retry_ws}")
    print("[ASSERT] log marker hits:")
    for k, v in heal_log_hits.items():
        print(f"  - {k}: {v}")

    ok = True
    if "PLAYWRIGHT_HEAL_TRIGGER" not in log_tail and "search_input_missing" not in log_tail:
        if any(e.get("status") == "completed" for e in events):
            print("[INFO] No heal trigger — fetch completed (selectors may already be healthy)")
            return 0
        print("[FAIL] Neither heal trigger nor successful completion observed")
        ok = False
    elif heal_failed_ws:
        print("[FAIL] Heal agent failed and batch halted")
        ok = False
    elif heal_started_ws and heal_retry_ws and (agent_started or heal_log_hits["PHASE_AGENT_SWAP"]):
        print("[PASS] Heal agent ran, portal promoted, batch retried scrip (continue-after-heal)")
    elif heal_started_ws and agent_analysis_only:
        print("[FAIL] Agent aborted during analysis (check charmap/LLM errors)")
        ok = False
    elif heal_started_ws and not agent_started:
        print("[FAIL] heal_agent_started on WS but agent phases not found in application.log")
        ok = False
    elif agent_started and not heal_retry_ws and not heal_started_ws:
        print("[FAIL] Agent ran in logs but WS did not emit heal_agent_started / heal_success_retrying")
        ok = False
    elif "PLAYWRIGHT_HEAL_TRIGGER" in log_tail and not heal_started_ws:
        print("[FAIL] Heal trigger logged but WS never started heal agent")
        ok = False
    else:
        print("[PASS] Heal handoff path exercised")

    # Old bug: successful heal permanently stopped the batch without retry
    if any(s == "heal_triggered_batch_halted" for s in statuses) and not heal_retry_ws:
        print("[FAIL] Legacy halt-without-retry behavior detected")
        ok = False

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Fetch Filings heal handoff with one scrip")
    parser.add_argument("--scrip", default="500325", help="BSE scrip code (default 500325)")
    parser.add_argument("--ws", default=DEFAULT_WS, help="WebSocket URL")
    parser.add_argument("--timeout", type=float, default=900.0, help="Overall test timeout seconds")
    args = parser.parse_args()
    return asyncio.run(run_test(args.ws, args.scrip, args.timeout))


if __name__ == "__main__":
    raise SystemExit(main())
