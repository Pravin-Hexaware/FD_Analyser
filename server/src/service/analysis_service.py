from __future__ import annotations

import json
import re
import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from repository.sqlite_repository import SqliteRepository
from utils.llm_testing import get_azure_chat_openai
from service.nlp_company_extractor import parse_query_and_get_companies_nlp

_LLM: Any = None

HARDCODED_PEERS: Dict[str, List[str]] = {
    "reliance": ["ioc", "ongc"],
    "ioc": ["reliance", "bpcl"],
    "ongc": ["coalindia", "ioc"],
    "bpcl": ["reliance", "ongc"],
    "coalindia": ["ongc", "reliance"],
    "techm": ["lti", "hcltech"],
    "tcs": ["infy", "wipro"],
    "infy": ["tcs", "wipro"],
    "wipro": ["infy","hcltech"],
     "hcltech": ["tcs", "infy"],
     "ltim": ["wipro","hcltech"],
     "ofss": ["tcs","hcltech"],
    "hext":["coforge","ltim"],
    "coforge":["hext","ltim"],
    "ultracemco":["lt","vbl"],
    "lt": ["ultracemco", "vbl"],
    "vbl": ["ultracemco", "lt"],
    "idea": ["tatacomm", "bhartiartl"],
    "tatacomm": ["idea", "bhartiartl"],
    "bhartiartl": ["idea", "tatacomm"],
    "HINDUNILVR":["godrejcp","dabur"],
    "godrejcp":["HINDUNILVR","dabur"],
    "dabur":["HINDUNILVR","godrejcp"],
    "lici":["sbilife","hdfclife"],
    "sbilife":["lici","icicpruli"],
    "hdfclife":["lici","icicpruli"],
    "icicpruli":["hdfclife","sbilife"],
    "sunpharma": ["DIVISLAB", "drreddy"],
    "cipla": ["sunpharma", "drreddy"],
    "drreddy": ["sunpharma", "cipla"],
    "divislab": ["sunpharma", "cipla"],
    "maruti":["m&m","tvsmotor"],
    "eichermot":["bajaj-auto","tvsmotor"],
    "m&m": ["maruti", "tvsmotor"],
    "tvsmotor": ["maruti", "eichermot"],
    "itc":["vstind"],
    "vstind": ["itc"],
    "ntpc":["adanipower","powergrid"],
    "powergrid": ["ntpc","adanipower"],
    "adanipower": ["ntpc","powergrid"],
    "adaniports": ["jswinfra","gppl"],
    "jswinfra": ["adaniports","gppl"],
    "gppl": ["adaniports","jswinfra"],
    "bel":["hal","bdl"],
    "datapattns":["bdl","bel"],
    "hal": ["bel","bdl"],
    "bdl": ["bel","hal"],
    "bajajfinsv":["bfinvest","bajajhldng"],
    "bfinvest": ["bajajfinsv","bajajhldng"],
    "bajajhldng": ["bajajfinsv","bfinvest"],
    "jswsteel":["tatasteel","jindalstel"],
    "tatasteel": ["jswsteel","jindalstel"],
    "jindalstel": ["jswsteel","tatasteel"],
    "vedl":["coalindia","nmdc"],
    "nmdc": ["coalindia","vedl"],
    "axisbank": ["hdfcbank", "icicibank"],
    "hdfcbank": ["axisbank", "sbin"],
    "icicibank": [ "kotakbank", "sbin"],
    "kotakbank": [ "hdfcbank", "icicibank"],
    "sbin": ["axisbank", "hdfcbank"]
}


def _get_hardcoded_peers(symbol: str) -> Optional[List[str]]:
    normalized = symbol.strip().lower() if symbol else ""
    peers = HARDCODED_PEERS.get(normalized)
    if peers:
        return [peer.upper() for peer in peers]
    return None



def _get_company_info_by_symbol(repo: SqliteRepository, symbol: str) -> Dict[str, Any]:
    """Get company info from database by symbol."""
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

