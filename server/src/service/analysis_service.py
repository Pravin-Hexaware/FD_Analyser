from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from repository.sqlite_repository import SqliteRepository
from utils.llm_testing import get_azure_chat_openai

_LLM: Any = None


def _get_llm() -> Any:
    """Return a cached AzureChatOpenAI instance (or create it)."""
    global _LLM
    if _LLM is None:
        _LLM = get_azure_chat_openai()
        if _LLM is None:
            raise RuntimeError("Failed to initialize AzureChatOpenAI from utils.llm_testing")
    return _LLM


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


def Get_Peers_from_DB(input_symbols: List[str]) -> Tuple[Dict[str, List[Dict[str, Any]]], str]:
    """Get peers for each input symbol based on sales range and sector matching.
    
    For each symbol:
    1. Get scrip_code from company_table using symbol
    2. Get annual sales from annual_table using scrip_code
    3. Calculate ±15% sales range
    4. Get sector from company_table
    5. Find all companies in same sector
    6. Filter companies whose latest sales fall within the range
    7. Handle different denominations (lakhs, crores, millions)
    
    Returns: ({symbol: [peer_companies]}, log_messages)
    """
    def normalize_sales_value(sales: float, level_of_rounding: str) -> float:
        """Normalize sales value to rupees based on denomination."""
        if not level_of_rounding:
            return sales  # Assume already in rupees
        
        rounding_lower = level_of_rounding.lower().strip()
        
        if 'lakh' in rounding_lower or 'lakhs' in rounding_lower:
            return sales * 100000  # 1 lakh = 100,000 rupees
        elif 'crore' in rounding_lower or 'crores' in rounding_lower:
            return sales * 10000000  # 1 crore = 10,000,000 rupees
        elif 'million' in rounding_lower or 'millions' in rounding_lower:
            return sales * 1000000  # 1 million = 1,000,000 rupees
        elif 'thousand' in rounding_lower or 'thousands' in rounding_lower:
            return sales * 1000  # 1 thousand = 1,000 rupees
        else:
            return sales  # Assume already in rupees or unknown denomination
    
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
            
            # Step 1: Get scrip_code from company_table using symbol
            log_messages.append(f"LOG: Step 1 - Getting scrip_code for symbol {symbol} from company_table")
            cur = repo._conn.cursor()
            cur.execute(
                "SELECT scrip_code, sector FROM company_table WHERE symbol = ? LIMIT 1",
                (symbol,)
            )
            company_row = cur.fetchone()
            
            if not company_row:
                log_messages.append(f"LOG: No company found in company_table for symbol {symbol}")
                continue
                
            target_scrip_code = company_row[0]
            target_sector = company_row[1]
            
            log_messages.append(f"LOG: Found scrip_code {target_scrip_code} and sector {target_sector} for symbol {symbol}")
            
            # Step 2: Get annual sales from annual_table using scrip_code
            log_messages.append(f"LOG: Step 2 - Getting annual data for scrip_code {target_scrip_code} from annual_table")
            target_annual = repo.get_latest_annual_data(target_scrip_code)
            if not target_annual or 'sales' not in target_annual:
                log_messages.append(f"LOG: No annual data found for scrip_code {target_scrip_code}")
                continue
                
            target_sales_raw = float(target_annual['sales'])
            target_level = target_annual.get('level_of_rounding', '')
            target_sales_normalized = normalize_sales_value(target_sales_raw, target_level)
            
            log_messages.append(f"LOG: Found sales data - raw: {target_sales_raw}, level: {target_level}, normalized: {target_sales_normalized}")
            
            # Step 3: Calculate sales range (±15%) on normalized values
            min_sales_normalized = target_sales_normalized * 0.00  # -35%
            max_sales_normalized = target_sales_normalized * 10.00  # +35%
            
            log_messages.append(f"LOG: Calculated sales range for {symbol}: {min_sales_normalized} to {max_sales_normalized} rupees")
            
            # Step 4: Get all companies in the same sector
            log_messages.append(f"LOG: Step 4 - Finding all companies in sector {target_sector}")
            cur = repo._conn.cursor()
            cur.execute(
                "SELECT symbol, scrip_code, company_name FROM company_table WHERE sector = ?",
                (target_sector,)
            )
            sector_companies = cur.fetchall()
            
            log_messages.append(f"LOG: Found {len(sector_companies)} companies in sector {target_sector}")
            
            # Step 5: Filter companies whose latest sales fall within range
            log_messages.append(f"LOG: Step 5 - Filtering companies by sales range")
            peer_candidates = []
            
            for company_row in sector_companies:
                company_symbol = company_row[0]
                company_scrip = company_row[1]
                company_name = company_row[2]
                
                # Skip the target company itself
                if company_symbol == symbol or company_scrip == target_scrip_code:
                    log_messages.append(f"LOG: Skipping target company {company_symbol} ({company_scrip})")
                    continue
                
                # Get latest annual data for this company using scrip_code
                company_annual = repo.get_latest_annual_data(company_scrip)
                if not company_annual or 'sales' not in company_annual:
                    log_messages.append(f"LOG: No annual data found for peer candidate {company_symbol} ({company_scrip})")
                    continue
                
                company_sales_raw = float(company_annual['sales'])
                company_level = company_annual.get('level_of_rounding', '')
                company_sales_normalized = normalize_sales_value(company_sales_raw, company_level)
                
                log_messages.append(f"LOG: Checking peer candidate {company_symbol}: sales={company_sales_raw} {company_level} = {company_sales_normalized} rupees")
                
                # Check if normalized sales fall within range
                if min_sales_normalized <= company_sales_normalized <= max_sales_normalized:
                    peer_info = {
                        "company": company_name,
                        "symbol": company_symbol,
                        "scrip_code": company_scrip,
                        "industry": target_sector,
                        "sales": company_sales_raw,  # Keep original value for display
                        "level_of_rounding": company_level,  # Keep denomination info
                        "normalized_sales": company_sales_normalized  # Include normalized value
                    }
                    peer_candidates.append(peer_info)
                    log_messages.append(f"LOG: ✓ Added peer: {company_symbol} (sales within range)")
                else:
                    log_messages.append(f"LOG: ✗ Rejected peer: {company_symbol} (sales outside range)")
            
            # Step 6: Limit to top 5 peers by sales proximity to target
            if len(peer_candidates) > 5:
                log_messages.append(f"LOG: Step 6 - Limiting to top 5 peers by sales proximity")
                # Sort by sales proximity to target (normalized)
                peer_candidates.sort(key=lambda x: abs(x['normalized_sales'] - target_sales_normalized))
                peers_result[symbol] = peer_candidates[:5]
                log_messages.append(f"LOG: Selected top 5 peers for {symbol}")
            else:
                peers_result[symbol] = peer_candidates
                log_messages.append(f"LOG: Selected all {len(peer_candidates)} peers for {symbol}")
            
            log_messages.append(f"LOG: Completed peer extraction for {symbol}: found {len(peers_result[symbol])} peers")
            
        except Exception as e:
            log_messages.append(f"LOG: Error getting peers for {symbol}: {str(e)}")
            continue
    
    repo.close()
    log_messages.append(f"LOG: Peer extraction completed for all symbols")
    
    # Join all log messages with newlines
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
        "- **statement_frequency**: 'quarterly', 'annual', or 'unspecified'.\n"
        "- **statement_type**: 'balance_sheet', 'cash_flow', 'income_statement', 'ratios', or 'unspecified'.\n"
        "- **period**: Specific period like 'latest quarter', 'Q3 2023', or 'unspecified'.\n"
        "- **target_companies**: List of company names mentioned.\n"
        "- **industries**: Any industries mentioned.\n"
        "- **other_requirements**: Any other specific requirements or questions.\n"
        "- **get_peer**: Set to true if the query requires peer company analysis/comparison, false otherwise.\n\n"
        "Then, based on the breakdown, generate a structured JSON response identifying target companies.\n"
        "If get_peer is true, the system will automatically fetch appropriate peers from the database.\n"
        "Ensure scrip_codes are accurate BSE codes.\n\n"
        "Return strictly valid JSON with no additional text.\n\n"
        "JSON Schema:\n"
        "{\n"
        "  \"intent\": {\n"
        "    \"statement_frequency\": \"string\",\n"
        "    \"statement_type\": \"string\",\n"
        "    \"period\": \"string\",\n"
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


