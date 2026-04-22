"""
WebSocket endpoint for admin-triggered news fetching workflow.
Fetches news for all companies in the database and creates markdown summaries.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio

from repository.sqlite_repository import SqliteRepository
from service.news_fetch_service import fetch_and_save_news_for_company

router = APIRouter()


@router.websocket("/ws/news-fetch-all")
async def websocket_news_fetch(websocket: WebSocket) -> None:
    """
    WebSocket endpoint to fetch news for all companies in company_table.
    For each company:
    1. Fetches news articles using NewsService
    2. Scrapes article content to markdown
    3. Saves individual markdowns in {company_name}_{date}/{filename}.md
    4. Creates a summary in {company_name}_{date}/{date}/summary.md
    
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

        for idx, company in enumerate(companies, start=1):
            company_name = company.get('company_name')
            scrip_code = company.get('scrip_code')

            await websocket.send_json({
                "idx": idx,
                "total": len(companies),
                "company_name": company_name,
                "scrip_code": scrip_code,
                "status": "processing_company"
            })

            # Fetch and save news for this company
            await fetch_and_save_news_for_company(company_name, scrip_code, websocket, idx)

            await asyncio.sleep(0)  # Allow other tasks

        await websocket.send_json({"status": "complete", "message": "All companies processed"})

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
