"""
Load LLM / agent prompt templates from ``server/src/prompts/*.md``.

Usage:
    from prompts.loader import load_prompt
    text = load_prompt("coding_system_prompt.md")
    text = load_prompt("orchestration_heal_goal.md", test_input="500325")
"""

from __future__ import annotations

from pathlib import Path
from string import Formatter
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent


class _SafeDict(dict):
    """Leave unknown ``{placeholders}`` intact so nested braces / JSON examples survive."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _read_raw(name: str) -> str:
    """Read prompt file from disk each time so edits apply without server restart."""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_prompt(name: str, **kwargs: Any) -> str:
    """
    Load a prompt markdown file and optionally format ``{placeholders}``.

    Only keys present in ``kwargs`` are substituted. Unknown braces in the
    template (e.g. JSON examples written as ``{{`` / ``}}`` or leftover
    ``{foo}``) are left as-is when using doubled braces, or preserved via
    safe substitution for missing keys.
    """
    raw = _read_raw(name).strip() + "\n"
    if not kwargs:
        return raw
    # Support standard str.format with doubled braces for literals.
    try:
        return raw.format(**kwargs)
    except (KeyError, ValueError):
        # Fallback: only replace provided keys.
        return Formatter().vformat(raw, (), _SafeDict(**kwargs))


def prompt_path(name: str) -> Path:
    return PROMPTS_DIR / name


def list_prompts() -> list[str]:
    return sorted(p.name for p in PROMPTS_DIR.glob("*.md") if p.name.upper() != "README.MD")
