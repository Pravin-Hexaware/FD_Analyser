from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from service.symbol_extraction_service import extract_company_symbol
from service.peer_company_service import get_peer_companies

router = APIRouter()


class PeerInfo(BaseModel):
    """Model for peer company information."""
    name: str
    symbol: str


class ExtractedCompany(BaseModel):
    """Model for extracted company information."""
    symbol: str
    name: str


class CompanyWithPeersResponse(BaseModel):
    """Response model combining symbol extraction and peer companies."""
    query: str
    extracted_companies: List[ExtractedCompany]
    companies_with_peers: List[Dict[str, Any]]


class ExtractSymbolAndPeersRequest(BaseModel):
    """Request model for extracting symbols and fetching peers."""
    query: str
    peer_type: str = "sector"


@router.post("/extract-symbol-with-peers", response_model=CompanyWithPeersResponse)
async def extract_symbol_with_peers(request: ExtractSymbolAndPeersRequest):
    """Extract company symbols from query and fetch their peer companies.
    
    This endpoint combines symbol extraction with peer company fetching.
    It identifies companies from the user query and returns both the
    extracted companies and their peer companies.
    
    Args:
        request: ExtractSymbolAndPeersRequest with query and peer_type
        
    Returns:
        CompanyWithPeersResponse with extracted companies and their peers
        
    Example:
        Request Body:
        {
            "query": "What is the revenue of Apple and Microsoft?",
            "peer_type": "sector"
        }
        
        Response:
        {
            "query": "What is the revenue of Apple and Microsoft?",
            "extracted_companies": [
                {"symbol": "AAPL", "name": "Apple Inc."},
                {"symbol": "MSFT", "name": "Microsoft Corporation"}
            ],
            "companies_with_peers": [
                {
                    "symbol": "AAPL",
                    "company_name": "Apple Inc.",
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                    "peer_type": "sector",
                    "peers": [
                        {"name": "Microsoft Corporation", "symbol": "MSFT"}
                    ],
                    "peer_count": 1
                },
                {
                    "symbol": "MSFT",
                    "company_name": "Microsoft Corporation",
                    "sector": "Technology",
                    "industry": "Software",
                    "peer_type": "sector",
                    "peers": [
                        {"name": "Apple Inc.", "symbol": "AAPL"}
                    ],
                    "peer_count": 1
                }
            ]
        }
    """
    try:
        if not request.query or not request.query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")
        
        if request.peer_type.lower() not in ["sector", "industry"]:
            raise HTTPException(status_code=400, detail="peer_type must be 'sector' or 'industry'")
        
        # Step 1: Extract symbols from the query
        symbols_dict, llm_response, raw_content = extract_company_symbol(request.query)
        
        # Convert extracted symbols to list format
        extracted_companies = [
            ExtractedCompany(symbol=symbol, name=company_name)
            for symbol, company_name in symbols_dict.items()
        ]
        
        # Step 2: For each extracted symbol, fetch peer companies
        companies_with_peers = []
        for symbol, company_name in symbols_dict.items():
            try:
                peer_result = get_peer_companies(symbol, request.peer_type)
                peers = [PeerInfo(name=p["name"], symbol=p["symbol"]) for p in peer_result["peers"]]
                
                companies_with_peers.append({
                    "symbol": peer_result["symbol"],
                    "company_name": peer_result["company_name"],
                    "sector": peer_result.get("sector"),
                    "industry": peer_result.get("industry"),
                    "peer_type": peer_result["peer_type"],
                    "peers": [p.dict() for p in peers],
                    "peer_count": peer_result["peer_count"]
                })
            except Exception as e:
                # If peer lookup fails, still include the extracted company
                companies_with_peers.append({
                    "symbol": symbol,
                    "company_name": company_name,
                    "sector": None,
                    "industry": None,
                    "peer_type": request.peer_type,
                    "peers": [],
                    "peer_count": 0,
                    "error": str(e)
                })
        
        return CompanyWithPeersResponse(
            query=request.query,
            extracted_companies=extracted_companies,
            companies_with_peers=companies_with_peers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
