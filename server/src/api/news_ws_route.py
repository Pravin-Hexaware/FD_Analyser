"""
WebSocket endpoint for admin-triggered news fetching workflow.
Fetches news for all companies in the database and creates markdown summaries.
Supports resume functionality - skips companies that are already processed for today.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
from datetime import datetime
from pathlib import Path
import re

from repository.sqlite_repository import SqliteRepository
from service.news_fetch_service import fetch_and_save_news_for_company

router = APIRouter()


def safe_filename(value: str) -> str:
    """Convert string to safe filename."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value) or "article"


def is_company_already_processed_today(company_name: str) -> bool:
    """
    Check if a company has already been fully processed for today.
    
    Conditions to skip:
    1. Folder exists: markdown/{company_name}/
    2. Today's date subfolder exists: markdown/{company_name}/{today}/
    3. summary.md exists in that subfolder
    
    Returns True if all conditions are met (company already processed).
    """
    today = datetime.now().strftime("%Y%m%d")
    base_dir = Path(__file__).resolve().parents[1]  # server/src
    markdown_dir = base_dir / "markdown"
    
    # Convert company name to safe folder name (uppercase with underscores)
    company_folder_name = safe_filename(company_name).upper()
    
    # Check condition 1: Company folder exists
    company_folder = markdown_dir / company_folder_name
    if not company_folder.exists():
        return False
    
    # Check condition 2: Today's date subfolder exists
    date_folder = company_folder / today
    if not date_folder.exists():
        return False
    
    # Check condition 3: summary.md exists
    summary_file = date_folder / "summary.md"
    if not summary_file.exists():
        return False
    
    # Verify summary.md is not empty
    if summary_file.stat().st_size == 0:
        return False
    
    return True


@router.websocket("/ws/news-fetch-all")
async def websocket_news_fetch(websocket: WebSocket) -> None:
    """
    WebSocket endpoint to fetch news for all companies in company_table.
    Supports resume - skips companies that are already processed for today.
    
    For each company:
    1. Check if already processed today (skip if yes)
    2. Fetches news articles using NewsService
    3. Scrapes article content to markdown
    4. Saves individual markdowns in {company_name}_{date}/{filename}.md
    5. Creates a summary in {company_name}_{date}/{date}/summary.md
    
    Status messages sent via websocket for progress tracking.
    """
    await websocket.accept()

    repo = SqliteRepository()

    try:
        await websocket.send_json({"status": "starting"})

        # Get all companies from database
        companies = repo.get_all_companies()
        
        if not companies:
            await websocket.send_json({"status": "no_companies", "count": 0})
            await websocket.send_json({"status": "complete"})
            await websocket.close()
            return

        await websocket.send_json({"status": "fetched_companies", "count": len(companies)})

        # Track skipped companies for reporting
        skipped_count = 0
        processed_count = 0

        for idx, company in enumerate(companies, start=1):
            company_name = company.get('company_name')
            scrip_code = company.get('scrip_code')

            # Check if already processed today
            if is_company_already_processed_today(company_name):
                await websocket.send_json({
                    "idx": idx,
                    "total": len(companies),
                    "company_name": company_name,
                    "scrip_code": scrip_code,
                    "status": "already_processed"
                })
                skipped_count += 1
                await asyncio.sleep(0)
                continue

            await websocket.send_json({
                "idx": idx,
                "total": len(companies),
                "company_name": company_name,
                "scrip_code": scrip_code,
                "status": "processing_company"
            })

            # Fetch and save news for this company
            await fetch_and_save_news_for_company(company_name, scrip_code, websocket, idx)
            processed_count += 1

            await asyncio.sleep(0)  # Allow other tasks

        await websocket.send_json({
            "status": "complete", 
            "message": "All companies processed",
            "processed": processed_count,
            "skipped": skipped_count
        })

    except WebSocketDisconnect:
        # Client disconnected gracefully
        pass
    except Exception as e:
        await websocket.send_json({"error": str(e), "status": "error"})
        await websocket.close()
    finally:
        try:
            repo.close()
        except Exception:
            pass
