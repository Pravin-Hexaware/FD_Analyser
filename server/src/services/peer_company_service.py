"""Peer company finder using Tortoise CompanyInfo / Industry."""

from typing import Any, Dict

from repositories.company_repository import find_peers, get_company_by_id


async def get_peer_companies(symbol: str, peer_type: str = "sector") -> Dict[str, Any]:
    """Fetch peer companies sharing the same industry."""
    if not symbol or not symbol.strip():
        raise ValueError("Symbol cannot be empty")

    company = await get_company_by_id(symbol.strip())
    if not company:
        return {
            "symbol": symbol,
            "company_name": None,
            "peers": [],
            "message": "Company not found in database",
        }

    result = await find_peers(company.symbol or symbol)
    peers = [
        {"name": p.get("company_name"), "symbol": p.get("symbol")}
        for p in result.get("peers", [])
    ]
    return {
        "symbol": symbol,
        "company_name": company.name,
        "sector": company.sector,
        "industry": company.industry,
        "peer_type": peer_type,
        "peers": peers,
        "peer_count": len(peers),
    }
