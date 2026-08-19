from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import sys
import os
# Add the src directory to Python path for absolute imports
sys.path.insert(0, os.path.dirname(__file__))

from api.xbrl_route import router as xbrl_router
from api.batch_xbrl_finder import router as batch_inter_router
from api.xbrl_ws_route import router as xbrl_ws_router
from api.llm_route import router as llm_router
from api.companies_route import router as companies_router
from api.company_route import router as company_router
from api.missing_companies_route import router as missing_companies_router
from api.news_ws_route import router as news_ws_router
from service.analysis_service import initialize_llm
from service.logging_service import logging_service
import importlib
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import socket


load_dotenv()

app = FastAPI(title="Financial Data Extractor API")

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            response = await call_next(request)
            client_ip = request.client.host if request.client else "unknown"
            logging_service.append_audit_entry(str(request.url.path), response.status_code, client_ip)
            return response
        except Exception:
            client_ip = request.client.host if request.client else "unknown"
            logging_service.append_audit_entry(str(request.url.path), 500, client_ip)
            raise

app.add_middleware(AuditMiddleware)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(xbrl_router, prefix="/api", tags=["xbrl"])
# Skip analysis_route
# app.include_router(analysis_router, prefix="/api", tags=["analysis"])
app.include_router(batch_inter_router, prefix="/api", tags=["batch_inter"])
app.include_router(xbrl_ws_router, prefix="/api", tags=["xbrl_ws"])
app.include_router(llm_router, prefix="/api", tags=["llm"])


@app.on_event("startup")
def startup_initialize_services() -> None:
    try:
        from service.analysis_service import get_llm_id
        app.state.llm = initialize_llm()
        app.state.llm_id = get_llm_id()
        importlib.import_module("api.service.news_agent_service")
        logging_service.append_audit_entry("APPLICATION STARTED", "-", socket.gethostbyname(socket.gethostname()))
        print("[startup] Azure LLM and news agent initialized.")
        print(f"✅ LLM initialized with ID: {app.state.llm_id}")
    except Exception as exc:
        logging_service.append_audit_entry("APPLICATION STARTED", "-", socket.gethostbyname(socket.gethostname()))
        print(f"[ERROR] Startup initialization failed: {exc}")
app.include_router(companies_router, prefix="/api", tags=["companies"])
app.include_router(company_router, prefix="/api/companies", tags=["company_financials"])
app.include_router(missing_companies_router, prefix="/api", tags=["missing_companies"])
app.include_router(news_ws_router, prefix="/api", tags=["news_ws"])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host='0.0.0.0',#nosec B104
        port=8001,
        reload=False,
    )