"""Chat history service for LLM conversations."""
from fastapi import HTTPException

from models.llm import ChatHistoryResponse, ChatMessageResponse, ConversationResponse
from repositories.sqlite_repository import SqliteRepository


def get_chat_history() -> list[ChatHistoryResponse]:
    repo = SqliteRepository()
    try:
        chats = repo.get_conversation_list()
        return [
            ChatHistoryResponse(
                chat_id=str(chat["chat_id"]),
                created_at=chat.get("last_updated") or chat["created_at"],
                title=(chat.get("first_message") or "New conversation")[:50] + (
                    "..." if chat.get("first_message") and len(chat.get("first_message")) > 50 else ""
                ),
                last_message=chat.get("last_message"),
            )
            for chat in chats
        ]
    finally:
        repo.close()


def get_conversation(chat_id: str) -> ConversationResponse:
    try:
        conversation_id = int(chat_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chat id")

    repo = SqliteRepository()
    try:
        if not repo.conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="Chat not found")

        conversation = repo.get_conversation(conversation_id)
        messages = repo.get_conversation_messages(conversation_id)

        title = "Chat"
        if messages:
            title = messages[0]["content"][:50] + ("..." if len(messages[0]["content"]) > 50 else "")

        return ConversationResponse(
            chat_id=chat_id,
            created_at=conversation["created_at"],
            title=title,
            messages=[
                ChatMessageResponse(
                    id=msg["id"],
                    sequence_number=msg["sequence_number"],
                    role=msg["role"],
                    content=msg["content"],
                    created_at=msg["created_at"],
                )
                for msg in messages
            ],
        )
    finally:
        repo.close()


def delete_unknown_sector_companies() -> dict:
    repo = SqliteRepository()
    try:
        deleted_count = repo.delete_companies_by_sector("")
        return {"message": f"Successfully deleted {deleted_count} companies with 'Unknown Sector'."}
    finally:
        repo.close()
