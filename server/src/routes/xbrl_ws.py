import asyncio
import csv
import json
import re
import traceback
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from config.settings import COMPANY_METADATA_CSV

from repositories.sqlite_repository import SqliteRepository
from repositories.xbrl_repository import update_metrics_json
from services.batch_xbrl_finder import (
    check_bse_landing_site_health,
    create_browser_and_context,
    fetch_xbrl_for_company,
    get_all_std_xbrl_urls,
    is_half_or_nine_month_period,
)
from services.heal_service import (
    BseWebsiteDown,
    PlaywrightHealBatchHalt,
    heal_results_portal,
    is_heal_in_progress,
)
from services.logging_service import logging_service
from services.xbrl_file_store import read_xbrl_raw, save_xbrl_raw
from automation.results_portal import SiteHealth, WEBSITE_DOWN_DETAIL, is_site_down

# Heal pipeline (analysis + DOM + up to 5 codegen/harness attempts) can take 15–25 min.
DEFAULT_PER_COMPANY_TIMEOUT_S = 180
HEAL_AWARE_PER_COMPANY_TIMEOUT_S = 2400
SCRIP_FILTER_PER_COMPANY_TIMEOUT_S = 900
# Halt and invoke heal when this many companies in a row yield zero XBRL rows.
CONSECUTIVE_EMPTY_GRID_HEAL_THRESHOLD = 3
BSE_RESULTS_URL = "https://www.bseindia.com/corporates/comp_resultsnew"
PRODUCTION_PORTAL_PATH = Path(__file__).resolve().parents[1] / "automation" / "results_portal.py"
from services.xml_extraction_service import (
    extract_xbrl_data_from_bytes,
)
from utils.fiscal_year import (
    calculate_5year_fiscal_range as _calculate_5year_fiscal_range,
    is_within_5year_range as _is_within_5year_range,
)

router = APIRouter()