def generate_answer_from_data(query: str, data: Dict[str, Any], statement_type: str, frequency: str) -> str:
    """Use LLM to generate an answer based on the query and fetched data."""
    system_prompt = f"""
You are a Senior Financial Analyst creating a comprehensive, detailed research report. Based on the user's query and provided financial data, generate an extensive analysis report in Markdown format.

Always structure your response as a professional financial report with:

# Report Title including the period and statement type (e.g., "Q3 2023 Income Statement Analysis")

## Executive Summary
Brief overview of the company's financial position 

## Financial Performance Overview
Present key financial metrics in a well-formatted table

## Detailed Analysis
- Revenue and profitability analysis
- Cost structure breakdown
- Margin analysis
- Tax efficiency
- EPS and shareholder returns

## Key Financial Ratios and Metrics
Calculate and interpret important ratios (where data allows):
- Profit margins
- Return on assets/equity
- Debt ratios
- Efficiency ratios

## Comparative Analysis
If multiple companies are included, provide detailed comparisons

## Strengths and Weaknesses
SWOT-style analysis based on financial data

## Industry Context and Positioning
Place the company's performance in industry context

## Future Outlook and Recommendations
Insights on growth prospects and investment considerations

Use {frequency} data for {statement_type.replace('_', ' ')} analysis. Include all available companies and metrics. Make the report as detailed and comprehensive as possible, using professional financial analysis language.

CRITICAL: Do not invent, extrapolate, or generate mock historical data. Only use the financial data provided in the input. If historical data is requested but not available in the provided data, clearly state that only current/latest data is available and cannot provide historical trends or CAGR calculations without historical data.
For historical data queries, the data is provided as arrays of records under each company. Use this to create trend tables and calculate actual CAGRs where possible. If only one data point is available, note the limitation.
Format the response in clean Markdown with tables, headers, and structured sections. Use proper formatting for numbers (crores, millions, etc.). If data is missing for some companies, note that and focus on available data.
Return only the Markdown report content, no additional explanations outside the report structure.
"""

    user_prompt = f"Query: {query}\n\nFinancial Data (JSON format - for historical queries, data is provided as arrays of records):\n{json.dumps(data, indent=2)}"

    response = _invoke_llm(system_prompt, user_prompt, max_tokens=2500)
    normalized = _normalize_llm_response(response)
    return normalized.get("content", "No answer generated.")
