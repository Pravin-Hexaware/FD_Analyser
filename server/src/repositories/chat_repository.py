"""Chat / conversation repository — Tortoise only."""
from __future__ import annotations

import json
from typing import Any, Optional

from db.models import ChatHistory, ChatReference, Conversation, User


async def create_conversation(user_id: Optional[int] = None) -> int:
    user = None
    if user_id:
        user = await User.get_or_none(id=user_id)
    conv = await Conversation.create(user=user)
    return conv.id


async def conversation_exists(conversation_id: int) -> bool:
    return await Conversation.exists(id=conversation_id)


async def get_conversation(conversation_id: int) -> Optional[dict]:
    conv = await Conversation.get_or_none(id=conversation_id)
    if not conv:
        return None
    return {
        "id": conv.id,
        "user_id": conv.user_id,
        "created_at": str(conv.created_time) if conv.created_time else None,
        "created_time": str(conv.created_time) if conv.created_time else None,
    }


async def get_next_sequence_number(conversation_id: int) -> int:
    last = await ChatHistory.filter(conversation_id=conversation_id).order_by("-sequence_number").first()
    return (last.sequence_number + 1) if last else 1


async def save_message(
    conversation_id: int,
    role: str,
    content: str,
    *,
    user_id: Optional[int] = None,
) -> int:
    """
    Map old role-based messages into chat_History query/response pairs.
    user role → fills query on a new or open turn; llm role → fills response.
    """
    seq = await get_next_sequence_number(conversation_id)
    user = await User.get_or_none(id=user_id) if user_id else None

    if role == "user":
        msg = await ChatHistory.create(
            conversation_id=conversation_id,
            user=user,
            sequence_number=seq,
            query=content,
            response=None,
        )
        return msg.id

    # llm / assistant: attach to last message without response, else create new
    last = await ChatHistory.filter(conversation_id=conversation_id).order_by("-sequence_number").first()
    if last and (last.response is None or last.response == ""):
        last.response = content
        await last.save()
        return last.id
    msg = await ChatHistory.create(
        conversation_id=conversation_id,
        user=user,
        sequence_number=seq,
        query=None,
        response=content,
    )
    return msg.id


async def get_conversation_messages(conversation_id: int) -> list[dict]:
    rows = await ChatHistory.filter(conversation_id=conversation_id).order_by("sequence_number")
    out = []
    for r in rows:
        if r.query:
            out.append(
                {
                    "id": r.id,
                    "conversation_id": conversation_id,
                    "sequence_number": r.sequence_number,
                    "role": "user",
                    "content": r.query,
                    "created_at": str(r.created_at) if r.created_at else None,
                }
            )
        if r.response:
            out.append(
                {
                    "id": r.id,
                    "conversation_id": conversation_id,
                    "sequence_number": r.sequence_number,
                    "role": "llm",
                    "content": r.response,
                    "created_at": str(r.created_at) if r.created_at else None,
                }
            )
    return out


async def get_conversation_list() -> list[dict]:
    convs = await Conversation.all().order_by("-id")
    out = []
    for c in convs:
        first = await ChatHistory.filter(conversation_id=c.id).order_by("sequence_number").first()
        out.append(
            {
                "id": c.id,
                "created_at": str(c.created_time) if c.created_time else None,
                "preview": (first.query or first.response or "")[:120] if first else "",
            }
        )
    return out


async def save_chat(chat_id: str, user_query: str, response: str) -> None:
    """Legacy chat_id string API → store as a new conversation turn."""
    # Use chat_id hash as synthetic: create conversation if numeric else new
    conv_id = None
    if str(chat_id).isdigit():
        conv_id = int(chat_id)
        if not await conversation_exists(conv_id):
            conv_id = await create_conversation()
    else:
        conv_id = await create_conversation()
    await save_message(conv_id, "user", user_query)
    await save_message(conv_id, "llm", response)


async def save_detailed_log(chat_id: str, step_name: str, input_data: str, output_data: str) -> None:
    """No dedicated llm_detailed_log table — store as ChatReference investor_info blob."""
    payload = json.dumps(
        {"chat_id": chat_id, "step_name": step_name, "input": input_data, "output": output_data},
        ensure_ascii=False,
    )
    await ChatReference.create(
        messages_id=int(chat_id) if str(chat_id).isdigit() else None,
        investor_info=payload,
    )


async def get_chat_history() -> list:
    rows = await ChatHistory.all().order_by("-id").limit(200)
    return [
        {
            "chat_id": str(r.id),
            "user_query": r.query or "",
            "response": r.response or "",
            "created_at": str(r.created_at) if r.created_at else None,
        }
        for r in rows
        if r.query or r.response
    ]


async def get_chat_by_id(chat_id: str) -> Optional[dict]:
    if not str(chat_id).isdigit():
        return None
    r = await ChatHistory.get_or_none(id=int(chat_id))
    if not r:
        return None
    return {
        "chat_id": str(r.id),
        "user_query": r.query or "",
        "response": r.response or "",
        "created_at": str(r.created_at) if r.created_at else None,
    }


async def attach_reference(
    messages_id: int,
    *,
    xbrl_data_ids: Any = None,
    news_articles: Any = None,
    investor_info: Optional[str] = None,
) -> int:
    ref = await ChatReference.create(
        messages_id=messages_id,
        xbrl_data_ids=json.dumps(xbrl_data_ids) if not isinstance(xbrl_data_ids, str) else xbrl_data_ids,
        news_articles=json.dumps(news_articles) if news_articles and not isinstance(news_articles, str) else news_articles,
        investor_info=investor_info,
    )
    msg = await ChatHistory.get_or_none(id=messages_id)
    if msg:
        msg.reference_id = ref.id
        await msg.save()
    return ref.id
