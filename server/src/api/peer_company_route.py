from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from service.peer_company_service import get_peer_companies

router = APIRouter()


class PeerInfo(BaseModel):
    """Model for peer company information."""
    name: str
    symbol: str


class GetPeersRequest(BaseModel):
    """Request model for peer companies endpoint."""
    symbol: str
    peer_type: str = "sector"  # Default to sector


class PeersResponse(BaseModel):
    """Response model for peer companies endpoint."""
    symbol: str
    company_name: Optional[str]
    sector: Optional[str]
    industry: Optional[str]
    peer_type: str
    peers: List[PeerInfo]
    peer_count: int


@router.post("/get-peers", response_model=PeersResponse)
async def get_peers(request: GetPeersRequest):
    """Fetch peer companies for a given stock symbol.
    
    This endpoint retrieves peer companies from the database based on sector or industry.
    
    Args:
        request: GetPeersRequest with symbol and peer_type
        
    Returns:
        PeersResponse with company info and list of peer companies
        
    Example:
        Request Body:
        {
            "symbol": "AAPL",
            "peer_type": "sector"
        }
        
        Response:
        {
            "symbol": "AAPL",
            "company_name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "peer_type": "sector",
            "peers": [
                {"name": "Microsoft Corporation", "symbol": "MSFT"},
                {"name": "Intel Corporation", "symbol": "INTC"}
            ],
            "peer_count": 2
        }
    """
    try:
        if not request.symbol or not request.symbol.strip():
            raise HTTPException(status_code=400, detail="Symbol cannot be empty")
        
        if request.peer_type.lower() not in ["sector", "industry"]:
            raise HTTPException(status_code=400, detail="peer_type must be 'sector' or 'industry'")
        
        result = get_peer_companies(request.symbol, request.peer_type)
        
        return PeersResponse(
            symbol=result["symbol"],
            company_name=result["company_name"],
            sector=result.get("sector"),
            industry=result.get("industry"),
            peer_type=result["peer_type"],
            peers=[PeerInfo(name=p["name"], symbol=p["symbol"]) for p in result["peers"]],
            peer_count=result["peer_count"]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
