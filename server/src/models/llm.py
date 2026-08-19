"""Pydantic schemas for LLM routes."""
from typing import Dict, List, Optional

from pydantic import BaseModel


class LLMQueryRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None


class ChatHistoryResponse(BaseModel):
    chat_id: str
    title: str
    created_at: str
    last_message: Optional[str] = None


class ChatMessageResponse(BaseModel):
    id: int
    sequence_number: int
    role: str
    content: str
    created_at: str


class ConversationResponse(BaseModel):
    chat_id: str
    title: str
    created_at: str
    messages: List[ChatMessageResponse]


class ProgressMessage(BaseModel):
    stage: str
    timestamp: str


class LLMTargetCompaniesResponse(BaseModel):
    chat_id: str
    answer: str
    tokens_used: Dict[str, int]
    progress_messages: List[ProgressMessage]
    invalid_companies: Optional[List[str]] = None
    background_note: Optional[str] = None