@router.websocket("/ws/xbrl-fetch-latest")
async def websocket_xbrl_fetch(websocket: WebSocket) -> None:
    """WebSocket endpoint that reads companies from CSV, fetches XBRL URLs, and stores them in SQLite."""
    await websocket.accept()

    csv_path = COMPANY_METADATA_CSV
    if not csv_path.exists():
        await websocket.send_json({"error": f"CSV file not found: {csv_path}"})
        await websocket.close()
        return

    repo = SqliteRepository()

    try:
        await websocket.send_json({"status": "starting", "csv_path": str(csv_path)})

        # Read CSV once
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records = [r for r in reader if r.get("Scrip-code")]

        await websocket.send_json(
            {"status": "read_csv", "records": len(records)}
        )

        # Determine restart/resume point based on recent (<=10 days) xbrl filing entries.
        start_idx = 1
        for idx, row in enumerate(records, start=1):
            scrip_code = (row.get("Scrip-code") or "").strip()
            if not scrip_code:
                continue
            try:
                if await repo.xbrl_filing_recent(scrip_code, days=10):
                    continue
                start_idx = idx
                break
            except Exception as e:
                await websocket.send_json({
                    "status": "resume_check_failed",
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
                start_idx = idx
                break

        if start_idx > len(records):
            await websocket.send_json({"status": "already_up_to_date", "start_idx": start_idx})
            await websocket.send_json({"status": "complete"})
            return

        await websocket.send_json({"status": "resume_from", "start_idx": start_idx})

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser, ctx = await create_browser_and_context(p)
            try:
                for idx, row in enumerate(records, start=1):
                        if idx < start_idx:
                            continue

                        scrip_code = (row.get("Scrip-code") or "").strip()
                        symbol = (row.get("Symbol") or "").strip()
                        name = (row.get("Company") or "").strip()
                        sector = (row.get("Sector ") or "").strip()
                        industry = (row.get("Industry") or "").strip()

                        if not scrip_code:
                            await websocket.send_json({"idx": idx, "status": "skipped", "reason": "empty scrip_code"})
                            continue

                        # Check if company already has XBRL filings in database
                        if await repo.get_xbrl_filings_count(scrip_code) > 0:
                            await websocket.send_json({
                                "idx": idx,
                                "scrip_code": scrip_code,
                                "symbol": symbol,
                                "status": "already_found_in_db",
                                "reason": "XBRL filings already exist in database"
                            })
                            continue

                        try:
                            async with asyncio.timeout(HEAL_AWARE_PER_COMPANY_TIMEOUT_S):
                                # Ensure company exists; if already present, keep it as-is
                                if not await repo.company_exists(scrip_code):
                                    await repo.upsert_company(
                                    company_name=name,
                                    symbol=symbol,
                                    scrip_code=scrip_code,
                                    sector=sector,
                                    industry=industry,
                                )

                            # Fetch both quarterly and annual report URLs in one pass (faster)
                            q_url = None
                            q_period = None
                            a_url = None
                            a_period = None
                            attempts = 0
                            try:
                                _, _, attempts, a_url, a_period, q_url, q_period = await fetch_xbrl_for_company(ctx, scrip_code, prefer="any")
                            except Exception as e:
                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "report_type": "mixed",
                                    "error": str(e),
                                    "traceback": traceback.format_exc(),
                                })

                            # Store and emit quarterly
                            q_id = None
                            q_stored = False
                            if q_url:
                                if await repo.xbrl_filing_exists(scrip_code, q_url, report_type="std", publication_date=q_period):
                                    q_stored = True
                                    q_id = await repo.get_xbrl_filing_id(scrip_code, q_url, report_type="std")
                                else:
                                    q_id = await repo.insert_xbrl_filing(
                                        scrip_code=scrip_code,
                                        symbol=symbol,
                                        xbrl_link=q_url,
                                        publication_date=q_period,
                                        report_type="std",
                                        category="std",
                                        period=q_period,
                                    )
                                    q_stored = True

                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "report_type": "std",
                                    "period": q_period,
                                    "url": q_url,
                                    "id": q_id,
                                    "stored": q_stored,
                                    "attempts": attempts,
                                })

                            # Store and emit annual
                            a_id = None
                            a_stored = False
                            if a_url:
                                if await repo.xbrl_filing_exists(scrip_code, a_url, report_type="std", publication_date=a_period):
                                    a_stored = True
                                    a_id = await repo.get_xbrl_filing_id(scrip_code, a_url, report_type="std")
                                else:
                                    a_id = await repo.insert_xbrl_filing(
                                        scrip_code=scrip_code,
                                        symbol=symbol,
                                        xbrl_link=a_url,
                                        publication_date=a_period,
                                        report_type="std",
                                        category="std",
                                        period=a_period,
                                    )
                                    a_stored = True

                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "report_type": "std",
                                    "period": a_period,
                                    "url": a_url,
                                    "id": a_id,
                                    "stored": a_stored,
                                    "attempts": attempts,
                                })

                        except asyncio.TimeoutError as te:
                            await websocket.send_json({
                                "idx": idx,
                                "scrip_code": scrip_code,
                                "status": "timeout",
                                "error": f"Per-entry timeout exceeded ({HEAL_AWARE_PER_COMPANY_TIMEOUT_S}s)",
                                "detail": str(te),
                                "traceback": traceback.format_exc(),
                            })
                            continue
                        except Exception as row_error:
                            await websocket.send_json({
                                "idx": idx,
                                "scrip_code": scrip_code,
                                "status": "row_error",
                                "error": str(row_error),
                                "traceback": traceback.format_exc(),
                            })
                            continue

            finally:
                try:
                    await browser.close()
                except Exception as e:
                    print(f"[ERROR] Smart Search input NOT found: {e}")

        await websocket.send_json({"status": "complete"})

    except WebSocketDisconnect:
        # Client disconnected
        pass
    except Exception as e:
        await websocket.send_json({"error": str(e), "traceback": traceback.format_exc()})
        await websocket.close()
    finally:
        try:
            repo.close()
        except Exception as e:
            print(f"[ERROR] Smart Search input NOT found: {e}")



