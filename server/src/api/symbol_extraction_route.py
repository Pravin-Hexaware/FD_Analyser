

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from service.symbol_extraction_service import extract_company_symbol

router = APIRouter()


class SymbolExtractionRequest(BaseModel):
    """Request model for symbol extraction endpoint."""
    query: str


class SymbolExtractionResponse(BaseModel):
    """Response model for symbol extraction endpoint."""
    symbols: Dict[str, str]  # Key: symbol, Value: company name


@router.post("/extract-symbol", response_model=SymbolExtractionResponse)
async def extract_symbol_from_query(request: SymbolExtractionRequest):
    """Extract company or stock symbols from a user query.
    
    This endpoint accepts a user chat query and uses an LLM to identify
    and extract any company or stock symbols mentioned in the query.
    
    Args:
        request: SymbolExtractionRequest containing the user query
        
    Returns:
        SymbolExtractionResponse with symbols and company names as key-value pairs
        
    Example:
        Request: {"query": "What is the revenue of Apple and Microsoft?"}
        Response: {"symbols": {"AAPL": "Apple Inc.", "MSFT": "Microsoft Corporation"}}
    """
    try:
        if not request.query or not request.query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")
        
        symbols_dict, llm_response, raw_content = extract_company_symbol(request.query)
        
        return SymbolExtractionResponse(
            symbols=symbols_dict
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
