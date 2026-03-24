from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import json

from service.symbol_extraction_service import extract_company_symbol
from service.peer_company_service import get_peer_companies
from repository.sqlite_repository import SqliteRepository

router = APIRouter()


class PeerInfo(BaseModel):
    """Model for peer company information."""
    name: str
    symbol: str


class CompanyInfo(BaseModel):
    """Model for company information with peers."""
    symbol: str
    name: str
    peers: List[PeerInfo]


class SymbolWithPeersRequest(BaseModel):
    """Request model for extracting symbols and fetching peers."""
    query: str
    peer_type: str = "sector"


class SymbolWithPeersResponse(BaseModel):
    """Response model with extracted companies and their peers."""
    companies: List[CompanyInfo]


@router.post("/extract-symbol-with-peers", response_model=SymbolWithPeersResponse)
async def extract_symbol_with_peers(request: SymbolWithPeersRequest):
    """Extract company symbols from query and fetch their peer companies.
    
    Args:
        request: SymbolWithPeersRequest with query and peer_type
        
    Returns:
        SymbolWithPeersResponse with extracted companies and their peers
        
    Example:
        Request Body:
        {
            "query": "What is the revenue of Hexaware and Coforge?"
        }
        
        Response:
        {
            "companies": [
                {
                    "symbol": "HEXT",
                    "name": "Hexaware Technologies Limited",
                    "peers": [
                        {"name": "TCS Limited", "symbol": "TCS"},
                        {"name": "Infosys Limited", "symbol": "INFY"}
                    ]
                },
                {
                    "symbol": "COFORGE",
                    "name": "Coforge Limited",
                    "peers": [
                        {"name": "TCS Limited", "symbol": "TCS"},
                        {"name": "Hexaware Technologies Limited", "symbol": "HEXT"}
                    ]
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
        
        # Initialize database repository
        repo = SqliteRepository()
        
        # Get the next query_id
        query_id = repo.get_next_query_id()
        
        # Step 2: For each extracted symbol, fetch peer companies and save to DB
        companies = []
        for symbol, company_name in symbols_dict.items():
            try:
                peer_result = get_peer_companies(symbol, request.peer_type)
                peers = [PeerInfo(name=p["name"], symbol=p["symbol"]) for p in peer_result["peers"]]
                
                company_info = CompanyInfo(
                    symbol=symbol,
                    name=company_name,
                    peers=peers
                )
                companies.append(company_info)
                
                # Save to database with query_id
                peers_json = json.dumps([{"name": p.name, "symbol": p.symbol} for p in peers])
                repo.save_symbol_extraction_result(
                    query_id=query_id,
                    query=request.query,
                    symbol=symbol,
                    name=company_name,
                    peers=peers_json
                )
                
            except Exception as e:
                # If peer lookup fails, still include the extracted company with empty peers
                company_info = CompanyInfo(
                    symbol=symbol,
                    name=company_name,
                    peers=[]
                )
                companies.append(company_info)
                
                # Save to database without peers
                repo.save_symbol_extraction_result(
                    query_id=query_id,
                    query=request.query,
                    symbol=symbol,
                    name=company_name,
                    peers="[]"
                )
        
        repo.close()
        
        return SymbolWithPeersResponse(companies=companies)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
