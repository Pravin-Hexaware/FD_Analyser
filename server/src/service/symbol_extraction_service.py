"""Symbol extraction service using Azure OpenAI LLM.

This service uses the LLM configuration from llm_config to extract
company or stock symbols from user queries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
import json
import re

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


def _invoke_llm(system_prompt: str, user_prompt: str, max_tokens: int = 500) -> Any:
    """Invoke the LangChain AzureChatOpenAI model and return the raw response."""
    llm = _get_llm()
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


def _extract_symbols_from_response(content: str) -> Dict[str, str]:
    """Parse the LLM response to extract stock/company symbols with their names.
    
    The LLM is instructed to return symbols in a structured format.
    Returns a dictionary with symbols as keys and company names as values.
    """
    if not content:
        return {}
    
    symbols_dict: Dict[str, str] = {}
    
    # Try to parse as JSON
    try:
        # Find the first { and last } to extract JSON
        start_idx = content.find('{')
        if start_idx != -1:
            end_idx = content.rfind('}')
            if end_idx > start_idx:
                json_str = content[start_idx:end_idx + 1]
                data = json.loads(json_str)
                
                # Check if symbols is a dictionary (symbol: company_name pairs)
                if isinstance(data.get("symbols"), dict):
                    symbols_dict = data["symbols"]
    except (json.JSONDecodeError, ValueError):
        pass
    
    return symbols_dict


def extract_company_symbol(query: str) -> Tuple[Dict[str, str], Dict[str, Any], str]:
    """Extract company or stock symbols from a user query using LLM.
    
    This function uses an LLM to identify and extract company names and stock ticker symbols
    from the user's query. The LLM intelligently recognizes companies, handles spelling 
    variations, and returns properly formatted results.
    
    Args:
        query: User query string containing references to companies/stocks
        
    Returns:
        A tuple containing:
        - Dictionary with symbol as key and company name as value
        - Dictionary with LLM response metadata
        - Raw content from LLM response
    """
    if not query or not query.strip():
        raise ValueError("Query cannot be empty")
    
    system_prompt = """You are an expert financial analyst and stock market specialist.
Your task is to identify and extract all company names and their ACTUAL stock ticker symbols from user queries.

CRITICAL INSTRUCTIONS:
1. Identify all companies mentioned in the query
2. IMPORTANT: Return the ACTUAL stock exchange ticker symbols, not company name abbreviations
3. For Indian companies specifically:
   - Hexaware Technologies -> HEXT (NOT HEXAWARE)
   - Coforge Limited -> COFORGE
   - TCS -> TCS
   - Infosys -> INFY
   - Wipro -> WIPRO
   - HCL Technologies -> HCL
4. For international companies:
   - Apple -> AAPL
   - Microsoft -> MSFT
   - Google/Alphabet -> GOOGL
   - Amazon -> AMZN
   - Tesla -> TSLA
5. Handle spelling variations intelligently (e.g., "hexwear" -> HEXT, "coforg" -> COFORGE)
6. Return the data in JSON format with a "symbols" field
7. The symbols field should contain key-value pairs where key is the ACTUAL stock ticker symbol (uppercase) and value is the full company name

RESPONSE FORMAT:
Return a JSON object like this:
{
    "symbols": {
        "HEXT": "Hexaware Technologies Limited",
        "COFORGE": "Coforge Limited"
    }
}

Example for multiple companies:
{
    "symbols": {
        "AAPL": "Apple Inc.",
        "MSFT": "Microsoft Corporation",
        "HEXT": "Hexaware Technologies Limited"
    }
}

REMEMBER: Use the ACTUAL tradeable stock symbols from the stock exchange, not abbreviations of company names."""

    user_message = f"Extract company and stock symbols from this query:\n\n{query}"
    
    try:
        # Call the LLM
        llm_response = _invoke_llm(system_prompt, user_message, max_tokens=500)
        normalized_response = _normalize_llm_response(llm_response)
        raw_content = normalized_response.get("content", "")
        
        # Extract symbols from the response
        symbols_dict = _extract_symbols_from_response(raw_content)
        
        return symbols_dict, normalized_response, raw_content
        
    except Exception as e:
        raise RuntimeError(f"Error extracting symbols from LLM: {str(e)}")