@router.websocket("/ws/xbrl-extract-from-db")
async def websocket_extract_from_db(websocket: WebSocket) -> None:
    """
    WebSocket endpoint: read XBRL filings from DB with specific conditions and extract using HTML parser.
    
    Conditions:
    - report_type == "std"
    - xbrl_link ends with ".html"
    - publication_date[1] == "C" (cumulative/annual) or "Q" (quarterly)
    - Skip all other records
    - Use html_parser_service to parse raw_content
    - Store parsed JSON in quarterly_extractions or annual_extractions table
    """
    await websocket.accept()

    repo = SqliteRepository()

    try:
        await websocket.send_json({"status": "starting"})

        # Get filings with company info (raw content lives on disk via xbrl_file_store)
        filings = await repo.get_xbrl_filings_with_company_and_content()
        await websocket.send_json({"status": "found_filings", "count": len(filings)})

        for idx, f in enumerate(filings, start=1):
            scrip_code = f.get("scrip_code")
            company_name = f.get("company_name") or "Unknown Company"
            xbrl_link = f.get("xbrl_link")
            publication_date = str(f.get("publication_date") or f.get("period") or "").strip()
            db_report_type = str(f.get("category") or f.get("report_type") or "").strip().lower()
            category = db_report_type if db_report_type in ("std", "con") else "std"

            await websocket.send_json({
                "idx": idx,
                "scrip_code": scrip_code,
                "company_name": company_name,
                "xbrl_link": xbrl_link,
                "publication_date": publication_date,
                "report_type": db_report_type,
                "status": "record_read",
            })
            await asyncio.sleep(0)

            # Apply filtering conditions — extract both standalone and consolidated
            if category not in ("std", "con"):
                await websocket.send_json({
                    "idx": idx,
                    "status": "skipped",
                    "reason": f"category is '{db_report_type}', not std/con",
                })
                await asyncio.sleep(0)
                continue

            if not xbrl_link or not (xbrl_link.lower().endswith(".html") or xbrl_link.lower().endswith(".xml")):
                await websocket.send_json({
                    "idx": idx,
                    "status": "skipped",
                    "reason": f"xbrl_link does not end with '.html' or '.xml': {xbrl_link}",
                })
                await asyncio.sleep(0)
                continue

            if len(publication_date) < 2:
                await websocket.send_json({
                    "idx": idx,
                    "status": "skipped",
                    "reason": "invalid publication_date format",
                    "publication_date": publication_date,
                })
                await asyncio.sleep(0)
                continue

            date_char = publication_date[1].upper()
            if date_char not in ["C", "Q"]:
                await websocket.send_json({
                    "idx": idx,
                    "status": "skipped",
                    "reason": f"publication_date[1] is '{date_char}', not 'C' or 'Q'",
                    "publication_date": publication_date,
                })
                await asyncio.sleep(0)
                continue

            # Determine extraction type
            extraction_type = "annual" if date_char == "C" else "quarterly"

            await websocket.send_json({
                "idx": idx,
                "scrip_code": scrip_code,
                "company_name": company_name,
                "xbrl_link": xbrl_link,
                "publication_date": publication_date,
                "report_type": db_report_type,
                "extraction_type": extraction_type,
                "status": "processing",
            })
            await asyncio.sleep(0)

            # Check if already extracted
            if await repo.xbrl_extraction_exists(scrip_code, xbrl_link, extraction_type):
                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "status": "skipped_already_extracted",
                    "extraction_type": extraction_type,
                })
                await asyncio.sleep(0)
                continue

            # Read raw content from file store (not DB)
            raw_content = read_xbrl_raw(
                scrip_code, category, publication_date, url=xbrl_link or ""
            )
            if not raw_content:
                await websocket.send_json({
                    "idx": idx,
                    "status": "skipped",
                    "reason": "no raw_content available on disk",
                })
                await asyncio.sleep(0)
                continue

            try:
                raw_text = raw_content if isinstance(raw_content, str) else raw_content.decode('utf-8', errors='replace')
                raw_preview = raw_text.lstrip()[:1024].lower()
                raw_bytes = raw_text.encode('utf-8')

                is_html_content = (
                    xbrl_link.lower().endswith('.html')
                    or xbrl_link.lower().endswith('.htm')
                    or '<html' in raw_preview
                    or '<!doctype html' in raw_preview
                    or '<body' in raw_preview
                    or '<ix:' in raw_preview
                )

                if is_html_content:
                    # HTML / iXBRL content stored as raw HTML
                    from services.html_parser_service import html_dom_to_structured_json_from_content

                    await websocket.send_json({
                        "idx": idx,
                        "status": "parsing_html",
                        "extraction_type": extraction_type,
                    })
                    await asyncio.sleep(0)

                    parsed_json = html_dom_to_structured_json_from_content(raw_bytes)
                else:
                    # XML content from file store
                    await websocket.send_json({
                        "idx": idx,
                        "status": "parsing_xml",
                        "extraction_type": extraction_type,
                    })
                    await asyncio.sleep(0)

                    parsed_json = extract_xbrl_data_from_bytes(raw_bytes, only_prefix="in-bse-fin")

                parsed_json_str = json.dumps(parsed_json, ensure_ascii=False, separators=(',', ':'))

                await update_metrics_json(
                    scrip_code=scrip_code,
                    period=publication_date,
                    category=category,
                    metrics_json=parsed_json_str,
                )

                flat_metrics = None
                try:
                    from services.xbrl_metrics_service import calculate_metrics, calculate_metrics_fourd, convert_xml_grouped_to_list
                    if isinstance(parsed_json, list):
                        flat_metrics = calculate_metrics_fourd(parsed_json)
                    elif isinstance(parsed_json, dict) and not is_html_content:
                        as_list = convert_xml_grouped_to_list(parsed_json) if callable(convert_xml_grouped_to_list) else None
                        if as_list:
                            flat_metrics = calculate_metrics_fourd(as_list)
                except Exception as metrics_err:
                    print(f"[extract] metrics compute skipped: {metrics_err}")

                # Store in appropriate table
                if extraction_type == "quarterly":
                    await repo.insert_quarterly_extraction(
                        scrip_code=scrip_code,
                        company_name=company_name,
                        xbrl_link=xbrl_link,
                        publication_date=publication_date,
                        report_type=category,
                        category=category,
                        parsed_json=parsed_json_str,
                        flat=flat_metrics,
                    )
                else:  # annual
                    await repo.insert_annual_extraction(
                        scrip_code=scrip_code,
                        company_name=company_name,
                        xbrl_link=xbrl_link,
                        publication_date=publication_date,
                        report_type=category,
                        category=category,
                        parsed_json=parsed_json_str,
                        flat=flat_metrics,
                    )

                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "company_name": company_name,
                    "status": "stored",
                    "extraction_type": extraction_type,
                    "message": f"Parsed JSON stored in XBRL_Data + {extraction_type} metrics",
                })
                await asyncio.sleep(0)

            except Exception as e:
                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "status": "error",
                    "extraction_type": extraction_type,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
                await asyncio.sleep(0)
                continue

        await websocket.send_json({"status": "complete", "message": "All records processed"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"error": str(e), "traceback": traceback.format_exc()})
        await websocket.close()
    finally:
        try:
            repo.close()
        except Exception as e:
            print(f"[ERROR] Smart Search input NOT found: {e}")



