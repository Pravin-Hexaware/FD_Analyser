from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import KEY_VAULT_URL
from services.analysis_service import _get_llm, _normalize_llm_response


def markdownify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def extract_code_from_markdown(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"```(?:python|py)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_markdown_to_data(text: str) -> Any:
    if not text:
        return None
    stripped = text.strip()
    for candidate in (stripped, extract_code_from_markdown(stripped)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return {"content": stripped}


def _extract_content(response: Any) -> Any:
    normalized = _normalize_llm_response(response)
    content = normalized.get("content")
    if content:
        return content
    return normalized or response


def evaluate_with_azure_llm(prompt: str, cache_path: Optional[str] = None) -> Any:
    llm = _get_llm()
    response = llm.invoke(
        [
            SystemMessage(content="Return the best possible result for the provided prompt."),
            HumanMessage(content=prompt),
        ],
        max_tokens=8000,
    )
    content = _extract_content(response)
    if cache_path:
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdownify(content), encoding="utf-8")
    parsed = parse_markdown_to_data(content if isinstance(content, str) else markdownify(content))
    if isinstance(parsed, dict) and parsed.get("content") == content:
        return content
    return parsed
