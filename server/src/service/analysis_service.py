from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from repository.sqlite_repository import SqliteRepository
from utils.llm_testing import get_azure_chat_openai

_LLM: Any = None

HARDCODED_PEERS: Dict[str, List[str]] = {
    "tcs": ["infy", "wipro","hcltech","ofss"],
    "infy": ["tcs", "wipro","hcltech","ltim"],
    "wipro": ["tcs", "infy","hcltech","ltim"],
     "hcltech": ["tcs", "infy","wipro","ltim"],
     "ltim": ["tcs", "infy","wipro","hcltech"],
     "ofss": ["tcs", "infy","hcltech","ltim"],
    "hext":["coforge","ltim"],
    "coforge":["hext","ltim"],
    "axisbank": ["hdfcbank", "icicibank", "kotakbank", "sbin"],
    "hdfcbank": ["axisbank", "icicibank", "kotakbank", "sbin"],
    "icicibank": ["axisbank", "hdfcbank", "kotakbank", "sbin"],
    "kotakbank": ["axisbank", "hdfcbank", "icicibank", "sbin"],
    "sbin": ["axisbank", "hdfcbank", "icicibank", "kotakbank"],
    "reliance": ["adaniports", "indusindbank", "lt", "itc"],
    "adaniports": ["reliance", "indusindbank", "lt", "itc"],
    "indusindbank": ["reliance", "adaniports", "lt", "itc"],
}


def _get_hardcoded_peers(symbol: str) -> Optional[List[str]]:
    normalized = symbol.strip().lower() if symbol else ""
    return HARDCODED_PEERS.get(normalized)


