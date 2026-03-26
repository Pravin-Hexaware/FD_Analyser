"""Peer company finder service using SQLite database.

This service retrieves peer companies from the database based on sector or industry.
"""

from typing import Dict, List, Any
from repository.sqlite_repository import SqliteRepository


def get_peer_companies(symbol: str, peer_type: str = "sector") -> Dict[str, Any]:
    """Fetch peer companies from the database based on sector or industry.
    
    This function retrieves companies that are peers to the given company symbol.
    Peers are determined by matching sector or industry.
    
    Args:
        symbol: Stock ticker symbol of the company to find peers for
        peer_type: Type of peer matching - "sector" or "industry" (default: "sector")
        
    Returns:
        A dictionary containing:
        - symbol: The input stock symbol
        - company_name: The name of the company
        - peers: List of peer companies with their names and symbols
    """
    if not symbol or not symbol.strip():
        raise ValueError("Symbol cannot be empty")
    
    repo = SqliteRepository()
    
    try:
        # First, find the company by symbol
        cursor = repo._conn.cursor()
        cursor.execute(
            "SELECT id, company_name, symbol, sector, industry FROM company_table WHERE UPPER(symbol) = UPPER(?)",
            (symbol,)
        )
        company = cursor.fetchone()
        
        if not company:
            return {
                "symbol": symbol,
                "company_name": None,
                "peers": [],
                "message": "Company not found in database"
            }
        
        company_dict = dict(company)
        company_name = company_dict.get("company_name")
        sector = company_dict.get("sector")
        industry = company_dict.get("industry")
        
        # Find peer companies based on peer_type
        if peer_type.lower() == "sector" and sector:
            cursor.execute(
                """SELECT company_name, symbol FROM company_table 
                   WHERE UPPER(sector) = UPPER(?) AND UPPER(symbol) != UPPER(?)
                   ORDER BY company_name""",
                (sector, symbol)
            )
        elif peer_type.lower() == "industry" and industry:
            cursor.execute(
                """SELECT company_name, symbol FROM company_table 
                   WHERE UPPER(industry) = UPPER(?) AND UPPER(symbol) != UPPER(?)
                   ORDER BY company_name""",
                (industry, symbol)
            )
        else:
            cursor.execute(
                """SELECT company_name, symbol FROM company_table 
                   WHERE UPPER(symbol) != UPPER(?)
                   ORDER BY company_name LIMIT 10""",
                (symbol,)
            )
        
        peers = []
        for row in cursor.fetchall():
            peers.append({
                "name": row[0],
                "symbol": row[1]
            })
        
        return {
            "symbol": symbol,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "peer_type": peer_type,
            "peers": peers,
            "peer_count": len(peers)
        }
        
    except Exception as e:
        raise RuntimeError(f"Error fetching peer companies: {str(e)}")
    finally:
        repo._conn.close()
