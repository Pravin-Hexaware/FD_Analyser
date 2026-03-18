import asyncio
import csv
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from repository.sqlite_repository import SqliteRepository
from api.batch_xbrl_finder import (
    create_browser_and_context,
    fetch_xbrl_for_company,
)

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
