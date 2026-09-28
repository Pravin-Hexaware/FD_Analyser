"""Shared Indian fiscal-year helpers for XBRL period filtering."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple

# Collect back through FY 2020-2021 (period labels like MQ2020-2021 / DC2020-2021).
COLLECTION_OLDEST_FY_END = 2021


def calculate_5year_fiscal_range(now: Optional[datetime] = None) -> Tuple[int, int]:
    """
    Calculate the fiscal year end range for the past 5 years.
    Returns (start_fy_end, current_fy_end).

    Kept for callers that still need a rolling 5-year window.
    """
    current = now or datetime.utcnow()
    current_year = current.year

    if current.month >= 3:
        current_fy_end = current_year + 1
    else:
        current_fy_end = current_year

    start_fy = current_fy_end - 5
    return start_fy, current_fy_end


def calculate_collection_fiscal_range(now: Optional[datetime] = None) -> Tuple[int, int]:
    """
    Collection window: from current FY back through FY 2020-2021 (fy_end=2021).

    If a company has no filing in 2020-2021, callers still keep whatever older-bound
    filings exist until the generator ends (or 2 consecutive out-of-range periods).
    """
    _, current_fy_end = calculate_5year_fiscal_range(now)
    return COLLECTION_OLDEST_FY_END, current_fy_end


def parse_fy_end_from_period(period: str) -> Optional[int]:
    if not period:
        return None
    match = re.search(r"(\d{4})-(\d{4})", str(period))
    if not match:
        return None
    try:
        return int(match.group(2))
    except (ValueError, IndexError):
        return None


def is_within_5year_range(period: str, now: Optional[datetime] = None) -> bool:
    """Legacy alias — now uses the collection window through FY 2020-2021."""
    return is_within_collection_range(period, now)


def is_within_collection_range(period: str, now: Optional[datetime] = None) -> bool:
    """
    True if period's FY end year is in [2021, current_fy_end].
    Example periods: DQ2025-2026, MC2020-2021.
    """
    fy_end = parse_fy_end_from_period(period)
    if fy_end is None:
        return False
    start_fy, end_fy = calculate_collection_fiscal_range(now)
    return start_fy <= fy_end <= end_fy
