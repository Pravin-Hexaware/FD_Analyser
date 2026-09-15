from __future__ import annotations

import csv
import json
import logging
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from threading import current_thread

PHASE_KEYWORD_MAP: Dict[str, str] = {
    "request_start": "PHASE_NLP_PARSE",
    "company_validate": "PHASE_COMPANY_VALIDATE",
    "db_fetch": "PHASE_DB_FETCH",
    "news_fetch": "PHASE_NEWS_FETCH",
    "report_generation": "PHASE_LLM_REPORT",
    "xbrl_navigate": "PHASE_XBRL_NAVIGATE",
    "xbrl_search": "PHASE_XBRL_SEARCH",
    "xbrl_filters": "PHASE_XBRL_FILTERS",
    "xbrl_submit": "PHASE_XBRL_SUBMIT",
    "xbrl_grid": "PHASE_XBRL_GRID",
    "xbrl_extract": "PHASE_XBRL_EXTRACT",
    "agent_dom": "PHASE_AGENT_DOM",
    "agent_analysis": "PHASE_AGENT_ANALYSIS",
    "agent_codegen": "PHASE_AGENT_CODEGEN",
    "agent_thinking": "PHASE_AGENT_THINKING",
    "agent_test": "PHASE_AGENT_TEST",
    "agent_swap": "PHASE_AGENT_SWAP",
    "agent_session": "PHASE_AGENT_SESSION",
    "xbrl_field": "PHASE_XBRL_FIELD",
    "playwright_heal_trigger": "PLAYWRIGHT_HEAL_TRIGGER",
}


def resolve_phase_keyword(phase: str) -> str:
    normalized = (phase or "").strip().lower()
    if normalized in PHASE_KEYWORD_MAP:
        return PHASE_KEYWORD_MAP[normalized]
    fallback = normalized.upper().replace("-", "_").replace(" ", "_")
    return f"PHASE_{fallback}" if fallback else "PHASE_UNKNOWN"


