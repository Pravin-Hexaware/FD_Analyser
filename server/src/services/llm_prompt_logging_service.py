"""LLM prompt logging helpers."""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import LOGS_DIR


def write_llm_log(
    user_query: str,
    llm_prompt: str,
    llm_response: str,
    db_data: Dict[str, Any],
    data_passed_to_llm: Dict[str, Any],
    final_prompt: str,
    final_response: str,
    peer_extraction_log: str = "",
    token_usage: Optional[Dict[str, int]] = None,
) -> None:
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_filepath = LOGS_DIR / f"Log-{timestamp}.log"

        log_content = f"""=== LLM TARGET COMPANIES LOG ===
Timestamp: {datetime.now().isoformat()}
Log File: Log-{timestamp}.log

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
        log_filepath.write_text(log_content, encoding="utf-8")
        print(f"LLM log written to: {log_filepath}")
    except Exception as e:
        print(f"Error writing LLM log: {str(e)}")


def get_actual_initial_prompt() -> str:
    return """NLP-Based Query Parsing (No LLM):
- Uses pattern matching and fuzzy matching against BSE company list
- Extracts statement frequency, type, period, time horizon, and target companies
- Deterministic rule-based extraction for company names from query
- Automatically detects peer request indicators
- Returns structured JSON compatible with existing pipeline"""


def get_actual_final_prompt(query: str, data: Dict[str, Any], statement_type: str, frequency: str) -> str:
    system_prompt = f"""You are a Financial Analyst. Answer the user's query using the provided parsed JSON financial data.
The data is for {frequency} financial statements, including {statement_type.replace('_', ' ')} metrics where available.

Provide a clear, concise manager-style analysis report. Use only the data present in the JSON and mention if any requested period or metric is missing."""
    user_prompt = f"Query: {query}\n\nData: {json.dumps(data, indent=2)}"
    return f"{system_prompt}\n\n{user_prompt}"


def format_sse_event(event_name: str, data: str) -> bytes:
    sanitized = data.replace("\r", "").split("\n")
    formatted = "".join(f"data: {line}\n" for line in sanitized)
    return f"event: {event_name}\n{formatted}\n".encode("utf-8")
