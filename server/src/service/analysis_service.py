from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from repository.sqlite_repository import SqliteRepository
from utils.llm_testing import get_azure_chat_openai

_LLM: Any = None

HARDCODED_PEERS: Dict[str, List[str]] = {
    "tcs": ["infy", "wipro"],
    "infy": ["tcs", "wipro"],
    "wipro": ["infy","hcltech"],
     "hcltech": ["tcs", "infy"],
     "ltim": ["wipro","hcltech"],
     "ofss": ["tcs","hcltech"],
    "hext":["coforge","ltim"],
    "coforge":["hext","ltim"],
    "axisbank": ["hdfcbank", "icicibank"],
    "hdfcbank": ["axisbank", "sbin"],
    "icicibank": [ "kotakbank", "sbin"],
    "kotakbank": [ "hdfcbank", "icicibank"],
    "sbin": ["axisbank", "hdfcbank"],
    "reliance": ["adaniports", "indusindbank"],
    "adaniports": ["reliance", "itc"],
    "indusindbank": ["lt", "itc"],
}


def _get_hardcoded_peers(symbol: str) -> Optional[List[str]]:
    normalized = symbol.strip().lower() if symbol else ""
    return HARDCODED_PEERS.get(normalized)


def _get_company_info_by_symbol(repo: SqliteRepository, symbol: Optional[str]) -> Dict[str, Any]:
    if not symbol:
        return {"symbol": "", "scrip_code": None, "company": "", "industry": None}

    cur = repo._conn.cursor()
    normalized_symbol = symbol.strip().lower()
    cur.execute(
        "SELECT symbol, scrip_code, company_name, sector FROM company_table WHERE LOWER(symbol) = ? LIMIT 1",
        (normalized_symbol,),
    )
    row = cur.fetchone()
    if not row:
        return {"symbol": symbol, "scrip_code": None, "company": symbol, "industry": None}
    return {
        "symbol": row[0],
        "scrip_code": row[1],
        "company": row[2],
        "industry": row[3],
    }


def _get_company_info_by_name(repo: SqliteRepository, company_name: Optional[str]) -> Dict[str, Any]:
    if not company_name:
        return {"symbol": "", "scrip_code": None, "company": "", "industry": None}

    normalized_name = company_name.strip().lower()
    cur = repo._conn.cursor()
    cur.execute(
        "SELECT symbol, scrip_code, company_name, sector FROM company_table WHERE LOWER(company_name) = ? LIMIT 1",
        (normalized_name,),
    )
    row = cur.fetchone()
    if not row:
        cur.execute(
            "SELECT symbol, scrip_code, company_name, sector FROM company_table WHERE LOWER(company_name) LIKE ? LIMIT 1",
            (f"%{normalized_name}%",),
        )
        row = cur.fetchone()
    if not row:
        return {"symbol": "", "scrip_code": None, "company": company_name, "industry": None}
    return {
        "symbol": row[0],
        "scrip_code": row[1],
        "company": row[2],
        "industry": row[3],
    }


def _build_peer_list_from_hardcoded(repo: SqliteRepository, symbol: str) -> List[Dict[str, Any]]:
    peer_symbols = _get_hardcoded_peers(symbol)
    if not peer_symbols:
        return []

    peers = []
    for peer_symbol in peer_symbols:
        peer_info = _get_company_info_by_symbol(repo, peer_symbol)
        peers.append(peer_info)
    return peers


def _get_llm() -> Any:
    """Return a cached AzureChatOpenAI instance (or create it)."""
    global _LLM
    if _LLM is None:
        _LLM = get_azure_chat_openai()
        if _LLM is None:
            raise RuntimeError("Failed to initialize AzureChatOpenAI from utils.llm_testing")
    return _LLM


def _try_parse_numeric_value(raw_value: Any) -> Optional[float]:
    if raw_value is None:
        return None

    if isinstance(raw_value, (int, float)):
        return float(raw_value)

    if isinstance(raw_value, str):
        cleaned = raw_value.replace(",", "").replace("₹", "").replace("INR", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            try:
                return float(re.sub(r"[^0-9.\-]", "", cleaned))
            except ValueError:
                return None

    return None


def _invoke_llm(system_prompt: str, user_prompt: str, max_tokens: int = 800) -> Any:
    """Invoke the LangChain AzureChatOpenAI model and return the raw response."""
    llm = _get_llm()
    # LangChain returns an object with a .content attribute.
    resp = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ],
        max_tokens=max_tokens,
    )
    return resp


