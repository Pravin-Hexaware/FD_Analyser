"""
WebSocket endpoint for admin-triggered news fetching.

Phase 1: news is disabled pending company_news schema on Tortoise.
"""
from fastapi import APIRouter, WebSocket

router = APIRouter()


@router.websocket("/ws/news-fetch-all")
async def websocket_news_fetch(websocket: WebSocket) -> None:
    """Stub: news fetch disabled until company_news schema is migrated."""
    await websocket.accept()
    try:
        await websocket.send_json({
            "status": "unavailable",
            "code": 501,
            "message": "News fetch is disabled pending company_news schema migration.",
        })
    finally:
        await websocket.close()
