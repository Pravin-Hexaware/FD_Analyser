"""Query interpretation and company data fetching for LLM pipeline."""
import inspect
import re
from datetime import datetime
from typing import Any, Dict, Optional

from repositories.sqlite_repository import SqliteRepository


def determine_frequency(statement_frequency: str, statement_type: str, period: str) -> str:
    sf = (statement_frequency or "").strip().lower()
    st = (statement_type or "").strip().lower()
    p = (period or "").strip().lower()

    if sf in ["annual", "yearly", "year"]:
        return "annual"
    if sf in ["quarterly", "q", "3months", "3-month", "3 months"]:
        return "quarterly"
    if sf in ["both", "annual and quarterly", "quarterly and annual"]:
        return "both"

    quarter_indicators = ["quarter", "quarterly", "q1", "q2", "q3", "q4", "qtr", "quarter results", "quarters"]
    annual_indicators = ["fy", "fiscal year", "year", "years"]

    if any(keyword in p for keyword in quarter_indicators):
        return "quarterly"
    if any(keyword in p for keyword in annual_indicators):
        return "annual"

    annual_types = ["balance_sheet", "cash_flow", "profit_and_loss", "income_statement"]
    if any(t in st for t in annual_types):
        return "annual"
    if "annual" in st or "year" in st:
        return "annual"

    frame = inspect.currentframe().f_back
    time_horizon = None
    if frame and "intent" in frame.f_locals:
        intent = frame.f_locals["intent"]
        time_horizon = (intent.get("time_horizon") or "").lower()
    if time_horizon:
        if re.match(r"^(\d+)\s*years?$", time_horizon) or re.match(r"^(\d+)[- ]*year[s]?$", time_horizon):
            return "annual"

    return "quarterly"


def should_include_peers(query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return False
    return "peer" in q or "peers" in q


def requires_historical_data(query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return False
    historical_keywords = [
        "historical", "5y", "5 year", "trend", "cagr", "growth", "over time",
        "past", "fy", "year", "last 2 years", "last 3 years", "last 5 years",
        "latest 2 years", "latest two years", "latest 3 years", "latest 5 years",
        "last two years", "last three years", "last five years",
    ]
    return any(keyword in q for keyword in historical_keywords)


def interpret_time_window(period: str, time_horizon: str, frequency: str) -> tuple[bool, Optional[int], Optional[str], int]:
    latest_only = False
    last_n_years = None
    period_filter = None
    limit_records = 5

    if time_horizon:
        boundary = time_horizon.strip().lower()
        if boundary in ["latest", "most recent", "recent"]:
            latest_only = True
        else:
            years_match = re.search(r"(\d+)\s*years?", boundary)
            if years_match:
                last_n_years = int(years_match.group(1))

    if period:
        normalized_period = period.strip().lower()
        if normalized_period in ["unspecified", "none", "n/a", "na", ""]:
            period_filter = None
        elif normalized_period.isdigit() and len(normalized_period) == 4:
            year = int(normalized_period)
            period_filter = f"FY{year}-{year+1}"
        else:
            quarters_match = re.search(r"(?:latest|last)\s+(\d+)\s+quarters?", normalized_period)
            if quarters_match:
                limit_records = int(quarters_match.group(1))
                latest_only = False
                if last_n_years is None:
                    last_n_years = 1
            elif "all quarter" in normalized_period:
                latest_only = False
                if last_n_years is None:
                    last_n_years = 1
                if frequency == "quarterly":
                    limit_records = max(limit_records, 4)
                period_filter = period_filter or "latest year"
            elif "latest q" in normalized_period or "most recent" in normalized_period or "last quarter" in normalized_period or "previous quarter" in normalized_period:
                latest_only = True
                period_filter = "latest quarter"
            elif any(keyword in normalized_period for keyword in ["latest year", "latest financial year", "last year", "last financial year", "previous year", "previous financial year"]):
                period_filter = "latest year"
                last_n_years = last_n_years or 1
                if frequency == "quarterly":
                    latest_only = False
                    limit_records = max(limit_records, 4)
                else:
                    latest_only = True
            elif "latest" in normalized_period:
                latest_only = True
                if "quarter" in normalized_period:
                    period_filter = "latest quarter"
                    last_n_years = 1
                elif "year" in normalized_period:
                    period_filter = "latest year"
                    last_n_years = 1
            elif last_n_years is None:
                years_match = re.search(r"(\d+)\s*years?", normalized_period)
                if years_match:
                    last_n_years = int(years_match.group(1))
                else:
                    period_filter = period

    return latest_only, last_n_years, period_filter, limit_records


def fetch_company_data(
    repo: SqliteRepository,
    scrip_code: str,
    frequency: str,
    statement_type: str,
    period: str,
    time_horizon: str,
    query: str = "",
) -> Dict[str, Any]:
    latest_only, last_n_years, period_filter, limit_records = interpret_time_window(period, time_horizon, frequency)
    requires_historical = requires_historical_data(query)

    annual_limit = limit_records
    quarterly_limit = limit_records
    if last_n_years is not None:
        annual_limit = max(limit_records, last_n_years)
        quarterly_limit = max(limit_records, last_n_years * 4)

    if frequency == "both":
        annual_results = repo.get_extraction_records(
            scrip_code, "annual", period=period_filter,
            last_n_years=last_n_years, latest_only=latest_only, limit=annual_limit,
        )
        quarterly_results = repo.get_extraction_records(
            scrip_code, "quarterly", period=period_filter,
            last_n_years=last_n_years, latest_only=latest_only, limit=quarterly_limit,
        )
        return {"annual": annual_results, "quarterly": quarterly_results}

    extraction_type = "annual" if frequency == "annual" else "quarterly"
    effective_limit = annual_limit if extraction_type == "annual" else quarterly_limit
    results = []

    if latest_only and not requires_historical and last_n_years is None:
        latest_record = repo.get_latest_extraction(scrip_code, extraction_type)
        if latest_record:
            results = [latest_record]
    else:
        results = repo.get_extraction_records(
            scrip_code, extraction_type, period=period_filter,
            last_n_years=last_n_years, latest_only=latest_only, limit=effective_limit,
        )

    if not results and not latest_only:
        latest_record = repo.get_latest_extraction(scrip_code, extraction_type)
        if latest_record:
            results = [latest_record]

    if not results:
        return {}

    return results if len(results) > 1 else results[0]