def _normalize_company_folder_name(company_name: str) -> str:
    if not company_name:
        return "UNKNOWN_COMPANY"
    normalized = company_name.strip().upper().replace("&", "AND")
    normalized = re.sub(r"[^A-Z0-9_]", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "UNKNOWN_COMPANY"

def _get_today_news_summary(company_name: Optional[str]) -> Optional[str]:
    """Fetch today's cached news markdown for a company from markdown folder.
    
    Searches for: markdown/{company_name}/{YYYYMMDD}/
    Returns raw article markdown from up to 3 files if available.
    Falls back to summary.md only when article files are missing.
    """
    if not company_name:
        return None

    try:
        today = datetime.now().strftime("%Y%m%d")
        src_dir = Path(__file__).resolve().parents[1]
        markdown_base = src_dir / "markdown"
        safe_company_name = _normalize_company_folder_name(company_name)
        company_date_folder = markdown_base / safe_company_name / today

        if company_date_folder.exists():
            article_files = [
                path for path in sorted(company_date_folder.glob("*.md"))
                if path.name.lower() != "summary.md"
            ][:5]

            if article_files:
                contents = []
                for path in article_files:
                    with open(path, 'r', encoding='utf-8') as f:
                        contents.append(f.read().strip())
                return "\n\n".join(contents)

            summary_path = company_date_folder / "summary.md"
            if summary_path.exists() and summary_path.is_file():
                with open(summary_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()

    except Exception as e:
        print(f"[DEBUG] Error reading markdown news for {company_name}: {str(e)}")

    return None


async def _fetch_news_using_agent(company_name: str, max_results: int = 3) -> Optional[str]:
    """Fetch recent company news URLs with the agent and convert them to markdown text."""
    try:
        from api.service.news_agent_service import app as news_agent_app, process_results
        from langchain_core.messages import HumanMessage
    except Exception as e:
        print(f"[WARN] Agent news fetch unavailable: {e}")
        return None

    try:
        query = (
            f"Collect up to 3 recent news articles for {company_name}. "
            "Return only relevant article URLs, titles, published dates if available, and reasons in strict JSON."
        )
        result = news_agent_app.invoke(
            {"messages": [HumanMessage(content=query)]},
            config={"configurable": {"thread_id": f"news-agent-{uuid.uuid4()}"}}
        )

        if not result or "messages" not in result:
            print(f"[WARN] Agent did not return messages for {company_name}")
            return None

        output_message = result["messages"][-1].content
        article_paths = process_results(output_message, company_name=company_name)
        if not article_paths:
            print(f"[WARN] Agent returned no article paths for {company_name}")
            return None

        contents = []
        for path in article_paths:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    contents.append(f.read().strip())
            except Exception as read_exc:
                print(f"[WARN] Failed to read scraped article {path}: {read_exc}")
                continue

        return "\n\n".join(contents) if contents else None

    except Exception as e:
        print(f"[WARN] Agent news fetch failed for {company_name}: {e}")
        return None


async def _get_or_fetch_today_news_summary(company_name: Optional[str], scrip_code: Optional[str] = None) -> Optional[str]:
    """
    Fetch today's raw news markdown from the cache or scrape it on-demand.
    
    Searches for: markdown/{company_name}/{YYYYMMDD}/
    where {YYYYMMDD} is today's date.
    If the date folder already contains markdown files, it returns up to 3 of them.
    Otherwise it fetches article URLs and scrapes raw markdown content to the folder.
    """
    if not company_name:
        return None

    try:
        today = datetime.now().strftime("%Y%m%d")
        src_dir = Path(__file__).resolve().parents[1]
        markdown_base = src_dir / "markdown"
        safe_company_name = _normalize_company_folder_name(company_name)
        company_date_folder = markdown_base / safe_company_name / today

        # If today's date folder already contains markdown article files, return them.
        if company_date_folder.exists():
            article_files = [
                path for path in sorted(company_date_folder.glob("*.md"))
                if path.name.lower() != "summary.md"
            ][:4]
            if article_files:
                contents = []
                for path in article_files:
                    with open(path, 'r', encoding='utf-8') as f:
                        contents.append(f.read().strip())
                print(f"[INFO] Using cached markdown articles for {company_name}")
                return "\n\n".join(contents)

            summary_file = company_date_folder / "summary.md"
            if summary_file.exists() and summary_file.is_file():
                with open(summary_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    print(f"[INFO] Using fallback cached summary for {company_name}")
                    return content

        print(f"[INFO] No cached markdown articles for {company_name}, attempting agent-based collection...")

        # Only agent-based news collection is allowed here.
        agent_news = await _fetch_news_using_agent(company_name, max_results=4)
        if agent_news:
            print(f"[INFO] Agent news collection succeeded for {company_name}")
            return agent_news

        print(f"[WARN] Agent news collection failed or returned no articles for {company_name}. No legacy NewsService fallback will be used.")
        return None

    except Exception as e:
        print(f"[ERROR] Error in _get_or_fetch_today_news_summary: {str(e)}")
        return None


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
    #
    # if not company_name:
    #     return {"symbol": "", "scrip_code": None, "company": "", "industry": None}
    #
    # normalized_name = company_name.strip().lower()
    # cur = repo._conn.cursor()
    # cur.execute(
    #     "SELECT symbol, scrip_code, company_name, sector FROM company_table WHERE LOWER(company_name) = ? LIMIT 1",
    #     (normalized_name,),
    # )
    # row = cur.fetchone()
    # if not row:
    #     cur.execute(
    #         "SELECT symbol, scrip_code, company_name, sector FROM company_table WHERE LOWER(company_name) LIKE ? LIMIT 1",
    #         (f"%{normalized_name}%",),
    #     )
    #     row = cur.fetchone()
    # if not row:
    #     return {"symbol": "", "scrip_code": None, "company": company_name, "industry": None}
    # return {
    #     "symbol": row[0],
    #     "scrip_code": row[1],
    #     "company": row[2],
    #     "industry": row[3],
    # }


def _build_peer_list_from_hardcoded(repo: SqliteRepository, symbol: str) -> List[Dict[str, Any]]:
    peer_symbols = _get_hardcoded_peers(symbol)
    if not peer_symbols:
        return []

    peers = []
    for peer_symbol in peer_symbols:
        peer_info = _get_company_info_by_symbol(repo, peer_symbol)
        peers.append(peer_info)
    return peers


def initialize_llm() -> None:
    """Initialize the AzureChatOpenAI instance once at application startup."""
    global _LLM,_LLM_ID
    if _LLM is None:

        _LLM = get_azure_chat_openai()
        _LLM_ID = str(uuid.uuid4())
        print(f"🔥 LLM CREATED (startup) → ID: {_LLM_ID}, Memory: {id(_LLM)}")
        if _LLM is None:
            raise RuntimeError("Failed to initialize AzureChatOpenAI from utils.llm_testing")


def _get_llm() -> Any:
    """Return a cached AzureChatOpenAI instance (or create it)."""
    global _LLM,_LLM_ID
    if _LLM is None:
        _LLM = get_azure_chat_openai()
        _LLM_ID = str(uuid.uuid4())
        print(f"🔥 LLM CREATED (Fallback) → ID: {_LLM_ID}, Memory: {id(_LLM)}")
        if _LLM is None:
            raise RuntimeError("Failed to initialize AzureChatOpenAI from utils.llm_testing")
    else:
        print(f"♻️ LLM REUSED: ID: {_LLM_ID}, Memory: {id(_LLM)}")
    return _LLM


def get_llm_id():
    return _LLM_ID

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


def _invoke_llm(system_prompt: str, user_prompt: str, max_tokens: int = 8000) -> Any:
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


def _extract_chunk_text(chunk: Any) -> str:
    """Extract text content from an LLM streaming chunk."""
    if chunk is None:
        return ""
    content = getattr(chunk, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                elif "content" in item:
                    parts.append(str(item["content"]))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _build_llm_prompts(query: str, formatted_data: Any, statement_type: str, frequency: str, news_context: Optional[str] = None) -> tuple[str, str]:
    """Build system and user prompts for the LLM."""
    system_prompt = f"""
You are a Senior Financial Analyst and Strategic Advisor preparing comprehensive, institutional-grade financial analysis reports for C-suite executives, board members, institutional investors, and senior financial representatives. Your reports must be rigorous, data-driven, and provide deep strategic insights that inform critical business decisions.

Generate a complete, exhaustive financial analysis report in Markdown format WITHOUT ANY TRUNCATION OR LENGTH RESTRICTIONS. The report should comprehensively analyze ALL available financial data, metrics, parameters, textual information, AND RECENT NEWS PROVIDED in the input - not just a subset.

## CRITICAL: NEWS FEEDS ARE PRIMARY ANALYTICAL INPUT
You MUST use the provided recent news and market developments as a PRIMARY ANALYTICAL TOOL, not supplementary context. The news feeds are essential for:

1. **Understanding Financial Performance Drivers**: Correlate financial metrics with recent company events. For example:
   - If news mentions new contracts/partnerships → expect revenue growth
   - If news mentions cost-cutting initiatives → expect margin improvements
   - If news mentions acquisitions → expect changes in asset base and profitability
   - If news mentions regulatory issues → assess financial impact and risk

2. **Identifying Trends and Inflection Points**: Use news to explain acceleration/deceleration in financial metrics across periods

3. **Risk Assessment**: News about lawsuits, investigations, regulatory probes, leadership changes, or market disruptions directly impact financial risk profile

4. **Forward-Looking Insights**: News about strategic initiatives, R&D investments, market expansion, and technology adoption inform growth trajectory

5. **Valuation Context**: Recent developments provide context for P/E multiples, market positioning, and competitive advantage sustainability

### MANDATORY News Integration Requirements:
- **Executive Summary**: Lead with key news developments and their financial implications
- **Company Overview**: Use news to explain business model changes and strategic pivots
- **Strategic Context**: Analyze how recent news shapes competitive positioning
- **Performance Analysis**: For each metric trend, explain whether news provides supporting context
- **Risk Assessment**: Prominently feature risks identified in recent news
- **Strategic Implications**: Ground recommendations in recent developments and their impact
- **Forward Outlook**: Use news to project future financial trajectory

PROMINENTLY FEATURE news-based insights throughout the report. Explain explicit causal relationships between recent developments and observed financial performance. Do not relegates news to a separate section—integrate it deeply into every analytical dimension.

## CRITICAL: TEXTUAL INFORMATION AND NOTES
The provided data includes TEXTUAL INFORMATION sections with financial notes, auditor remarks, management commentary, qualification statements, and other narrative disclosures. These are ESSENTIAL to include in your analysis as they provide critical context for understanding:
- Audit qualifications or modifications to audit opinions
- Management disclosure notes explaining financial performance
- Regulatory compliance information
- Special circumstances affecting financial results
- Risk disclosures and material contingencies
- Related party transaction disclosures
- Any caveats or limitations on financial results

Extract and prominently feature ALL textual information and narrative disclosures in your analysis. Do not omit or minimize these contextual notes - they are often more important than raw numbers.

Extract and analyze every relevant financial metric, trend, ratio, and insight from the complete dataset. Do not limit analysis to predefined metrics - dynamically identify and analyze all key financial indicators present in the data. Include all footnotes, explanations, and textual annotations.

The report should be extremely detailed and thorough, suitable for board-level strategic discussions, investment committee reviews, and executive decision-making. LENGTH IS NOT A CONSTRAINT - provide exhaustive, complete analysis without any truncation.

# Comprehensive Financial Analysis Report

## I. Executive Summary
Provide a comprehensive executive overview synthesizing key findings across all periods and companies:
- Strategic financial performance highlights and trajectory
- Critical profitability, efficiency, and growth metrics
- Major risk indicators and opportunities
- Strategic implications for business direction and governance
- Key recommendations for immediate executive attention
- Material qualifications, audit findings, or management disclosures

## II. Company Overview and Strategic Context
For each company analyzed:
- Business model and industry positioning
- Strategic objectives and market dynamics
- Key value drivers and competitive advantages
- Regulatory and macroeconomic context implications
- Any material management disclosures or special circumstances

## III. Comprehensive Financial Performance Analysis
Conduct exhaustive period-by-period and cross-company analysis of ALL financial metrics available:

### Revenue Analysis
- Detailed revenue composition and sources
- Revenue growth drivers and sustainability
- Geographic and segment revenue breakdown (if available)
- Revenue quality indicators and recurring vs. one-time components
- Management commentary on revenue performance

### Profitability Deep Dive
- Operating profit margins: Trends, drivers, and sustainability
- Net profit margins: Components and influencing factors
- EBITDA margins and operating efficiency metrics
- Gross margins by business segment or product line
- Margin drivers and sustainability factors
- Management notes on profitability

### Cost Structure Analysis
- Detailed cost breakdown: Fixed vs. variable costs
- Major expense categories: Personnel, R&D, marketing, administrative
- Cost optimization opportunities and efficiency trends
- Cost-to-revenue ratios and benchmarking
- Root causes of cost variations

### Balance Sheet Analysis
- Asset quality and composition
- Liability structure and debt management
- Working capital efficiency and cash conversion cycles
- Capital structure optimization and financial leverage
- Management commentary on balance sheet changes

### Cash Flow Analysis
- Operating cash flow generation and quality
- Investment and financing cash flows
- Free cash flow trends and utilization
- Cash flow forecasting implications
- Conversion efficiency from profit to cash

### Key Financial Ratios and Metrics
- Liquidity ratios: Current ratio, quick ratio, cash ratios
- Solvency ratios: Debt-to-equity, debt-to-assets, interest coverage
- Efficiency ratios: Asset turnover, inventory turnover, receivables days
- Profitability ratios: ROA, ROE, ROCE, EPS trends
- Valuation metrics and peer benchmarking

## IV. Audit Findings, Qualifications & Management Disclosures
CRITICAL SECTION - Include ALL:
- Audit opinion qualifications or modifications
- Auditor reservations or concerns
- Management commentary on audit findings
- Going concern assessments
- Related party transactions and related management disclosures
- Material contingencies or uncertain liabilities
- Regulatory compliance matters
- Any other material management notes or explanations

## V. Trend Analysis and Forecasting Insights
- Multi-period trend analysis with statistical significance
- Growth acceleration/deceleration patterns
- Cyclical vs. structural performance changes
- Forward-looking indicators from historical trends
- Sustainability of observed trends

## VI. Comparative Analysis
- Peer group comparisons across all metrics
- Industry benchmarking and positioning
- Competitive advantages and disadvantages
- Market share and growth relative to peers
- Relative financial health assessment

## VII. Risk Assessment and Mitigation
- Financial risk factors: Liquidity, solvency, currency, interest rate
- Operational risks: Cost pressures, margin compression, supply chain
- Market risks: Competition, demand fluctuations, regulatory changes
- Strategic risks: Market positioning, technology disruption, M&A implications
- Quantitative risk metrics and stress testing insights
- Disclosed management concerns and risk factors

## VIII. Strategic Implications and Recommendations
- Strategic opportunities identified from financial trends
- Areas requiring management intervention
- Capital allocation recommendations
- Risk mitigation strategies
- Governance and compliance considerations
- Long-term value creation strategies

## IX. Data Quality and Limitations
- Assessment of data completeness and reliability
- Missing data impacts on analysis
- Assumptions and estimation methodologies used
- Audit qualifications or any hedges on financial reliability
- Recommendations for improved financial reporting

## X. Appendices
- Detailed financial statements and schedules
- Ratio calculations and trend charts
- Peer comparison tables
- Statistical analysis and regression insights
- Complete text of all management disclosures and audit findings

---

**Analysis Parameters:** {frequency} financial statements | Focus: {statement_type.replace('_', ' ')} | Data Scope: EXHAUSTIVE analysis of ALL available financial parameters and narrative disclosures

**CRITICAL REQUIREMENTS:**
1. Analyze EVERY financial metric, parameter, and textual information present - DO NOT OMIT ANYTHING
2. PROMINENTLY FEATURE all audit findings, qualifications, management notes, and disclosures
3. Provide exhaustive, board-level analysis with strategic implications - NO TRUNCATION
4. Use precise numerical references with proper formatting (INR crores/lakhs, percentages, ratios)
5. Identify trends, drivers, risks, and opportunities across ALL data dimensions
6. Maintain professional, executive-level tone suitable for C-suite and board presentations
7. Include ALL contextual information from textual sections - do not minimize or omit
8. Generate actionable insights that drive strategic decision-making
9. Structure report for easy navigation while maintaining complete depth
10. Include quantitative analysis with statistical context where applicable
11. Provide forward-looking strategic recommendations based on historical trends
12. Do NOT artificially limit the report length - provide complete, exhaustive analysis
    """

    user_prompt_parts = [
        f"Query: {query}",
        f"\nFinancial Data (JSON format - for historical queries, data is provided as arrays of records):\n{json.dumps(formatted_data, indent=2)}"
    ]
    
    if news_context:
        user_prompt_parts.append(f"\n\n## RECENT NEWS AND MARKET DEVELOPMENTS (PRIMARY ANALYTICAL INPUT)\n\nUse this recent news to contextualize and explain financial metrics. These developments ARE the key drivers behind the observed financial performance:\n\n{news_context}\n\n**INSTRUCTIONS**: \n1. For each major news item, identify its expected financial impact\n2. Correlate news timing with financial metric changes\n3. Assess how news affects risk profile, growth trajectory, and valuation\n4. Explain whether financial results align with news-driven expectations\n5. Use news to project future financial performance and identify leading indicators\n6. Integrate news insights throughout the analysis, not in a separate section")
    else:
        user_prompt_parts.append("\n\nNOTE: No recent news data available for this analysis. Proceed with financial data analysis only.")
    
    user_prompt = "\n".join(user_prompt_parts)
    return system_prompt, user_prompt


def stream_answer_from_data(query: str, data: Dict[str, Any], statement_type: str, frequency: str, news_context: Optional[str] = None) -> Iterator[str]:
    """Stream answer chunks from the LLM using AzureChatOpenAI streaming."""
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
        if "publication_date" in formatted_data:
            formatted_data["Period"] = _format_period_from_publication_date(
                formatted_data.get("publication_date")
            )

    system_prompt, user_prompt = _build_llm_prompts(query, formatted_data, statement_type, frequency, news_context)
    llm = _get_llm()

    for chunk in llm.stream(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        max_tokens=8000,
    ):
        text = _extract_chunk_text(chunk)
        if text:
            yield text


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

            normalized_symbol = symbol.strip().lower() if symbol else ""
            hardcoded_peer_symbols = _get_hardcoded_peers(normalized_symbol)
            if hardcoded_peer_symbols:
                log_messages.append(f"LOG: Hardcoded peer symbols found for input symbol '{symbol}': {hardcoded_peer_symbols}")
                peer_list = []
                for peer_symbol in hardcoded_peer_symbols:
                    peer_info = _get_company_info_by_symbol(repo, peer_symbol)
                    peer_info["peer_source"] = "hardcoded"
                    peer_list.append(peer_info)
                peers_result[request_key] = peer_list
                log_messages.append(f"LOG: Returning hardcoded peers for request {request_key}: {[p['symbol'] for p in peer_list]}")
                continue

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

            # No sector-based peer finding; only use hardcoded peers
            log_messages.append(f"LOG: No hardcoded peers found for {target_symbol}, skipping peer extraction")
            continue

        except Exception as e:
            log_messages.append(f"LOG: Error getting peers for request {request_key}: {str(e)}")
            continue

    repo.close()
    log_messages.append("LOG: Peer extraction completed for all requests")

    full_log = "\n".join(log_messages)
    return peers_result, full_log


def parse_query_and_get_companies(query: str) -> Tuple[Dict[str, Any], str, str]:
    """Parse user query using NLP-based extraction (replacing LLM-based approach).
    
    This function now uses deterministic NLP pattern matching and fuzzy matching
    against the BSE company list instead of calling an expensive LLM service.
    
    If get_peer is true, automatically fetch peers from database based on sales range and sector.
    
    Returns:
        Tuple of (parsed_response, system_prompt_used, peer_extraction_log)
    """
    if not query or not query.strip():
        raise ValueError("Query must not be empty.")

    # Use NLP-based extraction instead of LLM
    parsed, system_prompt = parse_query_and_get_companies_nlp(query)
    
    # Check for extraction errors
    if parsed.get("error"):
        print(f"Query parsing error: {parsed.get('error')}")
        return parsed, system_prompt, ""
    
    peer_extraction_log = ""
    
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

    return parsed, system_prompt, peer_extraction_log



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


def generate_answer_from_data(query: str, data: Dict[str, Any], statement_type: str, frequency: str, news_context: Optional[str] = None) -> tuple[str, dict[str, int]]:
    """Use LLM to generate an answer based on the query and fetched data with optional news context.

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

Generate a complete, exhaustive financial analysis report in Markdown format WITHOUT ANY TRUNCATION OR LENGTH RESTRICTIONS. The report should comprehensively analyze ALL available financial data, metrics, parameters, textual information, AND RECENT NEWS PROVIDED in the input - not just a subset.

## CRITICAL: NEWS FEEDS ARE PRIMARY ANALYTICAL INPUT
You MUST use the provided recent news and market developments as a PRIMARY ANALYTICAL TOOL, not supplementary context. The news feeds are essential for:

1. **Understanding Financial Performance Drivers**: Correlate financial metrics with recent company events. For example:
   - If news mentions new contracts/partnerships → expect revenue growth
   - If news mentions cost-cutting initiatives → expect margin improvements
   - If news mentions acquisitions → expect changes in asset base and profitability
   - If news mentions regulatory issues → assess financial impact and risk

2. **Identifying Trends and Inflection Points**: Use news to explain acceleration/deceleration in financial metrics across periods

3. **Risk Assessment**: News about lawsuits, investigations, regulatory probes, leadership changes, or market disruptions directly impact financial risk profile

4. **Forward-Looking Insights**: News about strategic initiatives, R&D investments, market expansion, and technology adoption inform growth trajectory

5. **Valuation Context**: Recent developments provide context for P/E multiples, market positioning, and competitive advantage sustainability

### MANDATORY News Integration Requirements:
- **Executive Summary**: Lead with key news developments and their financial implications
- **Company Overview**: Use news to explain business model changes and strategic pivots
- **Strategic Context**: Analyze how recent news shapes competitive positioning
- **Performance Analysis**: For each metric trend, explain whether news provides supporting context
- **Risk Assessment**: Prominently feature risks identified in recent news
- **Strategic Implications**: Ground recommendations in recent developments and their impact
- **Forward Outlook**: Use news to project future financial trajectory

PROMINENTLY FEATURE news-based insights throughout the report. Explain explicit causal relationships between recent developments and observed financial performance. Do not relegates news to a separate section—integrate it deeply into every analytical dimension.

## CRITICAL: TEXTUAL INFORMATION AND NOTES
The provided data includes TEXTUAL INFORMATION sections with financial notes, auditor remarks, management commentary, qualification statements, and other narrative disclosures. These are ESSENTIAL to include in your analysis as they provide critical context for understanding:
- Audit qualifications or modifications to audit opinions
- Management disclosure notes explaining financial performance
- Regulatory compliance information
- Special circumstances affecting financial results
- Risk disclosures and material contingencies
- Related party transaction disclosures
- Any caveats or limitations on financial results

Extract and prominently feature ALL textual information and narrative disclosures in your analysis. Do not omit or minimize these contextual notes - they are often more important than raw numbers.

Extract and analyze every relevant financial metric, trend, ratio, and insight from the complete dataset. Do not limit analysis to predefined metrics - dynamically identify and analyze all key financial indicators present in the data. Include all footnotes, explanations, and textual annotations.

The report should be extremely detailed and thorough, suitable for board-level strategic discussions, investment committee reviews, and executive decision-making. LENGTH IS NOT A CONSTRAINT - provide exhaustive, complete analysis without any truncation.

# Comprehensive Financial Analysis Report

## I. Executive Summary
Provide a comprehensive executive overview synthesizing key findings across all periods and companies:
- Strategic financial performance highlights and trajectory
- Critical profitability, efficiency, and growth metrics
- Major risk indicators and opportunities
- Strategic implications for business direction and governance
- Key recommendations for immediate executive attention
- Material qualifications, audit findings, or management disclosures

## II. Company Overview and Strategic Context
For each company analyzed:
- Business model and industry positioning
- Strategic objectives and market dynamics
- Key value drivers and competitive advantages
- Regulatory and macroeconomic context implications
- Any material management disclosures or special circumstances

## III. Comprehensive Financial Performance Analysis
Conduct exhaustive period-by-period and cross-company analysis of ALL financial metrics available:

### Revenue Analysis
- Detailed revenue composition and sources
- Revenue growth drivers and sustainability
- Geographic and segment revenue breakdown (if available)
- Revenue quality indicators and recurring vs. one-time components
- Management commentary on revenue performance

### Profitability Deep Dive
- Operating profit margins: Trends, drivers, and sustainability
- Net profit margins: Components and influencing factors
- EBITDA margins and operating efficiency metrics
- Gross margins by business segment or product line
- Margin drivers and sustainability factors
- Management notes on profitability

### Cost Structure Analysis
- Detailed cost breakdown: Fixed vs. variable costs
- Major expense categories: Personnel, R&D, marketing, administrative
- Cost optimization opportunities and efficiency trends
- Cost-to-revenue ratios and benchmarking
- Root causes of cost variations

### Balance Sheet Analysis
- Asset quality and composition
- Liability structure and debt management
- Working capital efficiency and cash conversion cycles
- Capital structure optimization and financial leverage
- Management commentary on balance sheet changes

### Cash Flow Analysis
- Operating cash flow generation and quality
- Investment and financing cash flows
- Free cash flow trends and utilization
- Cash flow forecasting implications
- Conversion efficiency from profit to cash

### Key Financial Ratios and Metrics
- Liquidity ratios: Current ratio, quick ratio, cash ratios
- Solvency ratios: Debt-to-equity, debt-to-assets, interest coverage
- Efficiency ratios: Asset turnover, inventory turnover, receivables days
- Profitability ratios: ROA, ROE, ROCE, EPS trends
- Valuation metrics and peer benchmarking

## IV. Audit Findings, Qualifications & Management Disclosures
CRITICAL SECTION - Include ALL:
- Audit opinion qualifications or modifications
- Auditor reservations or concerns
- Management commentary on audit findings
- Going concern assessments
- Related party transactions and related management disclosures
- Material contingencies or uncertain liabilities
- Regulatory compliance matters
- Any other material management notes or explanations

## V. Trend Analysis and Forecasting Insights
- Multi-period trend analysis with statistical significance
- Growth acceleration/deceleration patterns
- Cyclical vs. structural performance changes
- Forward-looking indicators from historical trends
- Sustainability of observed trends

## VI. Comparative Analysis
- Peer group comparisons across all metrics
- Industry benchmarking and positioning
- Competitive advantages and disadvantages
- Market share and growth relative to peers
- Relative financial health assessment

## VII. Risk Assessment and Mitigation
- Financial risk factors: Liquidity, solvency, currency, interest rate
- Operational risks: Cost pressures, margin compression, supply chain
- Market risks: Competition, demand fluctuations, regulatory changes
- Strategic risks: Market positioning, technology disruption, M&A implications
- Quantitative risk metrics and stress testing insights
- Disclosed management concerns and risk factors

## VIII. Strategic Implications and Recommendations
- Strategic opportunities identified from financial trends
- Areas requiring management intervention
- Capital allocation recommendations
- Risk mitigation strategies
- Governance and compliance considerations
- Long-term value creation strategies

## IX. Data Quality and Limitations
- Assessment of data completeness and reliability
- Missing data impacts on analysis
- Assumptions and estimation methodologies used
- Audit qualifications or any hedges on financial reliability
- Recommendations for improved financial reporting

## X. Appendices
- Detailed financial statements and schedules
- Ratio calculations and trend charts
- Peer comparison tables
- Statistical analysis and regression insights
- Complete text of all management disclosures and audit findings

---

**Analysis Parameters:** {frequency} financial statements | Focus: {statement_type.replace('_', ' ')} | Data Scope: EXHAUSTIVE analysis of ALL available financial parameters and narrative disclosures

**CRITICAL REQUIREMENTS:**
1. Analyze EVERY financial metric, parameter, and textual information present - DO NOT OMIT ANYTHING
2. PROMINENTLY FEATURE all audit findings, qualifications, management notes, and disclosures
3. Provide exhaustive, board-level analysis with strategic implications - NO TRUNCATION
4. Use precise numerical references with proper formatting (INR crores/lakhs, percentages, ratios)
5. Identify trends, drivers, risks, and opportunities across ALL data dimensions
6. Maintain professional, executive-level tone suitable for C-suite and board presentations
7. Include ALL contextual information from textual sections - do not minimize or omit
8. Generate actionable insights that drive strategic decision-making
9. Structure report for easy navigation while maintaining complete depth
10. Include quantitative analysis with statistical context where applicable
11. Provide forward-looking strategic recommendations based on historical trends
12. Do NOT artificially limit the report length - provide complete, exhaustive analysis
    """

    # Build user prompt with financial data and optional news context
    user_prompt_parts = [
        f"Query: {query}",
        f"\nFinancial Data (JSON format - for historical queries, data is provided as arrays of records):\n{json.dumps(formatted_data, indent=2)}"
    ]
    
    # Add news context if available
    if news_context:
        user_prompt_parts.append(f"\n\n## RECENT NEWS AND MARKET DEVELOPMENTS (PRIMARY ANALYTICAL INPUT)\n\nUse this recent news to contextualize and explain financial metrics. These developments ARE the key drivers behind the observed financial performance:\n\n{news_context}\n\n**INSTRUCTIONS**: \n1. For each major news item, identify its expected financial impact\n2. Correlate news timing with financial metric changes\n3. Assess how news affects risk profile, growth trajectory, and valuation\n4. Explain whether financial results align with news-driven expectations\n5. Use news to project future financial performance and identify leading indicators\n6. Integrate news insights throughout the analysis, not in a separate section")
    else:
        user_prompt_parts.append("\n\nNOTE: No recent news data available for this analysis. Proceed with financial data analysis only.")
    
    user_prompt = "\n".join(user_prompt_parts)

    response = _invoke_llm(system_prompt, user_prompt, max_tokens=8000)

    token_usage = _extract_token_usage(response)
    normalized = _normalize_llm_response(response)
    return normalized.get("content", "No answer generated."), token_usage