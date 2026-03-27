from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from api.service.company_service import CompanyService
from api.models.company_model import Company

router = APIRouter()

# Initialize service
company_service = CompanyService()


@router.get("/companies")
async def get_all_companies():
    """Get all companies from database"""
    try:
        companies = company_service.get_all_companies()
        # Return array of company dicts directly for frontend compatibility
        return [
            {
                "id": c.id,
                "scrip_code": c.bse_code,
                "company_name": c.name,
                "symbol": c.symbol,
                "sector": c.sector,
                "industry": c.industry
            }
            for c in companies
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/search")
async def search_companies(q: str = Query(..., min_length=1, max_length=100)):
    """
    Auto-suggest endpoint for search bar
    Returns simplified company suggestions for real-time display
    Query: partial text (e.g., "TC", "REL", "INF")
    Response: array of suggestions with id, name, symbol, scripcode, sector
    """
    try:
        companies = company_service.search_companies(q)
        # Return simplified suggestions format for auto-suggest dropdown
        suggestions = [
            {
                "id": c.id,
                "name": c.name,
                "symbol": c.symbol,
                "scripcode": c.bse_code,
                "sector": c.sector
            }
            for c in companies
        ]
        return suggestions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{scrip_code}")
async def get_company_by_scrip_code(scrip_code: str):
    """Get a single company by scrip code"""
    try:
        company = company_service.get_company_details(scrip_code)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company with scrip code '{scrip_code}' not found")
        
        return {
            "id": company.id,
            "scrip_code": company.bse_code,
            "company_name": company.name,
            "symbol": company.symbol,
            "sector": company.sector,
            "industry": company.industry
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

