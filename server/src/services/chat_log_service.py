"""Structured chat session logs under ``logs/chat_logs/``."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config.settings import LOGS_DIR

CHAT_LOGS_DIR = LOGS_DIR / "chat_logs"


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


class ChatSessionLog:
    """Accumulate chat pipeline artifacts and write one file per request."""

    def __init__(
        self,
        *,
        query: str,
        conversation_id: Optional[int] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        CHAT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_conv{conversation_id}" if conversation_id is not None else ""
        self.path = CHAT_LOGS_DIR / f"ChatLog-{stamp}{suffix}.log"
        self.query = query
        self.conversation_id = conversation_id
        self.chat_id = chat_id
        self.query_breakdown: Any = None
        self.db_data: Any = None
        self.phase1_prompt: str = ""
        self.phase1_response: str = ""
        self.news_collection_prompt: str = ""
        self.news_data_passed: Any = None
        self.news_response: str = ""
        self.phase2_prompt: str = ""
        self.phase2_response: str = ""
        self.mode: str = ""
        self.extra_notes: list[str] = []

    def set_query_breakdown(self, payload: Any) -> None:
        self.query_breakdown = payload

    def set_db_data(self, data: Any) -> None:
        self.db_data = data

    def set_phase1(self, prompt: str, response: str = "") -> None:
        self.phase1_prompt = prompt or ""
        if response:
            self.phase1_response = response

    def set_phase1_response(self, response: str) -> None:
        self.phase1_response = response or ""

    def set_news(
        self,
        *,
        prompt: str = "",
        data_passed: Any = None,
        response: str = "",
    ) -> None:
        if prompt:
            self.news_collection_prompt = prompt
        if data_passed is not None:
            self.news_data_passed = data_passed
        if response:
            self.news_response = response

    def set_phase2(self, prompt: str = "", response: str = "") -> None:
        if prompt:
            self.phase2_prompt = prompt
        if response:
            self.phase2_response = response

    def note(self, text: str) -> None:
        self.extra_notes.append(text)

    def write(self) -> Path:
        """Write (or overwrite) the chat log file."""
        CHAT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        notes = "\n".join(f"- {n}" for n in self.extra_notes) if self.extra_notes else "(none)"
        content = f"""=== CHAT SESSION LOG ===
Timestamp: {datetime.now().isoformat()}
Log File: {self.path.name}
Conversation ID: {self.conversation_id}
Chat ID: {self.chat_id}
Mode: {self.mode or "(unspecified)"}

--------------------------------------------------------------------------------
1. INPUT QUERY
--------------------------------------------------------------------------------
{self.query}

--------------------------------------------------------------------------------
2. QUERY BREAKDOWN JSON
--------------------------------------------------------------------------------
{_safe_json(self.query_breakdown)}

--------------------------------------------------------------------------------
3. DATA FETCHED FROM DATABASE
--------------------------------------------------------------------------------
{_safe_json(self.db_data)}

--------------------------------------------------------------------------------
4. PHASE 1 PROMPT (financial report)
--------------------------------------------------------------------------------
{self.phase1_prompt or "(not captured)"}

--------------------------------------------------------------------------------
5. NEWS COLLECTION PROMPT
--------------------------------------------------------------------------------
{self.news_collection_prompt or "(not captured / news not fetched)"}

--------------------------------------------------------------------------------
6. DATA PASSED TO NEWS COLLECTION / NEWS IMPACT
--------------------------------------------------------------------------------
{_safe_json(self.news_data_passed) if self.news_data_passed is not None else "(none)"}

--------------------------------------------------------------------------------
7. NEWS RESPONSE
--------------------------------------------------------------------------------
{self.news_response or "(none)"}

--------------------------------------------------------------------------------
8. PHASE 1 RESPONSE
--------------------------------------------------------------------------------
{self.phase1_response or "(none)"}

--------------------------------------------------------------------------------
9. PHASE 2 RESPONSE (news impact / final enhancement)
--------------------------------------------------------------------------------
{self.phase2_response or "(none / single-pass report)"}

--------------------------------------------------------------------------------
10. NOTES
--------------------------------------------------------------------------------
{notes}

=== END CHAT SESSION LOG ===
"""
        self.path.write_text(content, encoding="utf-8")
        return self.path
