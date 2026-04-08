import asyncio
import csv
import json
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from repository.sqlite_repository import SqliteRepository
from api.batch_xbrl_finder import (
    create_browser_and_context,
    fetch_xbrl_for_company,
    get_all_std_xbrl_urls,
)
from api.xbrl_route import calculate_metrics, extract_annual
from api.Xbrl_annual_extractor import calculate_metrics_fourd
from service.html_extraction_service import extract_html_data
from service.xml_extraction_service import extract_xbrl_data

router = APIRouter()


@router.websocket("/ws/xbrl-fetch-latest")
async def websocket_xbrl_fetch(websocket: WebSocket) -> None:
    """WebSocket endpoint that reads companies from CSV, fetches XBRL URLs, and stores them in SQLite."""
    await websocket.accept()

    csv_path = Path(__file__).resolve().parents[1] / "Data" / "Company_metadata.csv"
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
        now = datetime.utcnow()
        for idx, row in enumerate(records, start=1):
            scrip_code = (row.get("Scrip-code") or "").strip()
            if not scrip_code:
                continue
            try:
                if repo.xbrl_filing_recent(scrip_code, days=10):
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
                        if repo.get_xbrl_filings_count(scrip_code) > 0:
                            await websocket.send_json({
                                "idx": idx,
                                "scrip_code": scrip_code,
                                "symbol": symbol,
                                "status": "already_found_in_db",
                                "reason": "XBRL filings already exist in database"
                            })
                            continue

                        try:
                            async with asyncio.timeout(180):
                                # Ensure company exists; if already present, keep it as-is
                                if not repo.company_exists(scrip_code):
                                    repo.upsert_company(
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
                                if repo.xbrl_filing_exists(scrip_code, q_url, report_type="quarterly"):
                                    q_stored = True
                                    q_id = repo.get_xbrl_filing_id(scrip_code, q_url, report_type="quarterly")
                                else:
                                    q_id = repo.insert_xbrl_filing(
                                        scrip_code=scrip_code,
                                        symbol=symbol,
                                        xbrl_link=q_url,
                                        publication_date=q_period,
                                        report_type="quarterly",
                                    )
                                    q_stored = True

                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "report_type": "quarterly",
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
                                if repo.xbrl_filing_exists(scrip_code, a_url, report_type="annual"):
                                    a_stored = True
                                    a_id = repo.get_xbrl_filing_id(scrip_code, a_url, report_type="annual")
                                else:
                                    a_id = repo.insert_xbrl_filing(
                                        scrip_code=scrip_code,
                                        symbol=symbol,
                                        xbrl_link=a_url,
                                        publication_date=a_period,
                                        report_type="annual",
                                    )
                                    a_stored = True

                                await websocket.send_json({
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "report_type": "annual",
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
                                "error": "Per-entry timeout exceeded (180s)",
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
                except Exception:
                    pass

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
        except Exception:
            pass



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

        # Get filings with company name and raw content
        filings = repo.get_xbrl_filings_with_company_and_content()
        await websocket.send_json({"status": "found_filings", "count": len(filings)})

        for idx, f in enumerate(filings, start=1):
            scrip_code = f.get("scrip_code")
            company_name = f.get("company_name") or "Unknown Company"
            xbrl_link = f.get("xbrl_link")
            publication_date = str(f.get("publication_date") or "").strip()
            db_report_type = str(f.get("report_type") or "").strip().lower()
            raw_content = f.get("raw_content")

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

            # Apply filtering conditions
            if db_report_type != "std":
                await websocket.send_json({
                    "idx": idx,
                    "status": "skipped",
                    "reason": f"report_type is '{db_report_type}', not 'std'",
                })
                await asyncio.sleep(0)
                continue

            if not xbrl_link or not xbrl_link.lower().endswith(".html"):
                await websocket.send_json({
                    "idx": idx,
                    "status": "skipped",
                    "reason": f"xbrl_link does not end with '.html': {xbrl_link}",
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
            if repo.xbrl_extraction_exists(scrip_code, xbrl_link, extraction_type):
                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "status": "skipped_already_extracted",
                    "extraction_type": extraction_type,
                })
                await asyncio.sleep(0)
                continue

            # Check if raw_content exists
            if not raw_content:
                await websocket.send_json({
                    "idx": idx,
                    "status": "skipped",
                    "reason": "no raw_content available",
                })
                await asyncio.sleep(0)
                continue

            try:
                # Import html_parser_service
                from service.html_parser_service import html_dom_to_structured_json_from_content

                # Parse the HTML content
                await websocket.send_json({
                    "idx": idx,
                    "status": "parsing_html",
                    "extraction_type": extraction_type,
                })
                await asyncio.sleep(0)

                parsed_json = html_dom_to_structured_json_from_content(raw_content.encode('utf-8'))
                parsed_json_str = json.dumps(parsed_json, ensure_ascii=False)

                # Store in appropriate table
                if extraction_type == "quarterly":
                    repo.insert_quarterly_extraction(
                        scrip_code=scrip_code,
                        company_name=company_name,
                        xbrl_link=xbrl_link,
                        publication_date=publication_date,
                        report_type=db_report_type,
                        parsed_json=parsed_json_str,
                    )
                else:  # annual
                    repo.insert_annual_extraction(
                        scrip_code=scrip_code,
                        company_name=company_name,
                        xbrl_link=xbrl_link,
                        publication_date=publication_date,
                        report_type=db_report_type,
                        parsed_json=parsed_json_str,
                    )

                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "company_name": company_name,
                    "status": "stored",
                    "extraction_type": extraction_type,
                    "message": f"Parsed JSON stored in {extraction_type}_extractions table",
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
        except Exception:
            pass



@router.websocket("/ws/xbrl-fetch-all-std")
async def websocket_xbrl_fetch_all(websocket: WebSocket) -> None:
    """WebSocket endpoint that reads companies from CSV, fetches XBRL URLs, and stores them in SQLite."""
    await websocket.accept()

    csv_path = Path(__file__).resolve().parents[1] / "Data" / "Company_metadata.csv"
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
        now = datetime.utcnow()
        for idx, row in enumerate(records, start=1):
            scrip_code = (row.get("Scrip-code") or "").strip()
            if not scrip_code:
                continue
            try:
                if repo.xbrl_filing_recent(scrip_code, days=10):
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

                        try:
                            async with asyncio.timeout(180):
                                # Ensure company exists; if already present, keep it as-is
                                if not repo.company_exists(scrip_code):
                                    repo.upsert_company(
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

                            # Prepare existing period/type lookup once to prevent repeated DB scans
                            existing_filings = repo.get_xbrl_filings(scrip_code)
                            existing_map = {
                                (f.get('publication_date'), f.get('report_type')): f.get('id')
                                for f in existing_filings
                            }

                            # Fetch all Std XBRL URLs
                            link_idx = 0
                            async for url, period, xbrl_type, raw_content in get_all_std_xbrl_urls(ctx, scrip_code):
                                key = (period, xbrl_type)
                                existing_id = existing_map.get(key)
                                if existing_id:
                                    stored = True
                                    filing_id = existing_id
                                else:
                                    filing_id = repo.insert_xbrl_filing(
                                        scrip_code=scrip_code,
                                        symbol=symbol,
                                        xbrl_link=url,
                                        publication_date=period,
                                        report_type=xbrl_type,
                                        raw_content=raw_content,
                                    )
                                    stored = True
                                    existing_map[key] = filing_id

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

                            # Send completed message
                            next_idx = idx + 1 if idx < len(records) else None
                            await websocket.send_json({
                                "status": "completed",
                                "idx": idx,
                                "scrip_code": scrip_code,
                                "symbol": symbol,
                                "next_idx": next_idx,
                            })

                        except asyncio.TimeoutError as te:
                            await websocket.send_json({
                                "idx": idx,
                                "scrip_code": scrip_code,
                                "status": "timeout",
                                "error": "Per-entry timeout exceeded (180s)",
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
                except Exception:
                    pass

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
        except Exception:
            pass
