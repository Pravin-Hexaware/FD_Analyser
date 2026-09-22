"""LangSmith / LangChain tracing configuration for FinBot LLM and agent runs."""

from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

_CONFIGURED = False

F = TypeVar("F", bound=Callable[..., Any])


def configure_langsmith() -> bool:
    """Enable LangSmith tracing via environment variables (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return is_langsmith_enabled()

    api_key = (
        os.getenv("LANGSMITH_API_KEY", "").strip()
        or os.getenv("LANGCHAIN_API_KEY", "").strip()
    )
    if not api_key:
        logger.info("LangSmith tracing disabled (set LANGSMITH_API_KEY to enable)")
        _CONFIGURED = True
        return False

    tracing_flag = (
        os.getenv("LANGSMITH_TRACING", "").strip()
        or os.getenv("LANGCHAIN_TRACING_V2", "true").strip()
    ).lower()
    if tracing_flag in {"0", "false", "no", "off"}:
        logger.info("LangSmith tracing disabled (LANGSMITH_TRACING=false)")
        _CONFIGURED = True
        return False

    os.environ.setdefault("LANGSMITH_API_KEY", api_key)
    os.environ.setdefault("LANGCHAIN_API_KEY", api_key)
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")

    project = (
        os.getenv("LANGSMITH_PROJECT", "").strip()
        or os.getenv("LANGCHAIN_PROJECT", "").strip()
        or "finbot"
    )
    os.environ.setdefault("LANGSMITH_PROJECT", project)
    os.environ.setdefault("LANGCHAIN_PROJECT", project)

    endpoint = os.getenv("LANGSMITH_ENDPOINT", "").strip()
    if endpoint:
        os.environ.setdefault("LANGSMITH_ENDPOINT", endpoint)

    _CONFIGURED = True
    logger.info("LangSmith tracing enabled (project=%s)", project)
    return True


def is_langsmith_enabled() -> bool:
    """Return True when LangSmith tracing env vars are active."""
    tracing = (
        os.getenv("LANGSMITH_TRACING", "").strip()
        or os.getenv("LANGCHAIN_TRACING_V2", "").strip()
    ).lower()
    if tracing in {"0", "false", "no", "off"}:
        return False
    if tracing in {"1", "true", "yes", "on"}:
        return bool(
            os.getenv("LANGSMITH_API_KEY", "").strip()
            or os.getenv("LANGCHAIN_API_KEY", "").strip()
        )
    return False


def llm_run_config(
    run_name: str,
    *,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a LangChain RunnableConfig dict for invoke/stream/graph calls."""
    config: dict[str, Any] = {"run_name": run_name}
    if tags:
        config["tags"] = tags
    if metadata:
        config["metadata"] = {
            key: value for key, value in metadata.items() if value is not None
        }
    return config


def merge_run_config(
    run_name: str,
    *,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
    configurable: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Like ``llm_run_config`` but also supports LangGraph ``configurable`` keys."""
    config = llm_run_config(run_name, tags=tags, metadata=metadata)
    if configurable:
        config["configurable"] = configurable
    return config


def traceable_run(
    name: str,
    *,
    run_type: str = "chain",
    tags: Optional[list[str]] = None,
) -> Callable[[F], F]:
    """Apply ``@traceable`` when LangSmith is enabled; otherwise no-op."""

    def decorator(func: F) -> F:
        traced_fn: Optional[F] = None

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal traced_fn
            if not is_langsmith_enabled():
                return func(*args, **kwargs)
            if traced_fn is None:
                try:
                    from langsmith import traceable
                except ImportError:
                    logger.warning(
                        "langsmith package not installed; skipping traceable for %s", name
                    )
                    return func(*args, **kwargs)
                traced_fn = traceable(name=name, run_type=run_type, tags=tags or [])(func)
            return traced_fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def langsmith_status() -> dict[str, Any]:
    """Summary for startup logs."""
    return {
        "enabled": is_langsmith_enabled(),
        "project": os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "finbot",
    }
