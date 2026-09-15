from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from services.analysis_service import _get_llm, _normalize_llm_response
from utils.langsmith_tracing import llm_run_config


def markdownify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def extract_code_from_markdown(text: str) -> str:
    if not text:
        return ""
    python_blocks = re.findall(r"```(?:python|py)\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if python_blocks:
        return max((block.strip() for block in python_blocks), key=len)
    match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_json_object(text: str) -> Optional[Any]:
    if not text or not isinstance(text, str):
        return None
    stripped = text.strip()
    # Direct JSON
    for candidate in (stripped,):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    # Fenced json / bare fence
    for pattern in (
        r"```(?:json|javascript)?\s*(.*?)```",
        r"(\{[\s\S]*\})",
        r"(\[[\s\S]*\])",
    ):
        match = re.search(pattern, stripped, re.DOTALL | re.IGNORECASE)
        if not match:
            continue
        blob = match.group(1).strip()
        try:
            return json.loads(blob)
        except Exception:
            continue
    return None


def unwrap_llm_payload(value: Any) -> Any:
    """
    Unwrap common LLM envelope shapes:
    - {"markdown": "```json ..."}
    - {"content": "..."}
    - {"final_analysis": "..."}
    - nested stringified JSON
    """
    if value is None:
        return None
    if isinstance(value, (list, int, float, bool)):
        return value
    if isinstance(value, str):
        parsed = extract_json_object(value)
        return parsed if parsed is not None else value
    if not isinstance(value, dict):
        return value

    # Prefer known structured keys if present alongside wrappers
    for key in ("elements_to_replace", "goal", "code", "generated_code", "script"):
        if key in value:
            return value

    for key in ("markdown", "content", "answer", "final_analysis", "analysis", "raw"):
        if key in value and value.get(key) is not None:
            inner = value.get(key)
            if isinstance(inner, str):
                parsed = extract_json_object(inner)
                if parsed is not None:
                    return parsed
                # strip outer markdown fence then retry
                codeish = extract_code_from_markdown(inner)
                if codeish and codeish != inner:
                    parsed = extract_json_object(codeish)
                    if parsed is not None:
                        return parsed
                return inner
            if isinstance(inner, dict):
                return unwrap_llm_payload(inner)
            return inner
    return value


def parse_markdown_to_data(text: str) -> Any:
    if not text:
        return None
    stripped = text.strip()
    # Try JSON first (including fenced)
    parsed = extract_json_object(stripped)
    if parsed is not None:
        return unwrap_llm_payload(parsed)
    fenced = extract_code_from_markdown(stripped)
    if fenced:
        parsed = extract_json_object(fenced)
        if parsed is not None:
            return unwrap_llm_payload(parsed)
    return {"content": stripped}


def _extract_content(response: Any) -> Any:
    normalized = _normalize_llm_response(response)
    content = normalized.get("content")
    if content:
        return content
    return normalized or response


def evaluate_with_azure_llm(
    prompt: str,
    cache_path: Optional[str] = None,
    *,
    max_tokens: int = 8000,
    system: Optional[str] = None,
    parse_json: bool = True,
    run_name: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Any:
    """
    Invoke Azure LLM.

    parse_json=True (default): attempt to parse structured JSON from the reply.
    parse_json=False: return raw text (used by coding agent fence format).
    """
    llm = _get_llm()
    system_text = system or (
        "Return the best possible result for the provided prompt. "
        "When asked for structured data, prefer a single JSON object."
    )
    trace_tags = list(tags or ["azure-llm"])
    trace_metadata = dict(metadata or {})
    if cache_path:
        trace_metadata.setdefault("cache_path", cache_path)
    config = llm_run_config(
        run_name or "azure_llm",
        tags=trace_tags,
        metadata=trace_metadata or None,
    )
    response = llm.invoke(
        [
            SystemMessage(content=system_text),
            HumanMessage(content=prompt),
        ],
        max_tokens=max_tokens,
        config=config,
    )
    content = _extract_content(response)
    if cache_path:
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw_text = content if isinstance(content, str) else markdownify(content)
        path.write_text(raw_text if isinstance(raw_text, str) else markdownify(raw_text), encoding="utf-8")
    if not parse_json:
        return content if isinstance(content, str) else markdownify(content)
    if isinstance(content, str):
        parsed = parse_markdown_to_data(content)
    else:
        parsed = unwrap_llm_payload(content)
    if isinstance(parsed, dict) and parsed.get("content") == content and len(parsed) == 1:
        return content
    return parsed if parsed is not None else content