class ChatbotExecutionLogger:
    """Thread-safe logger for a single chatbot request lifecycle."""

    def __init__(self, log_path: Path, request_id: str, user_query: str, conversation_id: Optional[int] = None):
        self.log_path = log_path
        self.request_id = request_id
        self.user_query = user_query
        self.conversation_id = conversation_id
        self._lock = threading.RLock()
        self._start_time = time.perf_counter()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"financial_data_extractor.chatbot.{request_id}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._logger.handlers.clear()

        handler = logging.FileHandler(self.log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        self._logger.addHandler(handler)

        self._write_header()

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    def _write_header(self) -> None:
        try:
            self._logger.info("=== CHATBOT EXECUTION START ===")
            self._logger.info("Request ID: %s", self.request_id)
            self._logger.info("Conversation ID: %s", self.conversation_id if self.conversation_id is not None else "-")
            self._logger.info("User Input: %s", self.user_query)
        except Exception:
            pass

    def log_event(self, event: str, **details: Any) -> None:
        try:
            with self._lock:
                payload = {"event": event, **details, "request_id": self.request_id, "thread": current_thread().name}
                self._logger.info(json.dumps(payload, default=str, ensure_ascii=False))
        except Exception:
            pass

    def log_nlp_breakdown(self, breakdown: Dict[str, Any]) -> None:
        self.log_event("nlp_breakdown", breakdown=breakdown)

    def log_database_operation(self, operation: str, query: str, parameters: Any, records_returned: Any, execution_time_ms: float) -> None:
        self.log_event(
            "database_operation",
            operation=operation,
            query=query,
            parameters=parameters,
            records_returned=records_returned,
            execution_time_ms=execution_time_ms,
        )

    def log_news_processing(self, **details: Any) -> None:
        self.log_event("news_processing", **details)

    def log_phase(self, phase: str, status: str, **details: Any) -> None:
        self.log_event("phase", phase=phase, status=status, keyword=resolve_phase_keyword(phase), **details)

    def log_report(self, phase: str, report: Any) -> None:
        self.log_event("report_generation", phase=phase, report=report)

    def log_error(self, component: str, error: Exception | str, exc_info: bool = True) -> None:
        details: Dict[str, Any] = {"component": component, "error": str(error)}
        if exc_info:
            details["stack_trace"] = "".join(traceback.format_exception(type(error), error, error.__traceback__)) if isinstance(error, Exception) else traceback.format_exc()
        self.log_event("error", **details)

    def log_runtime(self, message: str, **details: Any) -> None:
        line = message
        if details:
            line = f"{message} | " + " | ".join(f"{key}={value}" for key, value in details.items())
        try:
            with self._lock:
                self._logger.info(line)
        except Exception:
            pass

    def finalize(self, total_execution_time_ms: float, api_time_ms: float, db_time_ms: float, **details: Any) -> None:
        self.log_event(
            "execution_complete",
            total_execution_time_ms=total_execution_time_ms,
            api_execution_time_ms=api_time_ms,
            database_execution_time_ms=db_time_ms,
            **details,
        )
        self._logger.info("=== CHATBOT EXECUTION END ===")


class LoggingService:
    """Centralized logging service for chatbot execution logs and audit registry logs."""

    def __init__(self, base_dir: Optional[Path | str] = None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1])
        self.logs_dir = self.base_dir / "logs"
        self.overall_logs_dir = self.base_dir / "Overall_logs"
        self.agent_sessions_dir = self.logs_dir / "agent_sessions"
        self.app_log_path = self.logs_dir / "application.log"
        self.session_log_path: Optional[Path] = None
        self.agent_session_log_path: Optional[Path] = None
        self._session_handler: Optional[logging.Handler] = None
        self._agent_session_handler: Optional[logging.Handler] = None
        self._lock = threading.RLock()
        self._app_logger: Optional[logging.Logger] = None
        self._agent_logger: Optional[logging.Logger] = None
        self._request_context = threading.local()
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            self.overall_logs_dir.mkdir(parents=True, exist_ok=True)
            self.agent_sessions_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    def _app_log_formatter(self) -> logging.Formatter:
        return logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def _attach_file_handler(self, logger: logging.Logger, log_path: Path) -> logging.Handler:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(self._app_log_formatter())
        logger.addHandler(handler)
        return handler

    def _detach_handler(self, logger: logging.Logger, handler: Optional[logging.Handler]) -> None:
        if handler is None:
            return
        try:
            logger.removeHandler(handler)
            handler.close()
        except Exception:
            pass

    def _get_app_logger(self) -> logging.Logger:
        if self._app_logger is not None:
            return self._app_logger

        logger = logging.getLogger("financial_data_extractor.application")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()

        self._attach_file_handler(logger, self.app_log_path)
        self._app_logger = logger
        return logger

    def _get_agent_logger(self) -> logging.Logger:
        """Dedicated logger for agent sessions (does not duplicate into app SessionLog)."""
        if self._agent_logger is not None:
            return self._agent_logger
        logger = logging.getLogger("financial_data_extractor.agent_session")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()
        self._agent_logger = logger
        return logger

    def start_application_session(self, **meta: Any) -> Path:
        """Open a timestamped session log alongside application.log for manual review."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_path = self.logs_dir / f"SessionLog-{timestamp}.log"
        try:
            with self._lock:
                logger = self._get_app_logger()
                # Prevent handler accumulation (old "loop log" symptom on restarts/reloads)
                self._detach_handler(logger, self._session_handler)
                self._session_handler = self._attach_file_handler(logger, session_path)
                self.session_log_path = session_path
                logger.info("=== APPLICATION SESSION START ===")
                logger.info("Session log: %s", session_path)
                logger.info("Application log: %s", self.app_log_path)
                for key, value in meta.items():
                    logger.info("%s: %s", key, value)
        except Exception:
            pass
        return session_path

    def start_agent_session(self, *, run_id: str, target_url: str = "", test_input: str = "", **meta: Any) -> Path:
        """
        Open a dedicated AgentSession log for one heal/agent pipeline run.
        Kept separate from SessionLog so agent noise does not flood the app session.
        """
        stamp = datetime.now().strftime("%Y%m%d_%H-%M-%S")
        path = self.agent_sessions_dir / f"AgentSession-{stamp}_{run_id}.log"
        try:
            with self._lock:
                logger = self._get_agent_logger()
                self._detach_handler(logger, self._agent_session_handler)
                self._agent_session_handler = self._attach_file_handler(logger, path)
                self.agent_session_log_path = path
                logger.info("=== AGENT SESSION START run_id=%s ===", run_id)
                logger.info("agent_session_log=%s", path)
                logger.info("target_url=%s", target_url)
                logger.info("test_input=%s", test_input)
                for key, value in meta.items():
                    logger.info("%s=%s", key, value)
        except Exception:
            pass
        return path

    def end_agent_session(self, *, run_id: str = "", status: str = "ended", **details: Any) -> None:
        try:
            with self._lock:
                logger = self._get_agent_logger()
                logger.info(
                    "=== AGENT SESSION END run_id=%s status=%s %s ===",
                    run_id,
                    status,
                    " ".join(f"{k}={v}" for k, v in details.items()),
                )
                self._detach_handler(logger, self._agent_session_handler)
                self._agent_session_handler = None
        except Exception:
            pass

    def log_agent_session(self, message: str, **details: Any) -> None:
        """Write a line only to the active agent session log (and a short app pointer)."""
        line = message
        if details:
            line = f"{message} | " + " | ".join(f"{k}={v}" for k, v in details.items())
        try:
            with self._lock:
                self._get_agent_logger().info(line)
        except Exception:
            pass

    def log_application_event(self, event: str, **details: Any) -> None:
        parts = [f"event={event}"]
        for key, value in details.items():
            parts.append(f"{key}={value}")
        line = " | ".join(parts)
        try:
            with self._lock:
                self._get_app_logger().info(line)
        except Exception:
            pass

    @staticmethod
    def _format_phase_line(keyword: str, status: str, phase: str, **details: Any) -> str:
        parts = [f"KEYWORD={keyword}", f"status={status}", f"phase={phase}"]
        for key, value in details.items():
            if key in {"event", "keyword", "phase", "status", "thread"}:
                continue
            parts.append(f"{key}={value}")
        return " | ".join(parts)

    def create_chatbot_logger(self, user_query: str, conversation_id: Optional[int] = None, request_id: Optional[str] = None) -> ChatbotExecutionLogger:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        request_id = request_id or f"req-{timestamp}"
        log_path = self.logs_dir / f"Log-{timestamp}.log"
        return ChatbotExecutionLogger(log_path=log_path, request_id=request_id, user_query=user_query, conversation_id=conversation_id)

    def set_request_logger(self, request_logger: Optional[ChatbotExecutionLogger]) -> None:
        self._request_context.logger = request_logger

    def clear_request_logger(self) -> None:
        self._request_context.logger = None

    def get_request_logger(self) -> Optional[ChatbotExecutionLogger]:
        return getattr(self._request_context, "logger", None)

    def log_runtime(
        self,
        message: str,
        *,
        request_logger: Optional[ChatbotExecutionLogger] = None,
        echo: bool = True,
        **details: Any,
    ) -> None:
        """Write operational console messages to application/session/request log files."""
        line = message
        if details:
            line = f"{message} | " + " | ".join(f"{key}={value}" for key, value in details.items())
        if echo:
            try:
                print(message if not details else line)
            except UnicodeEncodeError:
                safe = (message if not details else line).encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                    sys.stdout.encoding or "utf-8", errors="replace"
                )
                print(safe)
        try:
            with self._lock:
                self._get_app_logger().info(line)
            active_logger = request_logger or self.get_request_logger()
            if active_logger is not None:
                active_logger.log_runtime(line)
        except Exception:
            pass

    def configure_server_file_logging(self) -> None:
        """Mirror uvicorn access/error logs into application.log for manual review."""
        handler = logging.FileHandler(self.app_log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        app_log = str(self.app_log_path.resolve())
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(name)
            if any(getattr(existing, "baseFilename", "") == app_log for existing in logger.handlers if isinstance(existing, logging.FileHandler)):
                continue
            logger.addHandler(handler)

    def log_phase(self, phase: str, status: str, **details: Any) -> None:
        """
        Single readable line to application/session log (no duplicate JSON twin).
        Agent-related phases are also mirrored into the active AgentSession log.
        """
        keyword = resolve_phase_keyword(phase)
        readable = self._format_phase_line(keyword, status, phase, **details)
        payload = {
            "event": "phase",
            "keyword": keyword,
            "phase": phase,
            "status": status,
            "thread": current_thread().name,
            **details,
        }
        try:
            with self._lock:
                self._get_app_logger().info(readable)
                # Mirror agent / heal / field events into dedicated agent session (JSON once there)
                agent_phases = {
                    "agent_dom",
                    "agent_analysis",
                    "agent_codegen",
                    "agent_thinking",
                    "agent_test",
                    "agent_swap",
                    "agent_session",
                    "xbrl_field",
                    "playwright_heal_trigger",
                }
                if phase in agent_phases or str(phase).startswith("agent_") or str(phase).startswith("xbrl_"):
                    agent_logger = self._get_agent_logger()
                    if self._agent_session_handler is not None:
                        agent_logger.info(readable)
                        agent_logger.info(json.dumps(payload, default=str, ensure_ascii=False))
        except Exception:
            pass
        try:
            active_logger = self.get_request_logger()
            if active_logger is not None:
                active_logger.log_phase(phase, status, **details)
        except Exception:
            pass

    def log_field(
        self,
        field: str,
        status: str,
        *,
        action: str = "interact",
        selector: str = "",
        value: Any = None,
        phase: str = "xbrl_field",
        error: Any = None,
        **details: Any,
    ) -> None:
        """
        Per-control pass/fail log for dropdowns/inputs/buttons.
        Also appends a compact FIELD= line to cache/generated_script_runtime.log for the coding agent.
        """
        payload = {
            "field": field,
            "action": action,
            "field_status": status,
            "selector": selector,
            "value": value,
            "error": error,
            **details,
        }
        # Drop Nones for readability
        payload = {k: v for k, v in payload.items() if v is not None and v != ""}
        self.log_phase(phase, status, **payload)

        # Compact line for harness / coding-agent regen
        compact = (
            f"FIELD field={field} action={action} status={status}"
            + (f" selector={selector}" if selector else "")
            + (f" value={value}" if value is not None else "")
            + (f" error={error}" if error else "")
        )
        try:
            import os

            env_path = os.environ.get("FINBOT_RUNTIME_LOG", "").strip()
            if env_path:
                runtime_path = Path(env_path)
            else:
                runtime_path = self.base_dir / "cache" / "generated_script_runtime.log"
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with runtime_path.open("a", encoding="utf-8") as handle:
                    handle.write(compact + "\n")
        except Exception:
            pass

    def log_heal_trigger(self, reason: str, **details: Any) -> None:
        # `phase` is a reserved log_phase kwarg; remap so callers can pass the failing portal phase.
        details = dict(details)
        if "phase" in details:
            details["failed_phase"] = details.pop("phase")
        self.log_phase("playwright_heal_trigger", "failed", reason=reason, **details)

    def log_agent_thinking(self, agent: str, thoughts: Any, *, run_id: Optional[str] = None) -> None:
        """Persist agent reasoning to agent session (+ short app pointer)."""
        if thoughts is None:
            return
        if isinstance(thoughts, (dict, list)):
            text = json.dumps(thoughts, ensure_ascii=False, indent=2)
        else:
            text = str(thoughts).strip()
        if not text:
            return
        if len(text) > 4000:
            text = text[:4000] + "\n...[truncated]..."
        # Prefer agent session for full text; app log gets a short marker
        self.log_agent_session(f"[THINKING agent={agent}]", thoughts=text[:2000], run_id=run_id)
        self.log_phase(
            "agent_thinking",
            "progress",
            agent=agent,
            thoughts_preview=text[:500],
            run_id=run_id,
        )

    def get_daily_audit_path(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        day_dir = self.overall_logs_dir / today
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / f"Log-{today}.csv"

    def append_audit_entry(self, endpoint_url: str, response_status: Any, client_ip: str) -> Path:
        path = self.get_daily_audit_path()
        try:
            with self._lock:
                write_header = not path.exists() or path.stat().st_size == 0
                with path.open("a", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    if write_header:
                        writer.writerow(["Timestamp", "EndpointURL", "ResponseStatus", "ClientIP"])
                    writer.writerow([self._timestamp(), endpoint_url, response_status, client_ip])
        except Exception:
            pass
        return path


logging_service = LoggingService()
