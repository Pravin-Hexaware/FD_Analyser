from dotenv import load_dotenv
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

_src_dir = Path(__file__).resolve().parent
load_dotenv()
load_dotenv(_src_dir.parent / ".env")

from utils.langsmith_tracing import configure_langsmith, langsmith_status

configure_langsmith()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from routes.companies import router as companies_router
from routes.llm import router as llm_router
from routes.missing_companies import router as missing_companies_router
from routes.news_ws import router as news_ws_router
from routes.xbrl_ws import router as xbrl_ws_router
from routes.heal_demo import router as heal_demo_router
from services.analysis_service import initialize_llm
from services.logging_service import logging_service
from utils.llm_testing import get_llm_provider_name
from db.lifespan import init_db, close_db
import importlib
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import socket


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    host = socket.gethostbyname(socket.gethostname())
    logging_service.configure_server_file_logging()
    session_log = logging_service.start_application_session(host=host, llm_provider=get_llm_provider_name())
    logging_service.log_application_event("startup_begin", session_log=str(session_log))
    try:
        from services.analysis_service import get_llm_id
        app.state.llm = initialize_llm()
        app.state.llm_id = get_llm_id()
        importlib.import_module("services.news_agent_service")
        logging_service.append_audit_entry("APPLICATION STARTED", "-", host)
        ls = langsmith_status()
        logging_service.log_application_event(
            "startup_success",
            llm_provider=get_llm_provider_name(),
            llm_id=app.state.llm_id,
            langsmith_enabled=ls["enabled"],
            langsmith_project=ls["project"],
        )
        print("[startup] Azure LLM and news agent initialized.")
        if ls["enabled"]:
            print(f"[OK] LangSmith tracing enabled (project={ls['project']})")
        else:
            print("[INFO] LangSmith tracing disabled (set LANGSMITH_API_KEY in .env to enable)")
        print(f"[OK] LLM initialized with ID: {app.state.llm_id}")
        print(f"[INFO] Session log: {session_log}")
        print(f"[INFO] Agent sessions dir: {logging_service.agent_sessions_dir}")
        try:
            from services.nifty500_scheduler_service import Nifty500SchedulerService

            await Nifty500SchedulerService.schedule_on_startup()
        except Exception as nifty_exc:
            print(f"[WARN] Nifty 500 scheduler failed to start: {nifty_exc}")
            logging_service.log_application_event(
                "nifty500_scheduler_start_failed", error=str(nifty_exc)
            )
    except Exception as exc:
        logging_service.append_audit_entry("APPLICATION STARTED", "-", host)
        logging_service.log_application_event("startup_failed", error=str(exc))
        print(f"[ERROR] Startup initialization failed: {exc}")
    yield
    await close_db()


app = FastAPI(title="Financial Data Extractor API", lifespan=lifespan)


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(llm_router, prefix="/api", tags=["llm"])
app.include_router(companies_router, prefix="/api", tags=["companies"])
app.include_router(missing_companies_router, prefix="/api", tags=["missing_companies"])
app.include_router(news_ws_router, prefix="/api", tags=["news_ws"])
app.include_router(xbrl_ws_router, prefix="/api", tags=["xbrl_ws"])
app.include_router(heal_demo_router, prefix="/api", tags=["heal_demo"])


if __name__ == "__main__":
    import uvicorn

    # Avoid Windows cp1252 crashes on Unicode agent/runtime logs.
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    uvicorn.run(
        "main:app",
        host="0.0.0.0",  # nosec B104
        port=8001,
        reload=False,
    )
