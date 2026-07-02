from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple
from datetime import datetime
import asyncio
import threading
import queue
import uuid
import json
import os
import re
import csv
from pathlib import Path

from service.analysis_service import (
    parse_query_and_get_companies,
    generate_answer_from_data,
    stream_answer_from_data,
    _get_or_fetch_today_news_summary,
    _normalize_company_folder_name,
    _get_today_news_summary,
)
from service.news_service import NewsService
from repository.sqlite_repository import SqliteRepository

router = APIRouter()

# ============================================================================
# LOW-LATENCY PIPELINE: Helper Functions for Parallel News Handling
# ============================================================================

def _news_cache_path(company_name: str, scrip_code: str) -> Path:
    """Return the path where cached news for a company should be stored."""
    src_dir = Path(__file__).resolve().parents[1]
    markdown_base = src_dir / "markdown"
    safe_name = _normalize_company_folder_name(company_name)
    today = datetime.now().strftime("%Y%m%d")
    return markdown_base / safe_name / today


def _get_latest_cached_news_summary(company_name: str, require_today_only: bool = False) -> Optional[str]:
    """Return cached news from the latest available date folder.

    When require_today_only is True, only the current date folder is considered.
    This is used for news availability checks so old cached news does not count.
    """
    if not company_name:
        return None

    src_dir = Path(__file__).resolve().parents[1]
    markdown_base = src_dir / "markdown"
    safe_name = _normalize_company_folder_name(company_name)
    company_folder = markdown_base / safe_name
    if not company_folder.exists():
        return None

    today = datetime.now().strftime("%Y%m%d")
    date_folders = sorted(
        [p for p in company_folder.iterdir() if p.is_dir() and p.name.isdigit()],
        reverse=True,
    )
    if require_today_only:
        date_folders = [p for p in date_folders if p.name == today]

    for folder in date_folders:
        article_files = [
            path for path in sorted(folder.glob("*.md"))
            if path.name.lower() != "summary.md"
        ]
        if article_files:
            contents = []
            for path in article_files:
                try:
                    contents.append(path.read_text(encoding="utf-8").strip())
                except Exception:
                    continue
            if contents:
                return "\n\n".join(contents)

        summary_file = folder / "summary.md"
        if summary_file.exists() and summary_file.is_file():
            try:
                return summary_file.read_text(encoding="utf-8").strip()
            except Exception:
                continue

    return None


async def _check_news_exists(company_name: str, scrip_code: str, resolved_name: Optional[str] = None) -> bool:
    """Check if cached news articles exist for the company.

    This checks both the original query company name and the validated issuer name,
    since markdown news folders may be created under either.
    """
    try:
        if _get_latest_cached_news_summary(company_name, require_today_only=True) is not None:
            return True
        if resolved_name and resolved_name != company_name:
            if _get_latest_cached_news_summary(resolved_name, require_today_only=True) is not None:
                return True
        return False
    except Exception:
        return False


async def _fetch_news_for_company(
    company_name: str, 
    scrip_code: str, 
    validated_name: Optional[str] = None
) -> Optional[str]:
    """Fetch news for a single company (background task for PROCESS B)."""
    try:
        resolved_name = validated_name or company_name
        return await _get_or_fetch_today_news_summary(resolved_name, scrip_code)
    except Exception as e:
        print(f"[ERROR] Failed to fetch news for {company_name}: {str(e)}")
        return None


async def _generate_news_impact_section(
    original_report: str,
    query: str,
    company_data: Dict[str, Any],
    news_context: str,
    statement_type: str,
    frequency: str
) -> str:
    """
    Generate a new section: "Impact of Recent News on the Company"
    This is called after news collection completes (STEP 4).
    """
    from service.analysis_service import _invoke_llm
    
    system_prompt = """You are a Senior Financial Analyst providing strategic insights.

You will receive an existing report body plus recent news context. Generate one concise, polished section that integrates the news into the analysis without repeating the title or reprinting the entire report.

Requirements:
- Keep the report seamless and professional
- Add a clear section such as '## IX. News-Driven Assessment and Outlook' or similar
- Explain how recent news changes the interpretation of financial performance, risk, and outlook
- Include implications for revenue, margin, cash flow, balance sheet, and strategic positioning
- Must include a dedicated final conclusion or overall assessment section at the end of the response
- The conclusion must clearly summarize the overall report and provide a final recommendation or takeaway

Do not repeat the full title, do not add 'phase 1'/'phase 2' markers, and do not include any separator text like 'END OF REPORT'."""

    user_prompt = f"""Original Query: {query}

Recent News Articles and Market Developments:
{news_context}

Company Financial Data:
{json.dumps(company_data, indent=2)}

Existing Report Body:
---
{original_report}
---

Generate one seamless section that integrates the recent news into the report and improves the final analysis. The output should be only the new section content, ready to be appended to the existing report."""

    try:
        response = _invoke_llm(system_prompt, user_prompt, max_tokens=2000)
        from service.analysis_service import _normalize_llm_response
        normalized = _normalize_llm_response(response)
        return normalized.get("content", "")
    except Exception as e:
        print(f"[ERROR] Failed to generate news impact section: {str(e)}")
        return ""

def _missing_tracker_csv_path() -> Path:
    src_dir = Path(__file__).resolve().parents[1]   # points to src/
    data_dir = src_dir / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "missing_companies.csv"



def _schedule_missing_company_processing() -> None:
    """Schedule background processing of missing companies."""
    try:
        from api.service.missing_company_service import MissingCompanyService

        def _run():
            try:
                asyncio.run(MissingCompanyService.process_missing_companies_batch(None))
            except Exception as exc:
                print(f"[WARN] Missing company background task failed: {exc}")

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
    except Exception as exc:
        print(f"[WARN] Failed to schedule missing company processing: {exc}")