def _get_company_info_by_symbol(repo: SqliteRepository, symbol: str) -> Dict[str, Any]:
    cur = repo._conn.cursor()
    cur.execute(
        "SELECT symbol, scrip_code, company_name, sector FROM company_table WHERE LOWER(symbol) = ? LIMIT 1",
        (symbol.strip().lower(),),
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


def Get_Peers_from_DB(input_symbols: List[str]) -> Tuple[Dict[str, List[Dict[str, Any]]], str]:
    """Get peers for each input symbol based on sales range and sector matching.

    For each symbol:
    1. Get scrip_code from company_table using symbol
    2. Get latest annual extraction from annual_extractions using scrip_code
    3. Calculate ±20% sales range
    4. Get sector from company_table
    5. Find all companies in same sector
    6. Filter companies whose latest sales fall within the range

    Returns: ({symbol: [peer_companies]}, log_messages)
    """
    if not input_symbols:
        return {}, "LOG: No input symbols provided for peer extraction"

    repo = SqliteRepository()
    peers_result = {}
    log_messages = []

    log_messages.append(f"LOG: Starting peer extraction for symbols: {input_symbols}")

    for symbol in input_symbols:
        try:
            log_messages.append(f"LOG: Processing peer extraction for symbol: {symbol}")
            peers_result[symbol] = []

            log_messages.append(f"LOG: Step 1 - Getting company details for symbol {symbol}")
            cur = repo._conn.cursor()
            cur.execute(
                "SELECT scrip_code, sector, company_name FROM company_table WHERE symbol = ? LIMIT 1",
                (symbol,)
            )
            company_row = cur.fetchone()

            if not company_row:
                log_messages.append(f"LOG: No company found in company_table for symbol {symbol}")
                continue

            target_scrip_code = company_row[0]
            target_sector = company_row[1]
            target_company_name = company_row[2]

            log_messages.append(f"LOG: Found scrip_code {target_scrip_code} and sector {target_sector} for symbol {symbol}")

            hardcoded_peers = _build_peer_list_from_hardcoded(repo, symbol)
            if hardcoded_peers:
                log_messages.append(f"LOG: Using hardcoded peers for {symbol}: {[p['symbol'] for p in hardcoded_peers]}")
                peers_result[symbol] = hardcoded_peers
                continue

            log_messages.append(f"LOG: Step 2 - Getting latest annual extraction for scrip_code {target_scrip_code}")
            target_annual = repo.get_latest_annual_data(target_scrip_code)
            if not target_annual:
                log_messages.append(f"LOG: No annual extraction found for scrip_code {target_scrip_code}")
                continue

            target_sales_raw = _extract_sales_from_json(target_annual.get("parsed_json"))
            if target_sales_raw is None:
                log_messages.append(f"LOG: No sales value found for target company {symbol} in parsed JSON")
                continue

            target_sales_normalized = float(target_sales_raw)
            log_messages.append(
                f"LOG: Found sales data for {symbol} - normalized sales: {target_sales_normalized}"
            )

            min_sales_normalized = target_sales_normalized * 0.8
            max_sales_normalized = target_sales_normalized * 1.2

            log_messages.append(
                f"LOG: Calculated sales range for {symbol}: {min_sales_normalized} to {max_sales_normalized} rupees"
            )

            log_messages.append(f"LOG: Step 3 - Finding all companies in sector {target_sector}")
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

                if company_symbol == symbol or company_scrip == target_scrip_code:
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
                peers_result[symbol] = peer_candidates[:5]
            else:
                peers_result[symbol] = peer_candidates

            log_messages.append(
                f"LOG: Completed peer extraction for {symbol}: found {len(peers_result[symbol])} peers"
            )

        except Exception as e:
            log_messages.append(f"LOG: Error getting peers for {symbol}: {str(e)}")
            continue

    repo.close()
    log_messages.append("LOG: Peer extraction completed for all symbols")

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
        "- **get_peer**: Set to true if the query requires peer company analysis/comparison, false otherwise.\n\n"
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
        input_symbols = []
        
        # Extract symbols from target companies
        for key, company_data in target_companies.items():
            symbol = company_data.get("symbol")
            if symbol:
                input_symbols.append(symbol)
        
        if input_symbols:
            print(f"Fetching peers for symbols: {input_symbols}")
            peers_data, peer_extraction_log = Get_Peers_from_DB(input_symbols)
            
            # Add peers to the parsed response
            for symbol, peers in peers_data.items():
                # Find the company entry and add peers
                for key, company_data in target_companies.items():
                    if company_data.get("symbol") == symbol:
                        company_data["peers"] = {}
                        for i, peer in enumerate(peers, 1):
                            company_data["peers"][str(i)] = peer
                        break

    return parsed, system_prompt, peer_extraction_log if 'peer_extraction_log' in locals() else ""


def generate_answer_from_data(query: str, data: Dict[str, Any], statement_type: str, frequency: str) -> tuple[str, dict[str, int]]:
    """Use LLM to generate an answer based on the query and fetched data.

    Returns a tuple of (answer_text, token_usage).
    """
    system_prompt = f"""
You are a Senior Financial Analyst preparing institutional-grade financial analysis reports for C-suite executives, board members, and institutional investors.

Generate a professional, data-driven financial analysis report in Markdown format. Your audience expects rigorous financial analysis with actionable insights.

# Company Financial Analysis Report

## I. Executive Summary
Provide a concise overview of key financial highlights across all periods presented, including:
- Revenue growth trajectory (absolute and %)
- Profitability trends and margins
- Key operational highlights
- Notable KPIs or metrics that require attention
Keep to 3-4 sentences maximum.

## II. Financial Performance Analysis
Present a comprehensive period-by-period analysis using tables. Each table MUST have:
- **Period** column (exact quarter/year provided in data)
- Key metrics: Revenue, Operating Profit, Net Profit, EPS
- All metrics shown as absolute values

Calculate and highlight in the narrative:
- Quarter-over-Quarter (QoQ) growth rates (%)
- Year-over-Year (YoY) growth rates (%)
- Trend direction and acceleration/deceleration

## III. Profitability & Margin Analysis
Analyze margin trends across all periods:
- Operating Profit Margin (OPM %): Trend analysis with drivers
- Net Profit Margin (NPM): Movement and reasons
- Other income contribution: Material changes
- Tax rate trends: Normalized vs reported

Identify margin expansion/compression drivers and sustainability.

## IV. Cost Structure & Operational Efficiency
- Major cost components: Employee benefits, Subcontracting, Finance costs, Depreciation
- Cost as % of Revenue: Trends across periods
- Operational efficiency indicators: Revenue per employee (if calculable), fixed vs variable cost splits
- Material cost movements and their drivers

## V. Cash Generation & Reinvestment
- Operating income to sales conversion
- Tax impact on bottom line
- Depreciation trends indicating capex patterns
- Overall profitability quality assessment

## VI. Comparative & Trend Analysis
- If multiple periods are provided, calculate multi-period trends (linear if < 5 periods, trend lines if longer)
- Identify inflection points or significant changes
- Segment analysis if different business lines are visible
- Peer positioning (if industry context provided)

## VII. Key Observations & Risk Factors
Highlight:
- Positive developments: Growing revenue, margin expansion, improved efficiency
- Areas of concern: Margin compression, rising costs, declining profitability
- One-time or extraordinary items impacting comparability
- Data quality notes: Missing periods, incomplete metrics

## VIII. Strategic Recommendations & Outlook
- Based ONLY on historical data trends, outline positive developments and areas requiring management attention
- Clearly separate fact-based analysis from forward-looking interpretation
- Do NOT project future performance beyond the data provided
- Recommend areas for deeper management discussion

---

**Analysis Parameters:** {frequency} financial statements | Focus: {statement_type.replace('_', ' ')}

**CRITICAL REQUIREMENTS:**
1. Present ONLY data explicitly provided in the input - no fabrication or extrapolation
2. Always show period labels in tables and references
3. Calculate all QoQ and YoY changes explicitly
4. Use proper number formatting with Indian currency conventions (INR, lakhs, crores) unless USD provided
5. Be specific with metrics: cite exact values with periods
6. Flag any incomplete or missing data clearly
7. Provide actionable insights suitable for board-level decision making
8. Maintain professional tone throughout
    """

    user_prompt = f"Query: {query}\n\nFinancial Data (JSON format - for historical queries, data is provided as arrays of records):\n{json.dumps(data, indent=2)}"

    response = _invoke_llm(system_prompt, user_prompt, max_tokens=2500)

    token_usage = _extract_token_usage(response)
    normalized = _normalize_llm_response(response)
    return normalized.get("content", "No answer generated."), token_usage
