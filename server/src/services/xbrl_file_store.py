"""Local XBRL raw file storage under Data/XBRLS/{std|con}/{scripcode}/{period}.{html|xml}."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from config.settings import XBRLS_DIR


def _safe_period(period: str) -> str:
    return re.sub(r'[/\\:*?"<>|]', "_", (period or "").strip())


def _normalize_category(category: str) -> str:
    cat = (category or "std").strip().lower()
    if cat not in ("std", "con"):
        cat = "std"
    return cat


def _extension_from_url(url: str) -> str:
    return "xml" if (url or "").lower().endswith(".xml") else "html"


def xbrl_file_path(
    scrip_code: str,
    category: str,
    period: str,
    *,
    url: str = "",
    ext: Optional[str] = None,
) -> Path:
    cat = _normalize_category(category)
    safe = _safe_period(period)
    extension = (ext or _extension_from_url(url)).lstrip(".")
    return XBRLS_DIR / cat / str(scrip_code).strip() / f"{safe}.{extension}"


def save_xbrl_raw(
    scrip_code: str,
    category: str,
    period: str,
    raw_content: str,
    url: str = "",
) -> Optional[str]:
    """Write raw XBRL HTML/XML to disk. Returns absolute path string or None on failure."""
    try:
        path = xbrl_file_path(scrip_code, category, period, url=url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw_content if isinstance(raw_content, str) else str(raw_content), encoding="utf-8")
        return str(path)
    except Exception as exc:
        print(f"[xbrl_file_store] save failed for {scrip_code}/{period}: {exc}")
        return None


def read_xbrl_raw(
    scrip_code: str,
    category: str,
    period: str,
    *,
    url: str = "",
) -> Optional[str]:
    """Read raw content from disk. Tries both html and xml if extension unknown."""
    cat = _normalize_category(category)
    safe = _safe_period(period)
    base = XBRLS_DIR / cat / str(scrip_code).strip()
    candidates = []
    if url:
        candidates.append(xbrl_file_path(scrip_code, category, period, url=url))
    candidates.extend([base / f"{safe}.html", base / f"{safe}.xml"])
    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                print(f"[xbrl_file_store] read failed {path}: {exc}")
                return None
    return None


def xbrl_raw_exists(scrip_code: str, category: str, period: str, *, url: str = "") -> bool:
    return read_xbrl_raw(scrip_code, category, period, url=url) is not None