def _append_missing_company(
    company_name: str,
    symbol: Optional[str],
    scrip_code: Optional[str],
    frequency: str,
    period: str,
    time_horizon: str,
    is_peer: bool,
    query: str,
    background_tasks: Optional[BackgroundTasks] = None,
    schedule_processing: bool = False,
) -> None:
    file_path = _missing_tracker_csv_path()
    header = [
        "timestamp",
        "company_name",
        "symbol",
        "scrip_code",
        "frequency",
        "period",
        "time_horizon",
        "is_peer",
        "query",
    ]
    row = {
        "timestamp": datetime.now().isoformat(),
        "company_name": company_name,
        "symbol": symbol or "",
        "scrip_code": scrip_code or "",
        "frequency": frequency,
        "period": period,
        "time_horizon": time_horizon,
        "is_peer": "true" if is_peer else "false",
        "query": query,
    }
    write_header = not file_path.exists()
    print(f"Tracking missing company to CSV: {file_path} -> {company_name} ({scrip_code})")
    with open(file_path, mode="a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    if background_tasks is not None and schedule_processing:
        background_tasks.add_task(_schedule_missing_company_processing)


def _format_sse_event(event_name: str, data: str) -> bytes:
    """Format a single Server-Sent Event message."""
    sanitized = data.replace("\r", "").split("\n")
    formatted = "".join(f"data: {line}\n" for line in sanitized)
    return f"event: {event_name}\n{formatted}\n".encode("utf-8")


_validation_companies_cache: Optional[List[Dict[str, str]]] = None


def _validation_csv_path() -> Path:
    src_dir = Path(__file__).resolve().parents[1]
    return src_dir / "Data" / "Validation.csv"


def _normalize_text(text: Optional[str]) -> str:
    if text is None:
        return ""
    normalized = text.strip().lower()
    normalized = re.sub(r"\.|,|\(|\)|&", "", normalized)
    normalized = re.sub(r"\b(ltd|ltd\b|limited)\b", "limited", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _load_validation_companies() -> List[Dict[str, str]]:
    global _validation_companies_cache
    if _validation_companies_cache is not None:
        return _validation_companies_cache

    validation_path = _validation_csv_path()
    rows: List[Dict[str, str]] = []
    if not validation_path.exists():
        print(f"Validation CSV not found: {validation_path}")
        _validation_companies_cache = rows
        return rows

    with open(validation_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({
                "security_code": row.get("Security Code", "").strip(),
                "issuer_name": row.get("Issuer Name", "").strip(),
                "security_id": row.get("Security Id", "").strip(),
                "security_name": row.get("Security Name", "").strip(),
            })

    _validation_companies_cache = rows
    return rows


def _resolve_company_validation(company_name: str, symbol: Optional[str] = None) -> Dict[str, Any]:
    normalized_query_name = _normalize_text(company_name)
    validation_rows = _load_validation_companies()
    if not validation_rows:
        return {
            "valid": False,
            "company_name": company_name,
            "reason": "Validation data unavailable.",
        }

    normalized_symbol = _normalize_text(symbol) if symbol else ""
    matched_row = None
    symbol_matched = False
    name_matches: List[Dict[str, str]] = []

    if normalized_symbol:
        symbol_candidates = [
            row for row in validation_rows
            if normalized_symbol == _normalize_text(row["security_id"]) 
            or normalized_symbol == _normalize_text(row["security_code"])
        ]
        if symbol_candidates:
            matched_row = symbol_candidates[0]
            symbol_matched = True

    if matched_row is None:
        if not normalized_query_name:
            return {
                "valid": False,
                "company_name": company_name,
                "reason": "Company name not provided and symbol did not match Validation.csv.",
            }

        name_matches = [
            row for row in validation_rows
            if normalized_query_name in _normalize_text(row["issuer_name"]) 
            or _normalize_text(row["issuer_name"]).find(normalized_query_name) >= 0
            or normalized_query_name in _normalize_text(row["security_name"])
        ]

        if not name_matches:
            return {
                "valid": False,
                "company_name": company_name,
                "reason": "Company name not found in Validation.csv.",
            }

        matched_row = sorted(
            name_matches,
            key=lambda row: len(_normalize_text(row["issuer_name"])),
            reverse=True,
        )[0]
        symbol_matched = False if symbol else True

    return {
        "valid": True,
        "company_name": company_name,
        "resolved_issuer_name": matched_row["issuer_name"],
        "resolved_scrip_code": matched_row["security_code"],
        "resolved_security_id": matched_row["security_id"],
        "parsed_symbol": symbol,
        "symbol_matched": symbol_matched,
        "name_matches": [row["issuer_name"] for row in name_matches],
    }


def write_llm_log(user_query: str, llm_prompt: str, llm_response: str, db_data: Dict[str, Any], data_passed_to_llm: Dict[str, Any], final_prompt: str, final_response: str, peer_extraction_log: str = "", token_usage: Optional[Dict[str, int]] = None):
    """Write detailed LLM interaction logs to timestamped file."""
    try:
        # Create logs directory if it doesn't exist
        logs_dir = Path(__file__).parent.parent / "logs"
        logs_dir.mkdir(exist_ok=True)

        # Generate timestamp for filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_filename = f"Log-{timestamp}.log"
        log_filepath = logs_dir / log_filename

        # Format the log content
        log_content = f"""=== LLM TARGET COMPANIES LOG ===
Timestamp: {datetime.now().isoformat()}
Log File: {log_filename}

1. USER QUERY:
{user_query}

2. INITIAL LLM PROMPT (Query Parsing):
{llm_prompt}

3. INITIAL LLM RESPONSE (Parsed Query):
{llm_response}

4. PEER EXTRACTION LOG:
{peer_extraction_log}

5. DATA FETCHED FROM DATABASE:
{json.dumps(db_data, indent=2)}

6. DATA PASSED TO LLM:
{json.dumps(data_passed_to_llm, indent=2)}

7. FINAL PROMPT GIVEN TO LLM:
{final_prompt}

8. FINAL RESPONSE FROM LLM:
{final_response}

9. TOKEN USAGE:
{json.dumps(token_usage or {}, indent=2)}

=== END LOG ===
"""

        # Write to file
        with open(log_filepath, 'w', encoding='utf-8') as f:
            f.write(log_content)

        print(f"LLM log written to: {log_filepath}")

    except Exception as e:
        print(f"Error writing LLM log: {str(e)}")


def get_actual_initial_prompt() -> str:
    """Get the actual initial prompt used for query parsing (NLP-based, no LLM)."""
    # NLP-based extraction now - this is just for logging/documentation
    return """NLP-Based Query Parsing (No LLM):
- Uses pattern matching and fuzzy matching against BSE company list
- Extracts statement frequency, type, period, time horizon, and target companies
- Deterministic rule-based extraction for company names from query
- Automatically detects peer request indicators
- Returns structured JSON compatible with existing pipeline"""


def get_actual_final_prompt(query: str, data: Dict[str, Any], statement_type: str, frequency: str) -> str:
    """Get the actual final prompt used for answer generation."""
    system_prompt = f"""You are a Financial Analyst. Answer the user's query using the provided parsed JSON financial data.
The data is for {frequency} financial statements, including {statement_type.replace('_', ' ')} metrics where available.

Provide a clear, concise manager-style analysis report. Use only the data present in the JSON and mention if any requested period or metric is missing."""
    
    user_prompt = f"Query: {query}\n\nData: {json.dumps(data, indent=2)}"
    
    return f"{system_prompt}\n\n{user_prompt}"

class LLMQueryRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None


class ChatHistoryResponse(BaseModel):
    chat_id: str
    title: str  # Display title for chat history
    created_at: str
    last_message: Optional[str] = None


class ChatMessageResponse(BaseModel):
    id: int
    sequence_number: int
    role: str
    content: str
    created_at: str


class ConversationResponse(BaseModel):
    chat_id: str
    title: str
    created_at: str
    messages: List[ChatMessageResponse]


class ProgressMessage(BaseModel):
    """Progress update message during query processing."""
    stage: str  # e.g., "Extracting user intent", "Fetching relevant data", etc.
    timestamp: str


class LLMTargetCompaniesResponse(BaseModel):
    """Response with progress messages and final answer."""
    chat_id: str
    answer: str
    tokens_used: Dict[str, int]
    progress_messages: List[ProgressMessage]
    invalid_companies: Optional[List[str]] = None
    background_note: Optional[str] = None


def _determine_frequency(statement_frequency: str, statement_type: str, period: str) -> str:
    """Determine the frequency: annual or quarterly."""
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

    # --- PATCH: treat time_horizon like '3years', '5years', etc. as annual ---
    import re
    # Try to extract time_horizon from the calling context (hack: look for '3years', '5years', etc. in globals)
    import inspect
    frame = inspect.currentframe().f_back
    time_horizon = None
    if frame and 'intent' in frame.f_locals:
        intent = frame.f_locals['intent']
        time_horizon = (intent.get('time_horizon') or '').lower()
    if time_horizon:
        if re.match(r"^(\d+)\s*years?$", time_horizon) or re.match(r"^(\d+)[- ]*year[s]?$", time_horizon):
            return "annual"

    return "quarterly"



def _should_include_peers(query: str) -> bool:
    """Return True only when query explicitly requests peers."""
    q = (query or "").strip().lower()
    if not q:
        return False
    if "peer" in q or "peers" in q:
        return True
    return False


def _requires_historical_data(query: str) -> bool:
    """Check if the query requires historical/trend data."""
    q = (query or "").strip().lower()
    if not q:
        return False
    historical_keywords = [
        "historical", "5y", "5 year", "trend", "cagr", "growth", "over time",
        "past", "fy", "year", "last 2 years", "last 3 years", "last 5 years",
        "latest 2 years", "latest two years", "latest 3 years", "latest 5 years",
        "last two years", "last three years", "last five years"
    ]
    return any(keyword in q for keyword in historical_keywords)


def _interpret_time_window(period: str, time_horizon: str, frequency: str) -> tuple[bool, Optional[int], Optional[str], int]:
    """Parse period and time_horizon and return (latest_only, last_n_years, period_filter, limit_records)."""
    latest_only = False
    last_n_years = None
    period_filter = None
    limit_records = 5  # default limit

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
            # Specific year like "2024"
            year = int(normalized_period)
            period_filter = f"FY{year}-{year+1}"
        else:
            # Check for "latest X quarters" or "last X quarters"
            quarters_match = re.search(r"(?:latest|last)\s+(\d+)\s+quarters?", normalized_period)
            if quarters_match:
                limit_records = int(quarters_match.group(1))
                latest_only = False  # Don't limit to single record
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


def _fetch_company_data(
    repo: SqliteRepository,
    scrip_code: str,
    frequency: str,
    statement_type: str,
    period: str,
    time_horizon: str,
    query: str = "",
) -> Dict[str, Any]:
    """Fetch data for a company and return the best matching extraction records."""
    latest_only, last_n_years, period_filter, limit_records = _interpret_time_window(period, time_horizon, frequency)
    requires_historical = _requires_historical_data(query)

    annual_limit = limit_records
    quarterly_limit = limit_records
    if last_n_years is not None:
        annual_limit = max(limit_records, last_n_years)
        quarterly_limit = max(limit_records, last_n_years * 4)

    if frequency == "both":
        annual_results = repo.get_extraction_records(
            scrip_code,
            "annual",
            period=period_filter,
            last_n_years=last_n_years,
            latest_only=latest_only,
            limit=annual_limit,
        )
        quarterly_results = repo.get_extraction_records(
            scrip_code,
            "quarterly",
            period=period_filter,
            last_n_years=last_n_years,
            latest_only=latest_only,
            limit=quarterly_limit,
        )
        results = {
            "annual": annual_results,
            "quarterly": quarterly_results,
        }
    else:
        extraction_type = "annual" if frequency == "annual" else "quarterly"
        effective_limit = annual_limit if extraction_type == "annual" else quarterly_limit
        results = []

        if latest_only and not requires_historical and last_n_years is None:
            latest_record = repo.get_latest_extraction(scrip_code, extraction_type)
            if latest_record:
                results = [latest_record]
        else:
            results = repo.get_extraction_records(
                scrip_code,
                extraction_type,
                period=period_filter,
                last_n_years=last_n_years,
                latest_only=latest_only,
                limit=effective_limit,
            )

        if not results and not latest_only:
            latest_record = repo.get_latest_extraction(scrip_code, extraction_type)
            if latest_record:
                results = [latest_record]

    if not results:
        return {}

    return results if len(results) > 1 else results[0]


@router.post("/llm/target_companies", response_model=LLMTargetCompaniesResponse)
async def llm_target_companies(request: LLMQueryRequest, background_tasks: BackgroundTasks):
    """Parse user query, fetch data, and generate answer with Azure LLM."""
    try:
        repo = SqliteRepository()
        
        # Initialize progress messages list
        progress_messages: List[Dict[str, str]] = []

        # Create or validate conversation
        if request.conversation_id is None:
            conversation_id = repo.create_conversation()
        else:
            conversation_id = request.conversation_id
            if not repo.conversation_exists(conversation_id):
                repo.close()
                raise HTTPException(status_code=404, detail="Conversation not found")

        chat_id = str(conversation_id)

        # Save the incoming user message inside the conversation
        repo.save_message(conversation_id, "user", request.query)

        # Initialize log variables
        user_query = request.query
        initial_llm_prompt = get_actual_initial_prompt()
        initial_llm_response = ""
        db_fetched_data = {}
        data_passed_to_llm = {}
        final_llm_prompt = ""
        peer_extraction_log = ""

        # Step 1: Parse user query
        print("Step 1: Parsing user query with NLP (no LLM)")
        progress_messages.append({
            "stage": "Extracting user intent",
            "timestamp": datetime.now().isoformat()
        })
        
        parsed, initial_llm_prompt, peer_extraction_log = parse_query_and_get_companies(request.query)
        print("1st NLP extraction returned:", parsed)

        # Store initial LLM interaction for logging
        initial_llm_response = json.dumps(parsed)

        # Log Step 1 - Query parsing
        repo.save_detailed_log(
            chat_id=chat_id,
            step_name="Query Parsing",
            input_data=json.dumps({"user_query": request.query}),
            output_data=json.dumps(parsed)
        )

        if parsed.get("error"):
            raise HTTPException(status_code=500, detail=parsed.get("error"))

        # Extract intent
        intent = parsed.get("intent", {})
        statement_type = intent.get("statement_type", "unspecified")
        statement_frequency = intent.get("statement_frequency", "unspecified")
        period = intent.get("period", "unspecified")
        time_horizon = intent.get("time_horizon", "unspecified")
        get_peer = intent.get("get_peer", False)
        frequency = _determine_frequency(statement_frequency, statement_type, period)
        print(f"Determined frequency: {frequency}, statement_frequency: {statement_frequency}, statement_type: {statement_type}, period: {period}, time_horizon: {time_horizon}, get_peer: {get_peer}")

        target_companies = parsed.get("target_companies", {})
        validation_results: Dict[str, Dict[str, Any]] = {}
        invalid_companies = []

        for key, company in target_companies.items():
            company_name = company.get("company", key)
            validation_results[company_name] = _resolve_company_validation(company_name, company.get("symbol"))
            if not validation_results[company_name]["valid"]:
                invalid_companies.append(company_name)

        # Add progress message for company identification
        progress_messages.append({
            "stage": "Identifying the companies",
            "timestamp": datetime.now().isoformat()
        })

        if invalid_companies:
            repo.save_detailed_log(
                chat_id=chat_id,
                step_name="Validation",
                input_data=json.dumps({
                    "parsed_companies": target_companies,
                    "invalid_companies": invalid_companies,
                }),
                output_data=json.dumps({
                    "answer": "Invalid company name(s). Please try a different company.",
                    "invalid_companies": invalid_companies,
                })
            )
            answer = f"Invalid company name(s): {', '.join(invalid_companies)}. Please try a different company."
            repo.save_message(conversation_id, "llm", answer)
            repo.close()
            return {
                "chat_id": chat_id,
                "answer": answer,
                "invalid_companies": invalid_companies,
                "tokens_used": {},
                "progress_messages": progress_messages,
            }

        # Step 2: Fetch data for target companies and peers
        print("Step 2: Fetching data for target companies" + (" + peers" if get_peer else ""))
        progress_messages.append({
            "stage": "Fetching relevant data",
            "timestamp": datetime.now().isoformat()
        })
        
        all_data = {}
        tracked_missing = set()

        db_fetch_log = {
            "frequency": frequency,
            "statement_type": statement_type,
            "companies_requested": list(target_companies.keys()),
            "get_peer": get_peer,
            "fetched_data": {}
        }

        missing_processing_scheduled = False
        for key, company in target_companies.items():
            company_name = company.get("company", key)
            validation_info = validation_results[company_name]
            resolved_scrip_code = validation_info["resolved_scrip_code"]
            company["scrip_code"] = resolved_scrip_code

            if validation_info.get("parsed_symbol") and validation_info.get("symbol_matched") is False:
                print(f"Symbol mismatch for {company_name}: parsed symbol '{validation_info['parsed_symbol']}' did not match Validation.csv; using scrip code {resolved_scrip_code}")

            data = _fetch_company_data(repo, resolved_scrip_code, frequency, statement_type, period, time_horizon, request.query)
            all_data[company_name] = data
            db_fetch_log["fetched_data"][company_name] = {
                "parsed_symbol": validation_info.get("parsed_symbol"),
                "symbol_matched": validation_info.get("symbol_matched"),
                "resolved_issuer_name": validation_info.get("resolved_issuer_name"),
                "resolved_scrip_code": resolved_scrip_code,
                "frequency": frequency,
                "period": period,
                "time_horizon": time_horizon,
                "data": data
            }
            print(f"Fetched extraction records for {company_name} ({resolved_scrip_code}): {data}")
            if not data:
                missing_key = (company_name, resolved_scrip_code, frequency, period, time_horizon, False)
                if missing_key not in tracked_missing:
                    _append_missing_company(
                        company_name=company_name,
                        symbol=company.get("symbol"),
                        scrip_code=resolved_scrip_code,
                        frequency=frequency,
                        period=period,
                        time_horizon=time_horizon,
                        is_peer=False,
                        query=request.query,
                        background_tasks=background_tasks,
                        schedule_processing=not missing_processing_scheduled,
                    )
                    tracked_missing.add(missing_key)
                    missing_processing_scheduled = True

            if get_peer:
                peers = company.get("peers", {})
                for p_key, peer in peers.items():
                    p_scrip = peer.get("scrip_code")
                    peer_name = peer.get("company", p_key)
                    if p_scrip:
                        p_data = _fetch_company_data(repo, p_scrip, frequency, statement_type, period, time_horizon, request.query)
                        all_data[peer_name] = p_data
                        db_fetch_log["fetched_data"][peer_name] = {
                            "scrip_code": p_scrip,
                            "frequency": frequency,
                            "period": period,
                            "time_horizon": time_horizon,
                            "is_peer": True,
                            "data": p_data
                        }
                        print(f"Fetched extraction records for peer {peer_name} ({p_scrip}): {p_data}")
                        if not p_data:
                            missing_key = (peer_name, p_scrip, frequency, period, time_horizon, True)
                            if missing_key not in tracked_missing:
                                _append_missing_company(
                                    company_name=peer_name,
                                    symbol=peer.get("symbol"),
                                    scrip_code=p_scrip,
                                    frequency=frequency,
                                    period=period,
                                    time_horizon=time_horizon,
                                    is_peer=True,
                                    query=request.query,
                                    background_tasks=background_tasks,
                                    schedule_processing=not missing_processing_scheduled,
                                )
                                tracked_missing.add(missing_key)
                                missing_processing_scheduled = True

        # Store DB fetched data for logging
        db_fetched_data = db_fetch_log

        # Log Step 2 - Database fetching
        repo.save_detailed_log(
            chat_id=chat_id,
            step_name="Database Fetch",
            input_data=json.dumps({
                "parsed_query": parsed,
                "frequency": frequency,
                "statement_type": statement_type,
                "target_companies": list(target_companies.keys())
            }),
            output_data=json.dumps(db_fetch_log)
        )

        # Check if any data was fetched
        has_data = bool(all_data) and any(all_data.values())

        if not has_data:
            # No data available, return message without calling LLM
            answer = "Company data for the selected period is temporarily unavailable, possibly due to processing delays. Please try again after 10 minutes."
            tokens_used = {}
            final_llm_response = answer
            final_llm_prompt = ""

            background_note = None
            if missing_processing_scheduled:
                background_note = "Background XBRL fetch has been scheduled. Data will be extracted once available."

            # Save assistant message
            repo.save_message(conversation_id, "llm", answer)

            # Log that no data was found
            repo.save_detailed_log(
                chat_id=chat_id,
                step_name="No Data Available",
                input_data=json.dumps({
                    "reason": "No extraction records found for requested companies/period"
                }),
                output_data=json.dumps({
                    "message": answer,
                    "background_note": background_note
                })
            )

            repo.close()

            # Write log
            write_llm_log(
                user_query=user_query,
                llm_prompt=initial_llm_prompt,
                llm_response=initial_llm_response,
                db_data=db_fetched_data,
                data_passed_to_llm=data_passed_to_llm,
                final_prompt=final_llm_prompt,
                final_response=final_llm_response,
                peer_extraction_log=peer_extraction_log if 'peer_extraction_log' in locals() else "",
                token_usage=tokens_used
            )

            response = {
                "chat_id": chat_id,
                "answer": answer,
                "tokens_used": tokens_used,
                "progress_messages": progress_messages,
            }
            if background_note:
                response["background_note"] = background_note

            return response

        # Step 3: Generate answer using LLM (with data fetched and company names resolved via NLP)
        print("Step 3: Fetching news context for companies")
        progress_messages.append({
            "stage": "Collecting news feeds",
            "timestamp": datetime.now().isoformat()
        })
        
        # Fetch news for ALL validated companies (not just those with data in all_data)
        news_context_parts = []
        news_fetch_log = {}
        
        # Get list of all validated companies from validation_results
        all_companies_to_fetch_news = list(validation_results.keys())
        
        # Also add peer companies if they were requested
        if get_peer:
            for company_name, company_info in target_companies.items():
                actual_company_name = company_info.get("company", company_name)
                if actual_company_name in all_data:
                    peers = company_info.get("peers", {})
                    for p_key, peer in peers.items():
                        peer_name = peer.get("company", p_key)
                        if peer_name not in all_companies_to_fetch_news:
                            all_companies_to_fetch_news.append(peer_name)
        
        print(f"Fetching news for {len(all_companies_to_fetch_news)} companies: {all_companies_to_fetch_news}")
        
        for company_name in all_companies_to_fetch_news:
            try:
                validation_info = validation_results.get(company_name)
                if validation_info is None:
                    # Resolve peer-only companies that were not part of the original target set.
                    resolved_symbol = None
                    normalized_key = company_name.strip()
                    if re.fullmatch(r"[A-Za-z]{2,10}", normalized_key):
                        resolved_symbol = normalized_key
                    validation_info = _resolve_company_validation(company_name, resolved_symbol)
                    validation_results[company_name] = validation_info

                scrip_code = validation_info.get("resolved_scrip_code") if validation_info.get("valid") else None
                news_company_name = validation_info.get("resolved_issuer_name") or company_name
                
                print(f"Processing company: {company_name}, resolved_name: {news_company_name}, scrip_code: {scrip_code}")
                
                if scrip_code:
                    # Fetch from cached raw markdown articles, or scrape on-demand if missing.
                    markdown_news = await _get_or_fetch_today_news_summary(news_company_name, scrip_code)
                    
                    if markdown_news:
                        # Include today's raw markdown news content
                        print(f"Found cached news content for {company_name}")
                        company_news_str = f"\n### {company_name} - Today's News Content\n"
                        company_news_str += markdown_news
                        company_news_str += "\n"
                        news_context_parts.append(company_news_str)
                        news_fetch_log[company_name] = {
                            "scrip_code": scrip_code,
                            "source": "markdown_daily_articles",
                            "date": datetime.now().strftime("%Y%m%d"),
                            "status": "found"
                        }
                    else:
                        # No cached markdown articles for today - do not fetch from other sources
                        print(f"No cached markdown articles found for {company_name} on {datetime.now().strftime('%Y%m%d')}")
                        news_fetch_log[company_name] = {
                            "scrip_code": scrip_code,
                            "source": "markdown_daily_articles",
                            "date": datetime.now().strftime("%Y%m%d"),
                            "status": "not_found"
                        }

                else:
                    print(f"No scrip_code for {company_name}, skipping news fetch")
            
            except Exception as e:
                print(f"[WARN] Failed to fetch news for {company_name}: {str(e)}")
                import traceback
                traceback.print_exc()
                news_fetch_log[company_name] = {
                    "error": str(e)
                }
        
        # Combine all news context
        news_context = "\n".join(news_context_parts) if news_context_parts else None
        
        print(f"News context compiled: {news_context is not None}")
        if news_context:
            print(f"News context length: {len(news_context)}")
        
        # Log Step 2.5 - News fetching
        repo.save_detailed_log(
            chat_id=chat_id,
            step_name="News Fetch",
            input_data=json.dumps({
                "companies": all_companies_to_fetch_news,
                "include_peers": get_peer
            }),
            output_data=json.dumps(news_fetch_log)
        )

        print("Step 4: Generating answer with LLM")
        progress_messages.append({
            "stage": "Generating response",
            "timestamp": datetime.now().isoformat()
        })

        # Prepare the EXACT data being sent to LLM
        system_prompt = f"""You are a Financial Analyst. Answer the user's query using the provided financial data.
The data is for {frequency} financial statements, including {statement_type.replace('_', ' ')} metrics where available.

Provide a clear, concise answer to the query. If data is missing for some companies, note that."""

        user_prompt = f"Query: {request.query}\n\nData: {json.dumps(all_data, indent=2)}"

        final_llm_prompt = get_actual_final_prompt(request.query, all_data, statement_type, frequency)

        # Store data passed to LLM for logging
        data_passed_to_llm = all_data

        print(f"Calling generate_answer_from_data with news_context: {news_context is not None}")
        answer, tokens_used = generate_answer_from_data(request.query, all_data, statement_type, frequency, news_context=news_context)
        print("2nd LLM answer:", answer)
        print("LLM token usage:", tokens_used)

        # Store final LLM response for logging
        final_llm_response = answer

        # Save assistant message inside the same conversation
        repo.save_message(conversation_id, "llm", answer)

        # Log Step 3 - EXACT LLM input and output
        repo.save_detailed_log(
            chat_id=chat_id,
            step_name="Answer Generation (LLM)",
            input_data=json.dumps({
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "query": request.query,
                "data_sent": all_data,
                "statement_type": statement_type,
                "frequency": frequency
            }, default=str),
            output_data=json.dumps({
                "llm_response": answer,
                "token_usage": tokens_used,
                "timestamp": datetime.now().isoformat()
            })
        )

        repo.close()

        # Write comprehensive log to file
        write_llm_log(
            user_query=user_query,
            llm_prompt=initial_llm_prompt,
            llm_response=initial_llm_response,
            db_data=db_fetched_data,
            data_passed_to_llm=data_passed_to_llm,
            final_prompt=final_llm_prompt,
            final_response=final_llm_response,
            peer_extraction_log=peer_extraction_log if 'peer_extraction_log' in locals() else "",
            token_usage=tokens_used
        )

        return {
            "chat_id": chat_id,
            "answer": answer,
            "tokens_used": tokens_used,
            "progress_messages": progress_messages,
        }

    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/target_companies/stream")
async def stream_llm_target_companies(query: str, background_tasks: BackgroundTasks, conversation_id: Optional[int] = None):
    """
    LOW-LATENCY STREAMING ENDPOINT: Implements progressive report enhancement.
    
    STEP 1: Parse query and validate companies (sync)
    STEP 2: Fetch financial data from database (sync)
    STEP 3: Check for cached news + parallel execution
        - CASE 1: News exists → Generate full report with news → Stream it
        - CASE 2: News missing → 
            - PROCESS A: Generate fast report (no news) → Stream immediately
            - PROCESS B: Fetch news in background (async)
    STEP 4: Once PROCESS B completes → Generate news impact section
    STEP 5: Stream the news impact section and append to UI
    """
    try:
        repo = SqliteRepository()

        # Create or validate conversation
        if conversation_id is None:
            conversation_id = repo.create_conversation()
        else:
            if not repo.conversation_exists(conversation_id):
                repo.close()
                raise HTTPException(status_code=404, detail="Conversation not found")

        chat_id = str(conversation_id)
        repo.save_message(conversation_id, "user", query)

        # Initialize log variables
        user_query = query
        initial_llm_prompt = get_actual_initial_prompt()
        initial_llm_response = ""
        db_fetched_data = {}
        peer_extraction_log = ""

        progress_messages: List[Dict[str, str]] = []
        all_data: Dict[str, Any] = {}
        tracked_missing = set()

        # ====== STEP 1: Parse user query ======
        print("[STEP 1] Parsing user query with NLP")
        progress_messages.append({
            "stage": "Extracting user intent",
            "timestamp": datetime.now().isoformat()
        })

        parsed, initial_llm_prompt, peer_extraction_log = parse_query_and_get_companies(query)
        initial_llm_response = json.dumps(parsed)

        if parsed.get("error"):
            repo.close()
            raise HTTPException(status_code=500, detail=parsed.get("error"))

        intent = parsed.get("intent", {})
        statement_type = intent.get("statement_type", "unspecified")
        statement_frequency = intent.get("statement_frequency", "unspecified")
        period = intent.get("period", "unspecified")
        time_horizon = intent.get("time_horizon", "unspecified")
        get_peer = intent.get("get_peer", False)
        frequency = _determine_frequency(statement_frequency, statement_type, period)

        target_companies = parsed.get("target_companies", {})
        validation_results: Dict[str, Dict[str, Any]] = {}
        invalid_companies = []

        for key, company in target_companies.items():
            company_name = company.get("company", key)
            validation_results[company_name] = _resolve_company_validation(company_name, company.get("symbol"))
            if not validation_results[company_name]["valid"]:
                invalid_companies.append(company_name)

        if invalid_companies:
            repo.save_message(conversation_id, "llm", f"Invalid company name(s): {', '.join(invalid_companies)}. Please try a different company.")
            repo.close()
            return StreamingResponse(
                iter([_format_sse_event("message", f"Invalid company name(s): {', '.join(invalid_companies)}. Please try a different company."), _format_sse_event("done", "true")]),
                media_type="text/event-stream"
            )

        # ====== STEP 2: Fetch financial data ======
        print("[STEP 2] Fetching financial data for target companies" + (" + peers" if get_peer else ""))
        progress_messages.append({
            "stage": "Fetching relevant data",
            "timestamp": datetime.now().isoformat()
        })

        missing_processing_scheduled = False
        for key, company in target_companies.items():
            company_name = company.get("company", key)
            validation_info = validation_results[company_name]
            resolved_scrip_code = validation_info["resolved_scrip_code"]
            company["scrip_code"] = resolved_scrip_code

            data = _fetch_company_data(repo, resolved_scrip_code, frequency, statement_type, period, time_horizon, query)
            all_data[company_name] = data
            if not data:
                missing_key = (company_name, resolved_scrip_code, frequency, period, time_horizon, False)
                if missing_key not in tracked_missing:
                    _append_missing_company(
                        company_name=company_name,
                        symbol=company.get("symbol"),
                        scrip_code=resolved_scrip_code,
                        frequency=frequency,
                        period=period,
                        time_horizon=time_horizon,
                        is_peer=False,
                        query=query,
                        background_tasks=background_tasks,
                        schedule_processing=not missing_processing_scheduled,
                    )
                    tracked_missing.add(missing_key)
                    missing_processing_scheduled = True

            if get_peer:
                peers = company.get("peers", {})
                for p_key, peer in peers.items():
                    p_scrip = peer.get("scrip_code")
                    peer_name = peer.get("company", p_key)
                    if p_scrip:
                        p_data = _fetch_company_data(repo, p_scrip, frequency, statement_type, period, time_horizon, query)
                        all_data[peer_name] = p_data
                        if not p_data:
                            missing_key = (peer_name, p_scrip, frequency, period, time_horizon, True)
                            if missing_key not in tracked_missing:
                                _append_missing_company(
                                    company_name=peer_name,
                                    symbol=peer.get("symbol"),
                                    scrip_code=p_scrip,
                                    frequency=frequency,
                                    period=period,
                                    time_horizon=time_horizon,
                                    is_peer=True,
                                    query=query,
                                    background_tasks=background_tasks,
                                    schedule_processing=not missing_processing_scheduled,
                                )
                                tracked_missing.add(missing_key)
                                missing_processing_scheduled = True

        has_data = bool(all_data) and any(all_data.values())

        if not has_data:
            background_note = "Background XBRL fetch has been scheduled and will continue quietly. Please try again after 10 minutes."
            answer = (
                "Company data for the selected period is temporarily unavailable, possibly due to processing delays. Please try again after 10 minutes."
            )
            repo.save_message(conversation_id, "llm", answer)
            repo.close()
            return StreamingResponse(
                iter([_format_sse_event("message", answer), _format_sse_event("done", "true")]),
                media_type="text/event-stream",
                background=background_tasks,
            )

        # ====== STEP 3: News check + Parallel Execution ======
        print("[STEP 3] Checking for cached news and preparing parallel execution")
        progress_messages.append({
            "stage": "Checking for news",
            "timestamp": datetime.now().isoformat()
        })

        # Build list of companies to check for news
        news_check_companies: List[Tuple[str, str, str]] = []  # (company_name, scrip_code, validated_name)
        for company_name in validation_results.keys():
            validation_info = validation_results[company_name]
            if validation_info.get("valid"):
                scrip_code = validation_info["resolved_scrip_code"]
                resolved_name = validation_info["resolved_issuer_name"]
                news_check_companies.append((company_name, scrip_code, resolved_name))

        # Check which companies have cached news
        news_exists_map: Dict[str, bool] = {}
        for company_name, scrip_code, resolved_name in news_check_companies:
            news_exists_map[company_name] = await _check_news_exists(company_name, scrip_code, resolved_name)

        has_any_news = any(news_exists_map.values())
        needs_news_fetch = any(not v for v in news_exists_map.values())

        print(f"News status: {has_any_news=}, {needs_news_fetch=}")
        print(f"News exists map: {news_exists_map}")

        # Prepare async task variables
        news_collection_task: Optional[asyncio.Task] = None
        collected_news: Dict[str, Optional[str]] = {}

        # ====== CASE 1: All news exists ======
        if has_any_news and not needs_news_fetch:
            print("[CASE 1] All news exists - generating full report with news")
            progress_messages.append({
                "stage": "Generating response with news context",
                "timestamp": datetime.now().isoformat()
            })

            # Fetch all news summaries from the latest available cached folder.
            news_context_parts = []
            for company_name, scrip_code, resolved_name in news_check_companies:
                if news_exists_map[company_name]:
                    markdown_news = _get_latest_cached_news_summary(company_name, require_today_only=True)
                    if not markdown_news and resolved_name and resolved_name != company_name:
                        markdown_news = _get_latest_cached_news_summary(resolved_name, require_today_only=True)
                    if markdown_news:
                        news_context_parts.append(f"\n### {company_name} - Recent News\n{markdown_news}")

            news_context = "\n".join(news_context_parts) if news_context_parts else None

            # Generate and stream full report with news
            def event_generator_case1() -> Iterator[bytes]:
                metadata = {"chat_id": chat_id, "conversation_id": conversation_id}
                yield _format_sse_event("metadata", json.dumps(metadata))

                answer_parts: List[str] = []
                for chunk in stream_answer_from_data(query, all_data, statement_type, frequency, news_context=news_context):
                    answer_parts.append(chunk)
                    yield _format_sse_event("message", chunk)

                yield _format_sse_event("done", "true")

                # Save answer after streaming
                try:
                    answer = "".join(answer_parts)
                    repo.save_message(conversation_id, "llm", answer)
                    repo.close()
                except Exception:
                    pass

            return StreamingResponse(event_generator_case1(), media_type="text/event-stream")

        # ====== CASE 2: News missing - Parallel execution ======
        print("[CASE 2] News missing - launching parallel processes")
        progress_messages.append({
            "stage": "Generating response (news will follow)",
            "timestamp": datetime.now().isoformat()
        })

        cached_news_parts: List[str] = []
        for company_name, scrip_code, resolved_name in news_check_companies:
            if news_exists_map.get(company_name):
                cached_text = _get_latest_cached_news_summary(company_name, require_today_only=True)
                if not cached_text and resolved_name and resolved_name != company_name:
                    cached_text = _get_latest_cached_news_summary(resolved_name, require_today_only=True)
                if cached_text:
                    cached_news_parts.append(f"\n### {company_name} - Cached News\n{cached_text}")

        async def collect_all_news() -> Dict[str, Optional[str]]:
            """Async function to collect news for missing companies."""
            tasks = []
            missing_companies = [c for c in news_check_companies if not news_exists_map.get(c[0])]
            for company_name, scrip_code, resolved_name in missing_companies:
                tasks.append(asyncio.create_task(_fetch_news_for_company(company_name, scrip_code, resolved_name)))

            results: Dict[str, Optional[str]] = {}
            if tasks:
                completed = await asyncio.gather(*tasks, return_exceptions=True)
                for idx, (company_name, scrip_code, resolved_name) in enumerate(missing_companies):
                    result = completed[idx]
                    if isinstance(result, Exception):
                        print(f"[PROCESS B] News fetch failed for {company_name}: {result}")
                        results[company_name] = None
                    else:
                        results[company_name] = result
            return results

        def _produce_report_chunks(report_queue: queue.Queue) -> None:
            try:
                for chunk in stream_answer_from_data(query, all_data, statement_type, frequency, news_context=None, report_mode="multi-first"):
                    report_queue.put(chunk)
            except Exception as e:
                print(f"[PROCESS A] Report generation error: {e}")
            finally:
                report_queue.put(None)

        async def event_generator_case2() -> AsyncIterator[bytes]:
            """Event generator for CASE 2: Fast path + background news collection."""
            metadata = {"chat_id": chat_id, "conversation_id": conversation_id}
            yield _format_sse_event("metadata", json.dumps(metadata))

            print("[PROCESS B] Starting background news collection")
            news_task = asyncio.create_task(collect_all_news())

            yield _format_sse_event("status", "Started initial report generation while news collection runs in background.")
            print("[PROCESS A] Generating report without news (fast path)")
            answer_parts: List[str] = []
            report_queue: queue.Queue = queue.Queue()
            producer_thread = threading.Thread(target=_produce_report_chunks, args=(report_queue,), daemon=True)
            producer_thread.start()

            while True:
                chunk = await asyncio.to_thread(report_queue.get)
                if chunk is None:
                    break
                answer_parts.append(chunk)
                yield _format_sse_event("message", chunk)

            fast_report = "".join(answer_parts)
            print(f"[PROCESS A] Fast report generated ({len(fast_report)} chars)")

            collected_news_result = {}
            try:
                collected_news_result = await news_task
                print(f"[PROCESS B] News collection completed: {list(collected_news_result.keys())}")
            except Exception as e:
                print(f"[PROCESS B] News collection failed: {e}")

            combined_news_parts = list(cached_news_parts)
            for company_name, news_text in collected_news_result.items():
                if news_text:
                    combined_news_parts.append(f"\n### {company_name} - Recent News\n{news_text}")

            complete_report = fast_report
            if combined_news_parts:
                news_context = "\n".join(combined_news_parts)
                print("[STEP 4] Generating news impact section")
                try:
                    news_impact = await _generate_news_impact_section(
                        original_report=fast_report,
                        query=query,
                        company_data=all_data,
                        news_context=news_context,
                        statement_type=statement_type,
                        frequency=frequency
                    )

                    if news_impact:
                        complete_report = fast_report + "\n\n" + news_impact.strip()
                        print(f"[STEP 5] Streaming final combined report ({len(complete_report)} chars)")
                    else:
                        print("[STEP 5] Streaming base report without news enhancement")
                except Exception as e:
                    print(f"[ERROR] Failed to generate news impact section: {e}")

            if complete_report != fast_report:
                chunk_size = 80
                for i in range(0, len(complete_report[len(fast_report):]), chunk_size):
                    chunk = complete_report[len(fast_report):][i:i+chunk_size]
                    yield _format_sse_event("message", chunk)
                    await asyncio.sleep(0)

            try:
                repo.save_message(conversation_id, "llm", complete_report)
            except Exception as e:
                print(f"[ERROR] Failed to save complete report: {e}")

            yield _format_sse_event("done", "true")

            try:
                repo.close()
            except Exception:
                pass

        return StreamingResponse(event_generator_case2(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        print("Stream error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/chat-history", response_model=List[ChatHistoryResponse])
async def get_chat_history():
    """Get all chat conversations."""
    try:
        repo = SqliteRepository()
        chats = repo.get_conversation_list()
        repo.close()

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
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/chat-history/{chat_id}", response_model=ConversationResponse)
async def get_chat(chat_id: str):
    """Get a specific conversation by ID."""
    try:
        conversation_id = int(chat_id)
        repo = SqliteRepository()
        if not repo.conversation_exists(conversation_id):
            repo.close()
            raise HTTPException(status_code=404, detail="Chat not found")

        conversation = repo.get_conversation(conversation_id)
        messages = repo.get_conversation_messages(conversation_id)
        repo.close()

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
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chat id")
    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/detailed-logs/{chat_id}")
async def get_detailed_logs(chat_id: str):
    """Get detailed input/output logs for a specific chat."""
    try:
        repo = SqliteRepository()
        logs = repo.get_detailed_logs(chat_id)
        repo.close()
        
        if not logs:
            raise HTTPException(status_code=404, detail="No detailed logs found for this chat")
        
        
        return {
            "chat_id": chat_id,
            "logs": logs,
            "total_steps": len(logs)
        }
    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


class CompanyNewsRequest(BaseModel):
    company_name: str
    max_results: int = 10
    days_back: int = 30


@router.post("/llm/company-news", response_model=Dict[str, Any])
async def get_company_news_endpoint(request: CompanyNewsRequest):
    """Fetch recent news articles for a specific company."""
    try:
        repo = SqliteRepository()
        
        # Try to resolve company to get scrip_code
        validation_info = _resolve_company_validation(request.company_name)
        scrip_code = validation_info.get("resolved_scrip_code") if validation_info.get("valid") else None
        
        news_data = NewsService.get_company_news(
            request.company_name,
            max_results=request.max_results,
            days_back=request.days_back
        )
        
        # Save to database if we got articles and have scrip_code
        if scrip_code and news_data.get("articles"):
            repo.save_company_news(scrip_code, request.company_name, news_data["articles"])
        
        repo.close()
        
        return {
            "company_name": request.company_name,
            "scrip_code": scrip_code,
            "articles": news_data.get("articles", []),
            "count": news_data.get("count", 0),
            "source": news_data.get("source"),
            "last_updated": news_data.get("last_updated"),
            "date_range": news_data.get("date_range"),
            "error": news_data.get("error")
        }
    
    except Exception as e:
        print("Error fetching company news:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/company-news-batch", response_model=Dict[str, Any])
async def get_company_news_batch(companies: List[str] = None):
    """Fetch recent news for multiple companies."""
    try:
        if not companies:
            raise HTTPException(status_code=400, detail="No companies provided")
        
        repo = SqliteRepository()
        results = {}
        
        for company_name in companies:
            try:
                # Resolve company
                validation_info = _resolve_company_validation(company_name)
                scrip_code = validation_info.get("resolved_scrip_code") if validation_info.get("valid") else None
                
                # Fetch news
                news_data = NewsService.get_company_news(company_name, max_results=5, days_back=30)
                
                # Save to database
                if scrip_code and news_data.get("articles"):
                    repo.save_company_news(scrip_code, company_name, news_data["articles"])
                
                results[company_name] = {
                    "scrip_code": scrip_code,
                    "articles_count": len(news_data.get("articles", [])),
                    "articles": news_data.get("articles", []),
                    "source": news_data.get("source"),
                    "valid": validation_info.get("valid")
                }
            
            except Exception as e:
                results[company_name] = {
                    "error": str(e)
                }
        
        repo.close()
        
        return {
            "companies_requested": len(companies),
            "companies_processed": len(results),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        print("Error fetching batch news:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/company-news/{scrip_code}")
async def get_cached_company_news(scrip_code: str, limit: int = 10, days_back: int = 30):
    """Get cached news articles for a company by scrip code."""
    try:
        repo = SqliteRepository()
        
        articles = repo.get_company_news(scrip_code, days_back=days_back, limit=limit)
        
        repo.close()
        
        return {
            "scrip_code": scrip_code,
            "articles": articles,
            "count": len(articles),
            "cache_timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        print("Error retrieving cached news:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/test-news/{company_name}")
async def test_news_fetch(company_name: str):
    """Test endpoint to verify news fetching works."""
    try:
        print(f"\n=== Testing News Fetch for {company_name} ===")
        
        # Test direct news service
        news_data = NewsService.get_company_news(company_name, max_results=3, days_back=30)
        
        return {
            "company_name": company_name,
            "test_status": "success",
            "articles_found": len(news_data.get("articles", [])),
            "articles": news_data.get("articles", []),
            "source": news_data.get("source"),
            "error": news_data.get("error"),
            "last_updated": news_data.get("last_updated")
        }
    
    except Exception as e:
        print(f"Error in test_news_fetch: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/llm/delete-unknown-sector-companies")
async def delete_unknown_sector_companies():
    """Deletes all company records from the database where the sector is 'Unknown Sector'
    """
    try:
        repo = SqliteRepository()
        deleted_count = repo.delete_companies_by_sector("")
        repo.close()
        return {"message": f"Successfully deleted {deleted_count} companies with 'Unknown Sector'."}
    except Exception as e:
        print("Error deleting unknown sector companies:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

