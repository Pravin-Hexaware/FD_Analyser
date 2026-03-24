from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

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


def analyze_target_companies_from_query(query: str) -> Dict[str, Any]:
    """Use Azure LLM to parse financial target companies + peers into a JSON schema."""
    if not query or not query.strip():
        raise ValueError("Query must not be empty.")

    system_prompt = (
        "You are a Senior Financial Analyst and Data Extraction Expert specializing in "
        "parsing financial queries, identifying listed companies, validating market identifiers, "
        "and structuring data for XBRL-based extraction.\n\n"

        "## Task:\n"
        "Parse the user query to extract the financial intent and identify all relevant companies, "
        "including their stock symbols, scrip codes, and industries, along with peers from the same industry.\n\n"

        "## Input Variables:\n"
        f"- **query**: {query}\n\n"

        "## Requirements:\n"
        "- Identify the **statement_frequency**: 'quarterly', 'annual', or 'unspecified'.\n"
        "- Identify the **statement_type**: 'balance_sheet', 'cash_flow', 'income_statement', 'ratios', or 'unspecified'.\n"
        "- Identify the **period**: such as 'latest quarter', 'Q3 2023', or 'unspecified'.\n"
        "- For each target company:\n"
        "  - Include the **company name**, **symbol**, **industry**, and **accurate scrip_code**.\n"
        "  - Include **exactly 3 peers** from the same industry.\n"
        "- For each peer:\n"
        "  - Include **company name**, **symbol**, **industry**, and **accurate scrip_code**.\n"
        "- Always return strictly valid JSON with *no explanation or additional text*.\n"
        "- The scrip_code must be accurate and correspond to the correct BSE listing.\n\n"

        "## Output Format:\n"
        "Return the data as a valid JSON object using the schema below.\n\n"

        "### JSON Schema:\n"
        """
        {
          "intent": {
            "statement_frequency": "quarterly | annual | unspecified",
            "statement_type": "balance_sheet | cash_flow | income_statement | ratios | unspecified",
            "period": "string or unspecified"
          },
          "target_companies": {
            "1": {
              "company": "company_name",
              "symbol": "company_symbol",
              "scrip_code": "company_scrip_code",
              "industry": "company_industry",
              "peers": {
                "1": {
                  "company": "peer_company_name",
                  "symbol": "peer_company_symbol",
                  "scrip_code": "peer_company_scrip_code",
                  "industry": "peer_company_industry"
                },
                "2": {
                  "company": "peer_company_name",
                  "symbol": "peer_company_symbol",
                  "scrip_code": "peer_company_scrip_code",
                  "industry": "peer_company_industry"
                },
                "3": {
                  "company": "peer_company_name",
                  "symbol": "peer_company_symbol",
                  "scrip_code": "peer_company_scrip_code",
                  "industry": "peer_company_industry"
                }
              }
            }
          }
        }
        """
    )

    response = _invoke_llm(system_prompt, "", max_tokens=600)  # Combined prompt, empty user_prompt
    normalized = _normalize_llm_response(response)
    text = normalized.get("content", "")

    # Try strict JSON parse first and fallback to substring extraction.
    parsed: Dict[str, Any] = {}
    try:
        parsed = json.loads(text)
    except Exception:
        # extract JSON object between first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                parsed = json.loads(candidate)
            except Exception:
                parsed = {
                    "error": "LLM output is not valid JSON",
                    "raw_output": text,
                }
        else:
            parsed = {
                "error": "LLM output does not contain JSON object",
                "raw_output": text,
            }

    return {
        "query": query,
        "parsed": parsed,
        "raw_llm_response": normalized,
    }