def _normalize_llm_response(resp: Any) -> Dict[str, Any]:
    """Convert LangChain LLM response objects into plain dicts for JSON serialization."""
    if resp is None:
        return {}

    if isinstance(resp, dict):
        return resp

    # LangChain AIMessage-like objects
    content = getattr(resp, "content", None)
    metadata = getattr(resp, "metadata", None) or getattr(resp, "extra", None)
    additional_kwargs = getattr(resp, "additional_kwargs", None)

    result: Dict[str, Any] = {}
    if content is not None:
        result["content"] = str(content)
    if metadata is not None:
        result["metadata"] = metadata
    if additional_kwargs is not None:
        result["additional_kwargs"] = additional_kwargs

    # Fallback to str() if empty
    if not result:
        result["content"] = str(resp)

    return result


def _extract_token_usage(resp: Any) -> Dict[str, int]:
    """Extract aggregated token usage from a raw LLM response object."""
    def _normalize_usage_dict(d: dict[str, Any]) -> Dict[str, int]:
        return {
            "input_tokens": int(d.get("input_tokens", d.get("inputTokens", 0) or 0)),
            "output_tokens": int(d.get("output_tokens", d.get("outputTokens", 0) or 0)),
            "total_tokens": int(d.get("total_tokens", d.get("totalTokens", d.get("total_tokens", 0)) or 0)),
        }

    def _find_usage(obj: Any) -> dict[str, int] | None:
        if isinstance(obj, dict):
            if any(k in obj for k in ("input_tokens", "inputTokens", "output_tokens", "outputTokens", "total_tokens", "totalTokens")):
                return _normalize_usage_dict(obj)
            for value in obj.values():
                result = _find_usage(value)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = _find_usage(item)
                if result is not None:
                    return result
        return None

    if resp is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    # Start from top-level usage-like fields if present.
    candidates = []
    if isinstance(resp, dict):
        candidates.append(resp)
    else:
        for attr in ("usage_metadata", "usage", "metadata", "extra", "additional_kwargs", "llm_output", "generations"):
            candidate = getattr(resp, attr, None)
            if candidate is not None:
                candidates.append(candidate)

        # Also fall back to __dict__ for objects with nested data fields.
        if hasattr(resp, "__dict__"):
            candidates.append({k: v for k, v in resp.__dict__.items() if v is not None})

    for candidate in candidates:
        tokens = _find_usage(candidate)
        if tokens is not None:
            return tokens

    # As a last resort try to search the entire response object if it is dict/list-like.
    if isinstance(resp, (dict, list)):
        tokens = _find_usage(resp)
        if tokens is not None:
            return tokens

    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def test_llm_connection() -> Dict[str, Any]:
    """Test the Azure OpenAI connection with a small prompt."""
    resp = _invoke_llm(
        system_prompt="You are a helpful assistant.",
        user_prompt="Please respond with a short greeting.",
        max_tokens=20,
    )
    return _normalize_llm_response(resp)


