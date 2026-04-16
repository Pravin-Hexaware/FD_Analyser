from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import threading
import uuid
import json
import os
import re
import csv
from pathlib import Path

from service.analysis_service import parse_query_and_get_companies, generate_answer_from_data
from repository.sqlite_repository import SqliteRepository

router = APIRouter()



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
    """Get the actual initial prompt used for query parsing."""
    # This should match the system prompt in parse_query_and_get_companies
    return """You are a Senior Financial Analyst and Data Extraction Expert. Your task is to analyze a user query for financial data extraction.

First, break down the query into key components:
- **statement_frequency**: 'quarterly', 'annual', 'both', or 'unspecified'.
- **statement_type**: 'balance_sheet', 'cash_flow', 'income_statement', 'ratios', or 'unspecified'.
- **period**: Specific period like 'latest quarter', 'latest financial year', 'all quarters of latest financial year', 'Q3 2023', 'FY2024-2025', or 'unspecified'.
- **time_horizon**: Normalized window such as 'quarterly', 'annual', 'latest', '2years', '5years', or 'unspecified'.
- **target_companies**: List of company names mentioned.
- **industries**: Any industries mentioned.
- **other_requirements**: Any other specific requirements or questions.
- **get_peer**: Set to true ONLY if the query explicitly asks for peers, competitors, industry comparisons, or benchmark analysis. Set to false if the query mentions specific companies to compare directly.

Then, based on the breakdown, generate a structured JSON response identifying target companies.
If get_peer is true, the system will automatically fetch appropriate peers from the database.
Ensure scrip_codes are accurate BSE codes.

Return strictly valid JSON with no additional text.

JSON Schema:
{
  "intent": {
    "statement_frequency": "string",
    "statement_type": "string",
    "period": "string",
    "time_horizon": "string",
    "get_peer": boolean
  },
  "target_companies": {
    "1": {
      "company": "company_name",
      "symbol": "company_symbol",
      "scrip_code": "company_scrip_code",
      "industry": "company_industry"
    }
  }
}
"""


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
        "past", "fy", "year", "last 2 years", "last 3 years", "last 5 years"
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


@router.post("/llm/target_companies", response_model=Dict[str, Any])
async def llm_target_companies(request: LLMQueryRequest, background_tasks: BackgroundTasks):
    """Parse user query, fetch data, and generate answer with Azure LLM."""
    try:
        repo = SqliteRepository()

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
        print("Step 1: Parsing user query with LLM")
        parsed, initial_llm_prompt, peer_extraction_log = parse_query_and_get_companies(request.query)
        print("1st LLM returned:", parsed)

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
            }

        # Step 2: Fetch data for target companies and peers
        print("Step 2: Fetching data for target companies" + (" + peers" if get_peer else ""))
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
            answer = "Company data for the specified period was unavailable. Please try some other company or period."
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
            }
            if background_note:
                response["background_note"] = background_note

            return response

        # Step 3: Generate answer using LLM
        print("Step 3: Generating answer with 2nd LLM")

        # Prepare the EXACT data being sent to LLM
        system_prompt = f"""You are a Financial Analyst. Answer the user's query using the provided financial data.
The data is for {frequency} financial statements, including {statement_type.replace('_', ' ')} metrics where available.

Provide a clear, concise answer to the query. If data is missing for some companies, note that."""

        user_prompt = f"Query: {request.query}\n\nData: {json.dumps(all_data, indent=2)}"

        final_llm_prompt = get_actual_final_prompt(request.query, all_data, statement_type, frequency)

        # Store data passed to LLM for logging
        data_passed_to_llm = all_data

        answer, tokens_used = generate_answer_from_data(request.query, all_data, statement_type, frequency)
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
            "tokens_used": tokens_used
        }

    except HTTPException:
        raise
    except Exception as e:
        print("Error:", str(e))
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
