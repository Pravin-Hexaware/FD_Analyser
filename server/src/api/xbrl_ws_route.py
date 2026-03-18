import asyncio
import csv
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from repository.sqlite_repository import SqliteRepository
from api.batch_xbrl_finder import (
    create_browser_and_context,
    fetch_xbrl_for_company,
)
from api.xbrl_route import calculate_metrics
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

        async with asyncio.timeout(600):
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser, ctx = await create_browser_and_context(p)
                try:
                    for idx, row in enumerate(records, start=1):
                        scrip_code = (row.get("Scrip-code") or "").strip()
                        symbol = (row.get("Symbol") or "").strip()
                        name = (row.get("Company") or "").strip()
                        sector = (row.get("Sector ") or "").strip()
                        industry = (row.get("Industry") or "").strip()

                        if not scrip_code:
                            continue

                        # Ensure company exists; if already present, keep it as-is
                        if not repo.company_exists(scrip_code):
                            repo.upsert_company(
                                company_name=name,
                                symbol=symbol,
                                scrip_code=scrip_code,
                                sector=sector,
                                industry=industry,
                            )

                        # Fetch XBRL URL using the comprehensive batch_xbrl_finder strategy
                        xbrl_url = None
                        period = None
                        attempts = 0
                        try:
                            xbrl_url, period, attempts = await fetch_xbrl_for_company(ctx, scrip_code, prefer="any")
                        except Exception as e:
                            await websocket.send_json(
                                {
                                    "idx": idx,
                                    "scrip_code": scrip_code,
                                    "symbol": symbol,
                                    "error": str(e),
                                }
                            )

                        stored = False
                        if xbrl_url:
                            if repo.xbrl_filing_exists(scrip_code, xbrl_url):
                                stored = True
                            else:
                                repo.insert_xbrl_filing(
                                    scrip_code=scrip_code,
                                    symbol=symbol,
                                    xbrl_link=xbrl_url,
                                    publication_date=period,
                                )
                                stored = True

                        await websocket.send_json(
                            {
                                "idx": idx,
                                "scrip_code": scrip_code,
                                "symbol": symbol,
                                "xbrl_url": xbrl_url,
                                "period": period,
                                "stored": stored,
                                "attempts": attempts,
                            }
                        )

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
        await websocket.send_json({"error": str(e)})
        await websocket.close()
    finally:
        try:
            repo.close()
        except Exception:
            pass


@router.websocket("/ws/xbrl-extract-from-db")
async def websocket_extract_from_db(websocket: WebSocket) -> None:
    """WebSocket endpoint: read XBRL URLs from DB, extract metrics, and store them in a second table."""
    await websocket.accept()

    repo = SqliteRepository()

    try:
        await websocket.send_json({"status": "starting"})

        filings = repo.get_xbrl_filings()
        await websocket.send_json({"status": "found_filings", "count": len(filings)})

        for idx, f in enumerate(filings, start=1):
            scrip_code = f.get("scrip_code")
            xbrl_link = f.get("xbrl_link")

            if not scrip_code or not xbrl_link:
                continue

            if repo.xbrl_extraction_exists(scrip_code, xbrl_link):
                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "xbrl_link": xbrl_link,
                    "status": "skipped_already_extracted",
                })
                continue

            try:
                if xbrl_link.lower().endswith(".xml"):
                    extracted = extract_xbrl_data(xbrl_link, only_prefix=None)
                    data_type = "xml"
                else:
                    extracted = extract_html_data(xbrl_link)
                    data_type = "html"

                metrics = calculate_metrics(extracted)

                repo.insert_xbrl_extraction(
                    scrip_code=scrip_code,
                    xbrl_link=xbrl_link,
                    company_name=metrics.get("company_name"),
                    company_symbol=metrics.get("company_symbol"),
                    currency=metrics.get("currency"),
                    level_of_rounding=metrics.get("level_of_rounding"),
                    reporting_type=metrics.get("reporting_type"),
                    nature_of_report=metrics.get("NatureOfReport"),
                    sales=metrics.get("Sales"),
                    expenses=metrics.get("Expenses"),
                    operating_profit=metrics.get("OperatingProfit"),
                    opm_percentage=metrics.get("OPM_percentage"),
                    other_income=metrics.get("OtherIncome"),
                    interest=metrics.get("Interest"),
                    depreciation=metrics.get("Depreciation"),
                    profit_before_tax=metrics.get("ProfitBeforeTax"),
                    tax=metrics.get("Tax"),
                    tax_percent=metrics.get("Tax_percent"),
                    net_profit=metrics.get("NetProfit"),
                    eps_in_rs=metrics.get("EPS_in_RS"),
                )

                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "xbrl_link": xbrl_link,
                    "status": "extracted",
                    "metrics": metrics,
                })

            except Exception as e:
                await websocket.send_json({
                    "idx": idx,
                    "scrip_code": scrip_code,
                    "xbrl_link": xbrl_link,
                    "error": str(e),
                })

        await websocket.send_json({"status": "complete"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"error": str(e)})
        await websocket.close()
    finally:
        try:
            repo.close()
        except Exception:
            pass
