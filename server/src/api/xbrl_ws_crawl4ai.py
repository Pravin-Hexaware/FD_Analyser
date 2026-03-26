#!/usr/bin/env python3
"""
WebSocket endpoint wrappers for XBRL operations using Crawl4AI.

Provides streaming updates during XBRL link fetching and extraction.
Replaces the complex Playwright logic in xbrl_ws_route.py with efficient Crawl4AI calls.
"""

import csv
import asyncio
import logging
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from repository.sqlite_repository import SqliteRepository
from api.crawl4ai_wrapper import fetch_xbrl_with_crawl4ai
from service.html_extraction_service import extract_html_data
from service.xml_extraction_service import extract_xbrl_data
from api.xbrl_route import calculate_metrics, extract_annual
from api.Xbrl_annual_extractor import calculate_metrics_fourd

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/xbrl-fetch-latest-crawl4ai")
async def websocket_xbrl_fetch_crawl4ai(websocket: WebSocket) -> None:
    """
    WebSocket endpoint using Crawl4AI for efficient XBRL link fetching.
    
    Reads companies from CSV, fetches XBRL URLs using Crawl4AI, 
    and stores them in SQLite with streaming updates.
    
    Much faster and more efficient than Playwright version.
    """
    await websocket.accept()

    csv_path = Path(__file__).resolve().parents[1] / "Data" / "Company_metadata.csv"
    if not csv_path.exists():
        await websocket.send_json({"error": f"CSV file not found: {csv_path}"})
        await websocket.close()
        return

    repo = SqliteRepository()
    start_time = datetime.utcnow()

    try:
        await websocket.send_json({"status": "starting", "csv_path": str(csv_path)})

        # Read CSV once
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records = [r for r in reader if r.get("Scrip-code")]

        total_records = len(records)
        await websocket.send_json(
            {"status": "read_csv", "records": total_records, "timestamp": datetime.utcnow().isoformat()}
        )

        # Determine resume point based on recent (<=10 days) xbrl filing entries
        start_idx = 0
        now = datetime.utcnow()
        for idx, row in enumerate(records):
            scrip_code = (row.get("Scrip-code") or "").strip()
            if not scrip_code:
                continue
            try:
                if not repo.xbrl_filing_recent(scrip_code, days=10):
                    start_idx = idx
                    break
            except Exception as e:
                logger.warning(f"Resume check failed for {scrip_code}: {e}")
                start_idx = idx
                break

        if start_idx >= len(records):
            await websocket.send_json(
                {
                    "status": "already_up_to_date",
                    "start_idx": start_idx,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            await websocket.send_json(
                {
                    "status": "complete",
                    "total": total_records,
                    "duration_seconds": (datetime.utcnow() - start_time).total_seconds(),
                }
            )
            return

        await websocket.send_json(
            {
                "status": "resume_from",
                "start_idx": start_idx,
                "remaining": len(records) - start_idx,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        # Fetch XBRL links for each company
        processed = 0
        successful = 0
        failed = 0

        for idx, row in enumerate(records[start_idx:], start=start_idx):
            scrip_code = (row.get("Scrip-code") or "").strip()
            symbol = (row.get("Symbol") or "").strip()
            name = (row.get("Company") or "").strip()
            sector = (row.get("Sector ") or "").strip()
            industry = (row.get("Industry") or "").strip()

            if not scrip_code:
                await websocket.send_json(
                    {
                        "idx": idx + 1,
                        "status": "skipped",
                        "reason": "empty_scrip_code",
                    }
                )
                continue

            await websocket.send_json(
                {
                    "idx": idx + 1,
                    "status": "processing",
                    "scrip_code": scrip_code,
                    "company": name,
                    "symbol": symbol,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

            try:
                # Use Crawl4AI to fetch XBRL link (much faster than Playwright)
                xbrl_url, period, report_type, attempts, error = (
                    await fetch_xbrl_with_crawl4ai(scrip_code, prefer="any")
                )

                if xbrl_url:
                    # Store in database
                    try:
                        repo.insert_xbrl_filing(
                            scrip_code=scrip_code,
                            symbol=symbol,
                            company_name=name,
                            sector=sector,
                            industry=industry,
                            xbrl_link=xbrl_url,
                            period=period,
                            report_type=report_type,
                            fetched_at=datetime.utcnow(),
                        )
                        successful += 1
                        await websocket.send_json(
                            {
                                "idx": idx + 1,
                                "status": "found",
                                "scrip_code": scrip_code,
                                "xbrl_link": xbrl_url,
                                "period": period,
                                "report_type": report_type,
                                "attempts": attempts,
                            }
                        )
                    except Exception as db_error:
                        logger.error(f"Database insertion error for {scrip_code}: {db_error}")
                        failed += 1
                        await websocket.send_json(
                            {
                                "idx": idx + 1,
                                "status": "error",
                                "scrip_code": scrip_code,
                                "error": f"Database error: {str(db_error)}",
                            }
                        )
                else:
                    failed += 1
                    await websocket.send_json(
                        {
                            "idx": idx + 1,
                            "status": "not_found",
                            "scrip_code": scrip_code,
                            "error": error,
                            "attempts": attempts,
                        }
                    )

            except asyncio.TimeoutError as te:
                failed += 1
                logger.warning(f"Timeout for {scrip_code}: {te}")
                await websocket.send_json(
                    {
                        "idx": idx + 1,
                        "status": "timeout",
                        "scrip_code": scrip_code,
                        "error": "Request timeout",
                    }
                )

            except Exception as row_error:
                failed += 1
                logger.error(f"Error processing {scrip_code}: {row_error}", exc_info=True)
                await websocket.send_json(
                    {
                        "idx": idx + 1,
                        "status": "error",
                        "scrip_code": scrip_code,
                        "error": str(row_error),
                        "traceback": traceback.format_exc(),
                    }
                )

            processed += 1
            # Send periodic status update
            if processed % 5 == 0:
                await websocket.send_json(
                    {
                        "status": "progress",
                        "processed": processed,
                        "successful": successful,
                        "failed": failed,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )

            # Small delay to avoid overwhelming the server
            await asyncio.sleep(0.5)

        # Final summary
        await websocket.send_json(
            {
                "status": "complete",
                "total": total_records,
                "processed": processed,
                "successful": successful,
                "failed": failed,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
        pass

    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        await websocket.send_json(
            {
                "error": str(e),
                "traceback": traceback.format_exc(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        try:
            await websocket.close()
        except Exception:
            pass

    finally:
        try:
            repo.close()
        except Exception as e:
            logger.warning(f"Error closing repository: {e}")


# ==================== Keep original xbrl_ws_route imports for reference ====================
# The original /ws/xbrl-extract-from-db endpoint remains in xbrl_ws_route.py
# This new endpoint is optimized specifically for XBRL link fetching

@router.websocket("/ws/xbrl-fetch-batch")
async def websocket_xbrl_fetch_batch(websocket: WebSocket) -> None:
    """
    Alternative batch WebSocket endpoint.
    Accepts list of company names/scrips and fetches XBRL links with streaming updates.
    """
    await websocket.accept()

    try:
        # Expect initial message with list of companies
        data = await websocket.receive_json()
        companies = data.get("companies", [])
        prefer = data.get("prefer", "any")
        max_parallel = min(data.get("parallel", 3), 6)

        if not companies:
            await websocket.send_json(
                {"error": "No companies provided", "timestamp": datetime.utcnow().isoformat()}
            )
            await websocket.close()
            return

        await websocket.send_json(
            {
                "status": "starting",
                "total_companies": len(companies),
                "parallel": max_parallel,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        # Fetch with controlled parallelism
        semaphore = asyncio.Semaphore(max_parallel)

        async def fetch_with_update(idx, company):
            async with semaphore:
                url, period, report_type, attempts, error = (
                    await fetch_xbrl_with_crawl4ai(company, prefer)
                )
                return idx, company, url, period, report_type, attempts, error

        tasks = [
            fetch_with_update(idx, company)
            for idx, company in enumerate(companies)
        ]

        # Process results as they complete
        for coro in asyncio.as_completed(tasks):
            idx, company, url, period, report_type, attempts, error = await coro
            await websocket.send_json(
                {
                    "idx": idx + 1,
                    "total": len(companies),
                    "company": company,
                    "xbrl_url": url,
                    "period": period,
                    "report_type": report_type,
                    "attempts": attempts,
                    "error": error,
                    "status": "found" if url else "not_found",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        await websocket.send_json(
            {
                "status": "complete",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during batch fetch")

    except Exception as e:
        logger.error(f"Error in batch WebSocket: {e}", exc_info=True)
        await websocket.send_json(
            {
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        try:
            await websocket.close()
        except Exception:
            pass