@router.websocket("/ws/xbrl-fetch-all-std")
async def websocket_xbrl_fetch_all(websocket: WebSocket) -> None:
    """WebSocket endpoint that reads companies from CSV, fetches XBRL URLs, and stores them in SQLite.

    Optional first client JSON message (within ~2s):
      {"scrip_codes": ["500325"]}  # limit Fetch Filings to these scrips (heal/regression tests)
    """
    await websocket.accept()

    csv_path = COMPANY_METADATA_CSV
    if not csv_path.exists():
        await websocket.send_json({"error": f"CSV file not found: {csv_path}"})
        await websocket.close()
        return

    repo = SqliteRepository()
    scrip_filter: set[str] | None = None

    try:
        # Optional filter from client (UI currently sends nothing; test harness can send scrip_codes).
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            payload = json.loads(raw) if raw else {}
            codes = payload.get("scrip_codes") or payload.get("scrip_code")
            if isinstance(codes, str):
                codes = [codes]
            if isinstance(codes, list):
                scrip_filter = {str(c).strip() for c in codes if str(c).strip()}
                await websocket.send_json({
                    "status": "scrip_filter_applied",
                    "scrip_codes": sorted(scrip_filter),
                })
        except asyncio.TimeoutError:
            pass
        except Exception as filter_exc:
            await websocket.send_json({
                "status": "scrip_filter_ignored",
                "error": str(filter_exc),
            })

        await websocket.send_json({"status": "starting", "csv_path": str(csv_path)})

        # Read CSV once
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records = [r for r in reader if r.get("Scrip-code")]

        if scrip_filter:
            records = [r for r in records if (r.get("Scrip-code") or "").strip() in scrip_filter]
            missing = scrip_filter - {(r.get("Scrip-code") or "").strip() for r in records}
            for code in sorted(missing):
                records.append({
                    "Scrip-code": code,
                    "Symbol": code,
                    "Company": code,
                    "Sector ": "",
                    "Industry": "",
                })

        await websocket.send_json(
            {"status": "read_csv", "records": len(records), "filtered": bool(scrip_filter)}
        )

        # Determine restart/resume point based on recent xbrl filing entries.
        # Explicit scrip filter (heal test) always starts at the first record.
        start_idx = 1
        if not scrip_filter:
            for idx, row in enumerate(records, start=1):
                scrip_code = (row.get("Scrip-code") or "").strip()
                if not scrip_code:
                    continue
                try:
                    if await repo.xbrl_filing_recent(scrip_code, days=50):
                        continue
                    start_idx = idx
                    break
                except Exception as e:
                    await websocket.send_json({
                        "status": "resume_check_failed",
                        "idx": idx,
                        "scrip_code": scrip_code,
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                    })
                    start_idx = idx
                    break

        if start_idx > len(records):
            await websocket.send_json({"status": "already_up_to_date", "start_idx": start_idx})
            await websocket.send_json({"status": "complete"})
            return

        await websocket.send_json({"status": "resume_from", "start_idx": start_idx})

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser, ctx = await create_browser_and_context(p)
            consecutive_empty_grids = 0
            # One full coding-agent heal per Fetch Filings batch — not per company.
            # Re-healing every scrip was the multi-hour loop in SessionLog.
            heal_attempted_for_batch = False

            async def _halt_website_down(**extra):
                payload = {
                    "status": "website_down",
                    "detail": WEBSITE_DOWN_DETAIL,
                    "halted_by": "bse_downtime",
                }
                payload.update(extra)
                await websocket.send_json(payload)
                await websocket.send_json({
                    "status": "complete",
                    "halted_by": "bse_downtime",
                    "detail": WEBSITE_DOWN_DETAIL,
                })

            # Landing-grid health check before any company search / heal.
            try:
                batch_health = await check_bse_landing_site_health(ctx)
            except Exception as health_exc:
                logging_service.log_phase(
                    "site_health",
                    "failed",
                    error=str(health_exc),
                    detail="batch_start_probe_failed_continue",
                )
                batch_health = SiteHealth.GRID_MISSING

            if is_site_down(batch_health):
                logging_service.log_phase(
                    "site_health",
                    "success",
                    health=SiteHealth.DOWN.value,
                    detail=WEBSITE_DOWN_DETAIL,
                    check_phase="batch_start",
                )
                await _halt_website_down(phase="batch_start")
                return

            logging_service.log_phase(
                "site_health",
                "success",
                health=str(getattr(batch_health, "value", batch_health)),
                detail="batch_start_site_ok_proceed",
            )

            try:
                for idx, row in enumerate(records, start=1):
                        if idx < start_idx:
                            continue

                        scrip_code = (row.get("Scrip-code") or "").strip()
                        symbol = (row.get("Symbol") or "").strip()
                        name = (row.get("Company") or "").strip()
                        sector = (row.get("Sector ") or "").strip()
                        industry = (row.get("Industry") or "").strip()

                        if not scrip_code:
                            await websocket.send_json({"idx": idx, "status": "skipped", "reason": "empty scrip_code"})
                            continue

                        per_company_timeout = (
                            SCRIP_FILTER_PER_COMPANY_TIMEOUT_S
                            if scrip_filter
                            else HEAL_AWARE_PER_COMPANY_TIMEOUT_S
                        )
                        company_done = False
                        while not company_done:
                            try:
                                async with asyncio.timeout(per_company_timeout):
                                    # Ensure company exists; if already present, keep it as-is
                                    if not await repo.company_exists(scrip_code):
                                        await repo.upsert_company(
                                            company_name=name,
                                            symbol=symbol,
                                            scrip_code=scrip_code,
                                            sector=sector,
                                            industry=industry,
                                        )

                                    # Send started message
                                    await websocket.send_json({
                                        "status": "started",
                                        "idx": idx,
                                        "scrip_code": scrip_code,
                                        "symbol": symbol,
                                    })

                                    # Prepare existing period/url lookup once to prevent repeated DB scans
                                    # Using (publication_date, xbrl_link) key allows O(1) lookup instead of DB queries
                                    existing_filings = await repo.get_xbrl_filings(scrip_code)
                                    existing_map = {
                                        (f.get('publication_date'), f.get('xbrl_link')): f.get('id')
                                        for f in existing_filings
                                    }

                                    # Canonical flow: type scrip in Security Name field (not company name).
                                    search_query = scrip_code
                                    expected_scrip = scrip_code

                                    # Fetch all Std XBRL URLs (only std, not con)
                                    link_idx = 0
                                    consecutive_out_of_range = 0
                                    async for url, period, xbrl_type, raw_content, _industry in get_all_std_xbrl_urls(
                                        ctx,
                                        search_query,
                                        expected_scrip=expected_scrip,
                                    ):
                                        # FILTER 1: Only collect "std" XBRL, skip "con"
                                        if xbrl_type.lower() != "std":
                                            continue

                                        # FILTER 2: Skip half-yearly (SH) / nine-months (DN) only
                                        if is_half_or_nine_month_period(period):
                                            await websocket.send_json({
                                                "idx": idx,
                                                "link_idx": link_idx,
                                                "scrip_code": scrip_code,
                                                "symbol": symbol,
                                                "report_type": xbrl_type,
                                                "period": period,
                                                "url": url,
                                                "status": "skipped_half_or_nine_month",
                                                "reason": f"Period {period} is half-yearly (H) or nine-months (N)",
                                            })
                                            link_idx += 1
                                            continue

                                        # Prefetched content missing ⇒ unprocessable row (do not re-fetch)
                                        if not raw_content:
                                            await websocket.send_json({
                                                "idx": idx,
                                                "link_idx": link_idx,
                                                "scrip_code": scrip_code,
                                                "symbol": symbol,
                                                "report_type": xbrl_type,
                                                "period": period,
                                                "url": url,
                                                "status": "skipped_unprocessable",
                                                "reason": "link present but raw content unavailable",
                                            })
                                            link_idx += 1
                                            continue

                                        # FILTER 3: Only collect data from past 5 years + EARLY EXIT OPTIMIZATION
                                        if not _is_within_5year_range(period):
                                            consecutive_out_of_range += 1
                                            await websocket.send_json({
                                                "idx": idx,
                                                "link_idx": link_idx,
                                                "scrip_code": scrip_code,
                                                "symbol": symbol,
                                                "report_type": xbrl_type,
                                                "period": period,
                                                "url": url,
                                                "status": "skipped_outside_5year_range",
                                                "reason": f"Period {period} is outside past 5 years range (consecutive: {consecutive_out_of_range})",
                                            })
                                            link_idx += 1

                                            if consecutive_out_of_range >= 2:
                                                await websocket.send_json({
                                                    "idx": idx,
                                                    "scrip_code": scrip_code,
                                                    "symbol": symbol,
                                                    "status": "halting_collection",
                                                    "reason": "2 consecutive records outside 5-year range. All remaining records assumed to be older. Halting collection.",
                                                })
                                                break
                                            continue

                                        consecutive_out_of_range = 0

                                        if _industry and _industry.strip():
                                            industry = _industry.strip()
                                            await repo.upsert_company(
                                                company_name=name,
                                                symbol=symbol,
                                                scrip_code=scrip_code,
                                                sector=industry,
                                                industry=industry,
                                            )

                                        if (period, url) in existing_map:
                                            await websocket.send_json({
                                                "idx": idx,
                                                "link_idx": link_idx,
                                                "scrip_code": scrip_code,
                                                "symbol": symbol,
                                                "report_type": xbrl_type,
                                                "period": period,
                                                "url": url,
                                                "status": "skipped_duplicate",
                                                "reason": f"Duplicate: same period ({period}) and URL for {scrip_code}",
                                            })
                                            link_idx += 1
                                            continue

                                        try:
                                            category = (xbrl_type or "std").strip().lower()
                                            if category not in ("std", "con"):
                                                category = "std"
                                            save_xbrl_raw(
                                                scrip_code,
                                                category,
                                                period,
                                                raw_content,
                                                url,
                                            )
                                            filing_id = await repo.insert_xbrl_filing(
                                                scrip_code=scrip_code,
                                                symbol=symbol,
                                                xbrl_link=url,
                                                publication_date=period,
                                                report_type=category,
                                                category=category,
                                                period=period,
                                            )
                                            stored = True
                                        except Exception as insert_error:
                                            await websocket.send_json({
                                                "idx": idx,
                                                "link_idx": link_idx,
                                                "scrip_code": scrip_code,
                                                "symbol": symbol,
                                                "report_type": xbrl_type,
                                                "period": period,
                                                "url": url,
                                                "status": "error_inserting",
                                                "error": str(insert_error),
                                            })
                                            link_idx += 1
                                            continue

                                        await websocket.send_json({
                                            "idx": idx,
                                            "link_idx": link_idx,
                                            "scrip_code": scrip_code,
                                            "symbol": symbol,
                                            "report_type": xbrl_type,
                                            "period": period,
                                            "url": url,
                                            "id": filing_id,
                                            "stored": stored,
                                            "attempts": link_idx + 1,
                                        })
                                        link_idx += 1

                                    next_idx = idx + 1 if idx < len(records) else None
                                    if link_idx == 0:
                                        consecutive_empty_grids += 1
                                        await websocket.send_json({
                                            "status": "no_results",
                                            "idx": idx,
                                            "scrip_code": scrip_code,
                                            "symbol": symbol,
                                            "search_query": search_query,
                                            "consecutive_empty": consecutive_empty_grids,
                                        })
                                        if (
                                            not scrip_filter
                                            and consecutive_empty_grids >= CONSECUTIVE_EMPTY_GRID_HEAL_THRESHOLD
                                            and not heal_attempted_for_batch
                                        ):
                                            try:
                                                empty_health = await check_bse_landing_site_health(ctx)
                                            except Exception as health_exc:
                                                logging_service.log_phase(
                                                    "site_health",
                                                    "failed",
                                                    company=scrip_code,
                                                    error=str(health_exc),
                                                    detail="consecutive_empty_probe_failed_treat_as_up",
                                                )
                                                empty_health = SiteHealth.UP
                                            if is_site_down(empty_health):
                                                logging_service.log_phase(
                                                    "playwright_heal_trigger",
                                                    "skipped",
                                                    company=scrip_code,
                                                    reason="consecutive_empty_bse_downtime",
                                                    consecutive_empty=consecutive_empty_grids,
                                                    detail=WEBSITE_DOWN_DETAIL,
                                                )
                                                raise BseWebsiteDown(
                                                    WEBSITE_DOWN_DETAIL,
                                                    company=scrip_code,
                                                )
                                            logging_service.log_phase(
                                                "playwright_heal_trigger",
                                                "started",
                                                company=scrip_code,
                                                reason="consecutive_empty_results_grids",
                                                failed_phase="xbrl_grid",
                                                consecutive_empty=consecutive_empty_grids,
                                                detail="fetch_filings_consecutive_empty_grid_threshold",
                                                site_health=str(getattr(empty_health, "value", empty_health)),
                                            )
                                            raise PlaywrightHealBatchHalt(
                                                "consecutive_empty_results_grids",
                                                company=scrip_code,
                                                needs_heal=True,
                                                failed_phase="xbrl_grid",
                                            )
                                    else:
                                        consecutive_empty_grids = 0
                                    await websocket.send_json({
                                        "status": "completed",
                                        "idx": idx,
                                        "scrip_code": scrip_code,
                                        "symbol": symbol,
                                        "next_idx": next_idx,
                                        "filings_found": link_idx,
                                    })
                                company_done = True

                            except BseWebsiteDown as down_exc:
                                await _halt_website_down(
                                    idx=idx,
                                    scrip_code=scrip_code,
                                    symbol=symbol,
                                    error=str(down_exc),
                                )
                                return

                            except PlaywrightHealBatchHalt as heal_halt:
                                reason = getattr(heal_halt, "reason", str(heal_halt))
                                healed_path = getattr(heal_halt, "healed_path", None)
                                needs_heal = getattr(heal_halt, "needs_heal", False)

                                async def _recreate_browser_after_heal():
                                    nonlocal browser, ctx
                                    try:
                                        await ctx.close()
                                    except Exception:
                                        pass
                                    try:
                                        await browser.close()
                                    except Exception:
                                        pass
                                    browser, ctx = await create_browser_and_context(p)

                                # UI drift: at most ONE coding-agent heal per Fetch Filings batch.
                                if needs_heal and not heal_attempted_for_batch:
                                    try:
                                        pre_heal_health = await check_bse_landing_site_health(ctx)
                                    except Exception as health_exc:
                                        logging_service.log_phase(
                                            "site_health",
                                            "failed",
                                            company=scrip_code,
                                            error=str(health_exc),
                                            detail="pre_heal_probe_failed_proceed_to_heal",
                                        )
                                        pre_heal_health = SiteHealth.GRID_MISSING
                                    if is_site_down(pre_heal_health):
                                        logging_service.log_phase(
                                            "playwright_heal_trigger",
                                            "skipped",
                                            company=scrip_code,
                                            reason="bse_downtime",
                                            detail=WEBSITE_DOWN_DETAIL,
                                        )
                                        await _halt_website_down(
                                            idx=idx,
                                            scrip_code=scrip_code,
                                            symbol=symbol,
                                            reason=reason,
                                        )
                                        return

                                    heal_attempted_for_batch = True
                                    await websocket.send_json({
                                        "status": "heal_agent_started",
                                        "idx": idx,
                                        "scrip_code": scrip_code,
                                        "symbol": symbol,
                                        "reason": reason,
                                        "detail": (
                                            "BSE UI drift detected — running analysis/coding agent "
                                            "(may take 15–25 min). Will retry this scrip and continue "
                                            "Fetch Filings after portal promote. "
                                            "Only one heal is run per batch."
                                        ),
                                    })
                                    try:
                                        healed_path = await asyncio.to_thread(
                                            heal_results_portal,
                                            BSE_RESULTS_URL,
                                            PRODUCTION_PORTAL_PATH,
                                            scrip_code,
                                        )
                                        await _recreate_browser_after_heal()
                                        try:
                                            post_heal_health = await check_bse_landing_site_health(ctx)
                                        except Exception as health_exc:
                                            logging_service.log_phase(
                                                "site_health",
                                                "failed",
                                                company=scrip_code,
                                                error=str(health_exc),
                                                detail="post_heal_probe_failed_continue_retry",
                                            )
                                            post_heal_health = SiteHealth.UP
                                        if is_site_down(post_heal_health):
                                            await _halt_website_down(
                                                idx=idx,
                                                scrip_code=scrip_code,
                                                symbol=symbol,
                                                phase="post_heal",
                                            )
                                            return
                                        consecutive_empty_grids = 0
                                        await websocket.send_json({
                                            "status": "heal_success_retrying",
                                            "idx": idx,
                                            "scrip_code": scrip_code,
                                            "symbol": symbol,
                                            "reason": reason,
                                            "healed_path": str(healed_path),
                                            "detail": (
                                                "Heal promoted results_portal.py — retrying this "
                                                "scrip with a fresh browser, then continuing the batch."
                                            ),
                                        })
                                        continue  # retry same company with promoted portal
                                    except BseWebsiteDown as down_exc:
                                        await _halt_website_down(
                                            idx=idx,
                                            scrip_code=scrip_code,
                                            symbol=symbol,
                                            error=str(down_exc),
                                            phase="heal_entry_probe",
                                        )
                                        return
                                    except Exception as heal_exc:
                                        await websocket.send_json({
                                            "status": "heal_failed_batch_halted",
                                            "idx": idx,
                                            "scrip_code": scrip_code,
                                            "symbol": symbol,
                                            "reason": reason,
                                            "error": str(heal_exc),
                                            "detail": (
                                                "Heal agent failed — portal unchanged. "
                                                "Check logs/agent_runs and cache/generated_code_run.log."
                                            ),
                                        })
                                        await websocket.send_json({
                                            "status": "complete",
                                            "halted_by": "playwright_heal",
                                        })
                                        return

                                # Heal already promoted (legacy path) — refresh browser and retry once.
                                if healed_path is not None and not heal_attempted_for_batch:
                                    heal_attempted_for_batch = True
                                    await _recreate_browser_after_heal()
                                    consecutive_empty_grids = 0
                                    await websocket.send_json({
                                        "status": "heal_success_retrying",
                                        "idx": idx,
                                        "scrip_code": scrip_code,
                                        "symbol": symbol,
                                        "reason": reason,
                                        "healed_path": str(healed_path),
                                        "detail": (
                                            "Portal already healed — retrying this scrip with a "
                                            "fresh browser, then continuing the batch."
                                        ),
                                    })
                                    continue

                                # Post-heal still failing, or heal already used this batch: skip company.
                                await websocket.send_json({
                                    "status": "heal_retry_failed_skipping",
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "reason": reason,
                                    "healed_path": str(healed_path) if healed_path else None,
                                    "detail": (
                                        "UI still failing after batch heal (or heal already ran). "
                                        "Skipping this company and continuing Fetch Filings "
                                        "without starting another agent run."
                                    ),
                                })
                                company_done = True
                            except asyncio.TimeoutError as te:
                                if is_heal_in_progress():
                                    await websocket.send_json({
                                        "status": "heal_in_progress_timeout",
                                        "idx": idx,
                                        "scrip_code": scrip_code,
                                        "symbol": symbol,
                                        "error": (
                                            f"Per-entry timeout ({per_company_timeout}s) while heal agent "
                                            "was still running. Batch halted — wait for heal to finish, "
                                            "then retry Fetch Filings."
                                        ),
                                        "detail": str(te),
                                    })
                                    await websocket.send_json({
                                        "status": "complete",
                                        "halted_by": "heal_timeout",
                                    })
                                    return
                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "status": "timeout",
                                    "error": f"Per-entry timeout exceeded ({per_company_timeout}s)",
                                    "detail": str(te),
                                    "traceback": traceback.format_exc(),
                                })
                                company_done = True
                            except Exception as row_error:
                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "status": "row_error",
                                    "error": str(row_error),
                                    "traceback": traceback.format_exc(),
                                })
                                company_done = True

            finally:
                try:
                    await browser.close()
                except Exception as e:
                    print(f"[ERROR] Failed to close browser: {e}")

        await websocket.send_json({"status": "complete"})

    except WebSocketDisconnect:
        # Client disconnected
        pass
    except Exception as e:
        await websocket.send_json({"error": str(e), "traceback": traceback.format_exc()})
        await websocket.close()
    finally:
        try:
            repo.close()
        except Exception as e:
            print(f"[ERROR] Smart Search input NOT found: {e}")
