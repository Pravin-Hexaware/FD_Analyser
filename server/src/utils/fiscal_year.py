"""Shared Indian fiscal-year helpers for XBRL period filtering."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple


def calculate_5year_fiscal_range(now: Optional[datetime] = None) -> Tuple[int, int]:
    """
    Calculate the fiscal year end range for the past 5 years.
    Returns (start_fy_end, current_fy_end).

    Example: if today is April 2026, current FY is 2026-2027 (end=2027),
    so we collect periods whose FY end is in [2022, 2027].
    """
    current = now or datetime.utcnow()
    current_year = current.year

    # If month >= 3, current fiscal year is current_year-{current_year+1}
    # If month < 3, current fiscal year is {current_year-1}-{current_year}
    if current.month >= 3:
        current_fy_end = current_year + 1
    else:
        current_fy_end = current_year

    start_fy = current_fy_end - 5
    return start_fy, current_fy_end


def is_within_5year_range(period: str, now: Optional[datetime] = None) -> bool:
    """
    Check if a period label (e.g. 'DQ2025-2026') is within the past 5 fiscal years.
    Uses the FY end year from the period string.
    """
    if not period:
        return False

    match = re.search(r"(\d{4})-(\d{4})", str(period))
    if not match:
        return False

    try:
        fy_end = int(match.group(2))
        start_fy, end_fy = calculate_5year_fiscal_range(now)
        return start_fy <= fy_end <= end_fy
    except (ValueError, IndexError):
        return False