def generate_analysis_report(records: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Generate an analysis report for a list of company metric records.

    Returns a tuple of (report_text, raw_llm_response).
    """

    if not records:
        raise ValueError("No records provided for analysis.")

    # Keep the prompt size reasonable by truncating if too many records.
    max_records = 20
    truncated = False
    if len(records) > max_records:
        records_to_send = records[:max_records]
        truncated = True
    else:
        records_to_send = records

    # Build a compact markdown table for the most important metrics to keep prompts small.
    def _build_markdown_table(recs: List[Dict[str, Any]]) -> str:
        headers = ["company_name", "company_symbol", "Sales", "NetProfit", "OPM_percentage"]
        rows = ["| " + " | ".join(headers) + " |", "|---|---|---|---|---|"]
        for r in recs:
            row = []
            for h in headers:
                v = r.get(h)
                row.append(str(v) if v is not None else "")
            rows.append("| " + " | ".join(row) + " |")
        return "\n".join(rows)

    data_block = _build_markdown_table(records_to_send)
    if truncated:
        data_block += "\n\n*(only the first %d records shown)*" % max_records

    system_prompt = (
        "You are a professional financial analyst. "
        "You have been given a table of company financial metrics. "
        "Produce a concise analysis report in Markdown format. "
        "Focus on trends, comparisons, outliers, and data quality issues."
    )

    user_prompt = (
        "Here is the data to analyze (Markdown table):\n\n" + data_block + "\n\n"
        "Please provide a markdown report that includes:\n"
        "- Key observations across the companies\n"
        "- Any clear outliers or anomalies\n"
        "- A short conclusion\n"
        "Return only the markdown report (no extra explanation)."
    )

    def _get_response_content(resp: Any) -> str:
        if hasattr(resp, "content"):
            return str(getattr(resp, "content") or "").strip()
        if isinstance(resp, dict):
            choices = resp.get("choices")
            if choices and isinstance(choices, list):
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message") or first.get("text")
                    if isinstance(message, dict):
                        return str(message.get("content") or "").strip()
                    if isinstance(message, str):
                        return message.strip()
            return str(resp).strip()
        return str(resp).strip()

    # Primary call
    llm_response = _invoke_llm(system_prompt, user_prompt, max_tokens=400)
    report = _get_response_content(llm_response)
    llm_response_dict = _normalize_llm_response(llm_response)

    # Retry with smaller output budget if empty
    if not report:
        retry_response = _invoke_llm(system_prompt, user_prompt, max_tokens=250)
        report = _get_response_content(retry_response)
        if report:
            return report, _normalize_llm_response(retry_response)

    if not report:
        report = (
            "No analysis was generated (LLM returned empty output). "
            "Please check the model/deployment or reduce input size."
        )

    return report, llm_response_dict 


def _try_parse_numeric_value(raw_value: Any) -> Optional[float]:
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    if isinstance(raw_value, str):
        cleaned = raw_value.replace(",", "").replace("₹", "").replace("INR", "").strip()
        match = re.search(r"[-+]?[0-9]*\.?[0-9]+", cleaned)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _find_value_by_keywords(data: Any, keywords: List[str]) -> Optional[float]:
    if isinstance(data, dict):
        for key, value in data.items():
            key_text = str(key).lower()
            if any(keyword in key_text for keyword in keywords):
                parsed = _try_parse_numeric_value(value)
                if parsed is not None:
                    return parsed
            nested = _find_value_by_keywords(value, keywords)
            if nested is not None:
                return nested
    elif isinstance(data, list):
        for item in data:
            found = _find_value_by_keywords(item, keywords)
            if found is not None:
                return found
    return None


def _extract_sales_from_json(parsed_json: Any) -> Optional[float]:
    return _find_value_by_keywords(parsed_json, ["sales", "revenue", "net sales", "total revenue"])


def Get_Peers_from_DB(input_requests: List[tuple[str, Optional[str], str]]) -> Tuple[Dict[str, List[Dict[str, Any]]], str]:
    """Get peers for each input request based on symbol or company name.

    Each request is a tuple of (request_key, parsed_symbol, company_name).
    This allows fallback from a malformed symbol to a company-name lookup.
    """
    if not input_requests:
        return {}, "LOG: No input requests provided for peer extraction"

    repo = SqliteRepository()
    peers_result = {}
    log_messages = []

    log_messages.append(f"LOG: Starting peer extraction for requests: {input_requests}")

    for request_key, symbol, company_name in input_requests:
        try:
            log_messages.append(f"LOG: Processing peer extraction for request {request_key}, symbol={symbol}, company_name={company_name}")
            peers_result[request_key] = []

            company_info = _get_company_info_by_symbol(repo, symbol) if symbol else {"scrip_code": None}
            if not company_info.get("scrip_code"):
                log_messages.append(f"LOG: Symbol lookup failed for '{symbol}', trying company name lookup for '{company_name}'")
                company_info = _get_company_info_by_name(repo, company_name)

            if not company_info.get("scrip_code"):
                log_messages.append(f"LOG: No company found in company_table for symbol '{symbol}' or name '{company_name}'")
                continue

            target_symbol = company_info["symbol"]
            target_scrip_code = company_info["scrip_code"]
            target_sector = company_info.get("industry") or company_info.get("company")
            log_messages.append(f"LOG: Resolved company for request {request_key} to symbol {target_symbol}, scrip_code {target_scrip_code}")

            hardcoded_peers = _build_peer_list_from_hardcoded(repo, target_symbol)
            if hardcoded_peers:
                log_messages.append(f"LOG: Using hardcoded peers for {target_symbol}: {[p['symbol'] for p in hardcoded_peers]}")
                peers_result[request_key] = hardcoded_peers
                continue

            log_messages.append(f"LOG: Step 2 - Getting latest annual extraction for scrip_code {target_scrip_code}")
            target_annual = repo.get_latest_annual_data(target_scrip_code)
            if not target_annual:
                log_messages.append(f"LOG: No annual extraction found for scrip_code {target_scrip_code}")
                continue

            target_sales_raw = _extract_sales_from_json(target_annual.get("parsed_json"))
            if target_sales_raw is None:
                log_messages.append(f"LOG: No sales value found for target company {target_symbol} in parsed JSON")
                continue

            target_sales_normalized = float(target_sales_raw)
            log_messages.append(
                f"LOG: Found sales data for {target_symbol} - normalized sales: {target_sales_normalized}"
            )

            min_sales_normalized = target_sales_normalized * 0.8
            max_sales_normalized = target_sales_normalized * 1.2

            log_messages.append(
                f"LOG: Calculated sales range for {target_symbol}: {min_sales_normalized} to {max_sales_normalized} rupees"
            )

            log_messages.append(f"LOG: Step 3 - Finding all companies in sector {target_sector}")
            cur = repo._conn.cursor()
            cur.execute(
                "SELECT symbol, scrip_code, company_name FROM company_table WHERE sector = ?",
                (target_sector,),
            )
            sector_companies = cur.fetchall()
            log_messages.append(f"LOG: Found {len(sector_companies)} companies in sector {target_sector}")

            peer_candidates = []
            for company_row in sector_companies:
                company_symbol = company_row[0]
                company_scrip = company_row[1]
                company_name = company_row[2]

                if company_symbol == target_symbol or company_scrip == target_scrip_code:
                    log_messages.append(f"LOG: Skipping target company {company_symbol} ({company_scrip})")
                    continue

                company_annual = repo.get_latest_annual_data(company_scrip)
                if not company_annual:
                    log_messages.append(
                        f"LOG: No annual extraction found for peer candidate {company_symbol} ({company_scrip})"
                    )
                    continue

                company_sales_raw = _extract_sales_from_json(company_annual.get("parsed_json"))
                if company_sales_raw is None:
                    log_messages.append(
                        f"LOG: No sales value found for peer candidate {company_symbol} ({company_scrip})"
                    )
                    continue

                company_sales_normalized = float(company_sales_raw)
                log_messages.append(
                    f"LOG: Checking peer candidate {company_symbol}: normalized sales = {company_sales_normalized}"
                )

                if min_sales_normalized <= company_sales_normalized <= max_sales_normalized:
                    peer_info = {
                        "company": company_name,
                        "symbol": company_symbol,
                        "scrip_code": company_scrip,
                        "industry": target_sector,
                        "sales": company_sales_raw,
                        "normalized_sales": company_sales_normalized,
                    }
                    peer_candidates.append(peer_info)
                    log_messages.append(f"LOG: ✓ Added peer: {company_symbol}")
                else:
                    log_messages.append(f"LOG: ✗ Rejected peer: {company_symbol}")

            if len(peer_candidates) > 5:
                log_messages.append(f"LOG: Step 4 - Limiting to top 5 peers by sales proximity")
                peer_candidates.sort(
                    key=lambda x: abs(x["normalized_sales"] - target_sales_normalized)
                )
                peers_result[request_key] = peer_candidates[:5]
            else:
                peers_result[request_key] = peer_candidates

            log_messages.append(
                f"LOG: Completed peer extraction for {request_key}: found {len(peers_result[request_key])} peers"
            )

        except Exception as e:
            log_messages.append(f"LOG: Error getting peers for request {request_key}: {str(e)}")
            continue

    repo.close()
    log_messages.append("LOG: Peer extraction completed for all requests")

    full_log = "\n".join(log_messages)
    return peers_result, full_log


def parse_query_and_get_companies(query: str) -> Tuple[Dict[str, Any], str]:
    """Use Azure LLM to break down the user query and generate structured response with companies.
    
    If get_peer is true, automatically fetch peers from database based on sales range and sector.
    """
    if not query or not query.strip():
        raise ValueError("Query must not be empty.")

    system_prompt = (
        "You are a Senior Financial Analyst and Data Extraction Expert. Your task is to analyze a user query for financial data extraction.\n\n"
        "First, break down the query into key components:\n"
        "- **statement_frequency**: 'quarterly', 'annual', 'both', or 'unspecified'.\n"
        "- **statement_type**: 'balance_sheet', 'cash_flow', 'income_statement', 'ratios', or 'unspecified'.\n"
        "- **period**: Specific period like 'latest quarter', 'Q3 2023', 'FY2024', or 'unspecified'.\n"
        "- **time_horizon**: Normalized timeframe such as 'latest', '2years', '5years', or 'unspecified'.\n"
        "- **target_companies**: List of company names mentioned.\n"
        "- **industries**: Any industries mentioned.\n"
        "- **other_requirements**: Any other specific requirements or questions.\n"
        "- **get_peer**: Set to true ONLY if the query explicitly asks for peers, competitors, industry comparisons, or benchmark analysis. Set to false if the query mentions specific companies to compare directly.\n\n"
        "Then, based on the breakdown, generate a structured JSON response identifying target companies.\n"
        "If get_peer is true, the system will first apply hardcoded peer mappings and then fall back to database peer lookup if needed.\n"
        "Ensure scrip_codes are accurate BSE codes.\n\n"
        "Return strictly valid JSON with no additional text.\n\n"
        "JSON Schema:\n"
        "{\n"
        "  \"intent\": {\n"
        "    \"statement_frequency\": \"string\",\n"
        "    \"statement_type\": \"string\",\n"
        "    \"period\": \"string\",\n"
        "    \"time_horizon\": \"string\",\n"
        "    \"get_peer\": boolean\n"
        "  },\n"
        "  \"target_companies\": {\n"
        "    \"1\": {\n"
        "      \"company\": \"company_name\",\n"
        "      \"symbol\": \"company_symbol\",\n"
        "      \"scrip_code\": \"company_scrip_code\",\n"
        "      \"industry\": \"company_industry\"\n"
        "    }\n"
        "  }\n"
        "}\n"
    )

    response = _invoke_llm(system_prompt, query, max_tokens=800)
    normalized = _normalize_llm_response(response)
    text = normalized.get("content", "")

    try:
        parsed = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                parsed = json.loads(candidate)
            except Exception:
                parsed = {"error": "Failed to parse JSON"}

    # If get_peer is true, fetch peers from database
    if parsed.get("intent", {}).get("get_peer", False):
        target_companies = parsed.get("target_companies", {})
        input_requests: List[tuple[str, Optional[str], str]] = []

        for key, company_data in target_companies.items():
            symbol = company_data.get("symbol")
            company_name = company_data.get("company") or key
            input_requests.append((key, symbol, company_name))

        if input_requests:
            print(f"Fetching peers for requests: {input_requests}")
            peers_data, peer_extraction_log = Get_Peers_from_DB(input_requests)

            # Add peers to the parsed response
            for request_key, peers in peers_data.items():
                company_data = target_companies.get(request_key)
                if not company_data:
                    continue
                company_data["peers"] = {}
                for i, peer in enumerate(peers, 1):
                    company_data["peers"][str(i)] = peer

    return parsed, system_prompt, peer_extraction_log if 'peer_extraction_log' in locals() else ""


def _format_period_from_publication_date(publication_date: Optional[str]) -> str:
    """Extract and format the period from publication_date field.
    
    Handles formats like:
    - 'Q1 FY19 (Apr-Jun)' -> 'June 2019'
    - 'Q4 2025-26 (Jan-Mar)' -> 'March 2026'
    - 'DQ2025-2026' -> '2025-2026'
    - Direct date strings
    """
    if not publication_date:
        return "Unspecified"
    
    pub_str = str(publication_date).strip()
    
    # Month mapping
    months = {
        'Apr': 'April', 'Jan': 'January', 'Feb': 'February', 'Mar': 'March',
        'May': 'May', 'Jun': 'June', 'Jul': 'July', 'Aug': 'August',
        'Sep': 'September', 'Oct': 'October', 'Nov': 'November', 'Dec': 'December'
    }
    
    # Try to extract (Month, Year) from parentheses format with fiscal year range
    # Example: "Q4 2025-26 (Jan-Mar)" should return "March 2026", "Q3 2025-26 (Oct-Dec)" should return "December 2025"
    paren_match = re.search(r'\(([A-Z][a-z]{2})-([A-Z][a-z]{2})\)', pub_str)
    if paren_match:
        month_str = paren_match.group(2)  # Get end month (e.g., 'Mar')
        # Try to extract fiscal year range like "2025-26"
        fy_match = re.search(r'(\d{4})-(\d{2,4})', pub_str)
        if fy_match:
            start_year = fy_match.group(1)
            end_year_part = fy_match.group(2)
            # Handle both "2025-26" and "2025-2026" formats
            if len(end_year_part) == 2:
                end_year = start_year[:2] + end_year_part  # "2025-26" -> "2026"
            else:
                end_year = end_year_part
            
            # Fiscal year: Apr-Jun(Q1), Jul-Sep(Q2), Oct-Dec(Q3) are in start_year
            # Jan-Mar(Q4) is in end_year
            if month_str in ['Jan', 'Feb', 'Mar']:
                year_to_use = end_year
            else:
                year_to_use = start_year
            
            month_name = months.get(month_str, month_str)
            return f"{month_name} {year_to_use}"
        else:
            # Fallback: extract first 4-digit year
            year_match = re.search(r'(\d{4})', pub_str)
            if year_match:
                year = year_match.group(1)
                month_name = months.get(month_str, month_str)
                return f"{month_name} {year}"
    
    # Try format like 'DQ2025-2026' -> extract just the period
    if 'D' in pub_str and '-' in pub_str:
        year_match = re.search(r'(\d{4})-(\d{4})', pub_str)
        if year_match:
            return f"{year_match.group(1)}-{year_match.group(2)}"
    
    # Fallback: try to find any year
    year_match = re.search(r'(\d{4})', pub_str)
    if year_match:
        return pub_str  # Return as-is if it contains a year
    
    return pub_str  # Return original if no pattern matched


def generate_answer_from_data(query: str, data: Dict[str, Any], statement_type: str, frequency: str) -> tuple[str, dict[str, int]]:
    """Use LLM to generate an answer based on the query and fetched data.

    Returns a tuple of (answer_text, token_usage).
    """
    # Pre-process data to format periods nicely
    formatted_data = data
    if isinstance(data, list):
        formatted_data = []
        for record in data:
            formatted_record = record.copy() if isinstance(record, dict) else record
            if isinstance(formatted_record, dict) and "publication_date" in formatted_record:
                formatted_record["Period"] = _format_period_from_publication_date(
                    formatted_record.get("publication_date")
                )
            formatted_data.append(formatted_record)
    elif isinstance(data, dict):
        formatted_data = data.copy()
        # If it has a publication_date, add formatted Period
        if "publication_date" in formatted_data:
            formatted_data["Period"] = _format_period_from_publication_date(
                formatted_data.get("publication_date")
            )
    
    system_prompt = f"""
You are a Senior Financial Analyst and Strategic Advisor preparing comprehensive, institutional-grade financial analysis reports for C-suite executives, board members, institutional investors, and senior financial representatives. Your reports must be rigorous, data-driven, and provide deep strategic insights that inform critical business decisions.

Generate a detailed, professional financial analysis report in Markdown format. The report should comprehensively analyze ALL available financial data, metrics, and parameters provided in the input, not just a subset. Pay special attention to any notes, comments, observations, or qualitative text embedded in the JSON data. Use those notes as evidence and integrate them with numeric findings.

Extract and analyze every relevant financial metric, trend, ratio, and insight from the complete dataset. Do not limit analysis to predefined metrics - dynamically identify and analyze all key financial indicators present in the data.

The report should be extremely detailed and thorough, suitable for board-level strategic discussions, investment committee reviews, and executive decision-making. Length is not a constraint - provide exhaustive analysis that covers all aspects of the financial performance, risks, opportunities, and implications.

# Comprehensive Financial Analysis Report

## I. Executive Summary
Provide a comprehensive executive overview synthesizing key findings across all periods and companies:
- Strategic financial performance highlights and trajectory
- Critical profitability, efficiency, and growth metrics
- Major risk indicators and opportunities
- Strategic implications for business direction and governance
- Key recommendations for immediate executive attention

## II. Company Overview and Strategic Context
For each company analyzed:
- Business model and industry positioning
- Strategic objectives and market dynamics
- Key value drivers and competitive advantages
- Regulatory and macroeconomic context implications

## III. Comprehensive Financial Performance Analysis
Conduct exhaustive period-by-period and cross-company analysis of ALL financial metrics available:

### Revenue Analysis
- Detailed revenue composition and sources
- Revenue growth drivers and sustainability
- Geographic and segment revenue breakdown (if available)
- Revenue quality indicators and recurring vs. one-time components

### Profitability Deep Dive
- Operating profit margins: Trends, drivers, and sustainability
- Net profit margins: Components and influencing factors
- EBITDA margins and operating efficiency metrics
- Gross margins by business segment or product line

### Cost Structure Analysis
- Detailed cost breakdown: Fixed vs. variable costs
- Major expense categories: Personnel, R&D, marketing, administrative
- Cost optimization opportunities and efficiency trends
- Cost-to-revenue ratios and benchmarking

### Balance Sheet Analysis
- Asset quality and composition
- Liability structure and debt management
- Working capital efficiency and cash conversion cycles
- Capital structure optimization and financial leverage

### Cash Flow Analysis
- Operating cash flow generation and quality
- Investment and financing cash flows
- Free cash flow trends and utilization
- Cash flow forecasting implications

### Key Financial Ratios and Metrics
- Liquidity ratios: Current ratio, quick ratio, cash ratios
- Solvency ratios: Debt-to-equity, debt-to-assets, interest coverage
- Efficiency ratios: Asset turnover, inventory turnover, receivables days
- Profitability ratios: ROA, ROE, ROCE, EPS trends
- Valuation metrics: P/E, P/B, EV/EBITDA (if market data available)

## IV. Trend Analysis and Forecasting Insights
- Multi-period trend analysis with statistical significance
- Growth acceleration/deceleration patterns
- Cyclical vs. structural performance changes
- Forward-looking indicators from historical trends

## V. Comparative Analysis
- Peer group comparisons across all metrics
- Industry benchmarking and positioning
- Competitive advantages and disadvantages
- Market share and growth relative to peers

## VI. Risk Assessment and Mitigation
- Financial risk factors: Liquidity, solvency, currency, interest rate
- Operational risks: Cost pressures, margin compression, supply chain
- Market risks: Competition, demand fluctuations, regulatory changes
- Strategic risks: Market positioning, technology disruption, M&A implications
- Quantitative risk metrics and stress testing insights

## VII. Strategic Implications and Recommendations
- Strategic opportunities identified from financial trends
- Areas requiring management intervention
- Capital allocation recommendations
- Risk mitigation strategies
- Governance and compliance considerations
- Long-term value creation strategies

## VIII. Data Quality and Limitations
- Assessment of data completeness and reliability
- Missing data impacts on analysis
- Assumptions and estimation methodologies used
- Recommendations for improved financial reporting

## IX. Appendices
- Detailed financial statements and schedules
- Ratio calculations and trend charts
- Peer comparison tables
- Statistical analysis and regression insights
- Glossary of terms and methodologies

---

**Analysis Parameters:** {frequency} financial statements | Focus: {statement_type.replace('_', ' ')} | Data Scope: Comprehensive analysis of all available financial parameters

**CRITICAL REQUIREMENTS:**
1. Analyze EVERY financial metric and parameter present in the provided data - do not limit to predefined fields
2. Provide exhaustive, board-level analysis with strategic implications
3. Use precise numerical references with proper formatting (INR crores/lakhs, percentages, ratios)
4. Identify trends, drivers, risks, and opportunities across all data dimensions
5. Maintain professional, executive-level tone suitable for C-suite and board presentations
6. Flag data limitations and provide conservative interpretations where uncertainty exists
7. Generate actionable insights that drive strategic decision-making
8. Structure report for easy navigation and executive summary consumption
9. Include quantitative analysis with statistical context where applicable
10. Provide forward-looking strategic recommendations based on historical trends
    """

    user_prompt = f"Query: {query}\n\nFinancial Data (JSON format - for historical queries, data is provided as arrays of records):\n{json.dumps(formatted_data, indent=2)}"

    response = _invoke_llm(system_prompt, user_prompt)

    token_usage = _extract_token_usage(response)
    normalized = _normalize_llm_response(response)
    return normalized.get("content", "No answer generated."), token_usage
