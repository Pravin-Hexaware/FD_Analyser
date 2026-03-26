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
        return {
            "success": True,
            "count": len(companies),
            "companies": [c.to_dict() for c in companies]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/search")
async def search_companies(q: str = Query(..., min_length=1, max_length=100)):
    """
    Auto-suggest endpoint for search bar
    Returns simplified company suggestions for real-time display
    Query: partial text (e.g., "TC", "REL", "INF")
    Response: array of suggestions with id, name, symbol
    """
    try:
        companies = company_service.search_companies(q)
        # Return simplified suggestions format for auto-suggest dropdown
        suggestions = [
            {
                "id": c.id,
                "name": c.name,
                "symbol": c.symbol,
                "scripcode": c.bse_code,  # Add BSE code to suggestions
                "sector": c.sector
            }
            for c in companies
        ]
        return suggestions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{company_id}")
async def get_company_details(company_id: str):
    """Get detailed information about a specific company"""
    try:
        company = company_service.get_company_details(company_id)
        
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
        
        return {
            "success": True,
            "company": company.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{company_id}/financials")
async def get_company_financials(company_id: str, years: Optional[int] = 5):
    """Get financial data for a company"""
    try:
        company = company_service.get_company_details(company_id)
        
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
        
        financials = company_service.get_company_financials(company_id, years)
        
        return {
            "success": True,
            "company_id": company_id,
            "years_requested": years,
            "financials": [
                {
                    "year": f.year,
                    "sales": f.sales,
                    "ebitda": f.ebitda,
                    "opm": f.opm,
                    "pat": f.pat,
                    "eps": f.eps,
                    "roce": f.roce,
                    "de": f.de,
                    "cfo": f.cfo,
                }
                for f in financials
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/trending")
async def get_trending_companies():
    """Get trending/popular companies"""
    try:
        trending = company_service.get_trending_companies(limit=4)
        return {
            "success": True,
            "trending": [
                {
                    "id": c.id,
                    "name": c.name,
                    "symbol": c.symbol,
                    "sector": c.sector,
                    "sales": c.financials[0].sales if c.financials else 0,
                    "change": "+2.5%"
                }
                for c in trending
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
