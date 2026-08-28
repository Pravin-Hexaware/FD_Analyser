from __future__ import annotations

import csv
import json
import logging
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from threading import current_thread


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
        self.log_event("phase", phase=phase, status=status, **details)

    def log_report(self, phase: str, report: Any) -> None:
        self.log_event("report_generation", phase=phase, report=report)

    def log_error(self, component: str, error: Exception | str, exc_info: bool = True) -> None:
        details: Dict[str, Any] = {"component": component, "error": str(error)}
        if exc_info:
            details["stack_trace"] = "".join(traceback.format_exception(type(error), error, error.__traceback__)) if isinstance(error, Exception) else traceback.format_exc()
        self.log_event("error", **details)

    def finalize(self, total_execution_time_ms: float, api_time_ms: float, db_time_ms: float, **details: Any) -> None:
        self.log_event(
            "execution_complete",
            total_execution_time_ms=total_execution_time_ms,
            api_execution_time_ms=api_time_ms,
            database_execution_time_ms=db_time_ms,
            **details,
        )
        self._logger.info("=== CHATBOT EXECUTION END ===")
        self.close()

    def close(self) -> None:
        """Flush and close this request's file handler."""
        with self._lock:
            for handler in self._logger.handlers[:]:
                handler.flush()
                handler.close()
                self._logger.removeHandler(handler)


class LoggingService:
    """Centralized logging service for chatbot execution logs and audit registry logs."""

    def __init__(self, base_dir: Optional[Path | str] = None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1])
        self.logs_dir = self.base_dir / "logs"
        self.overall_logs_dir = self.base_dir / "Overall_logs"
        self._lock = threading.RLock()
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            self.overall_logs_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    def create_chatbot_logger(self, user_query: str, conversation_id: Optional[int] = None, request_id: Optional[str] = None) -> ChatbotExecutionLogger:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        request_id = request_id or f"req-{timestamp}"
        log_path = self.logs_dir / f"Log-{timestamp}.log"
        return ChatbotExecutionLogger(log_path=log_path, request_id=request_id, user_query=user_query, conversation_id=conversation_id)

    def create_chat_log(self, user_query: str, conversation_id: Optional[int] = None, request_id: Optional[str] = None) -> ChatbotExecutionLogger:
        """Create a detailed per-chat log without changing the existing log files."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        request_id = request_id or f"chat-{timestamp}"
        log_path = self.logs_dir / "chat" / f"chat{timestamp}.log"
        return ChatbotExecutionLogger(log_path=log_path, request_id=request_id, user_query=user_query, conversation_id=conversation_id)

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
