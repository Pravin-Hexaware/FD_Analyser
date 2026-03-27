from fastapi import APIRouter, Query, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional
from api.service.company_service import CompanyService
from api.models.company_model import Company
from api.xbrl_route import extract_annual, ExtractAnnualRequest
import httpx

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


class YearlyReportExtractionRequest(BaseModel):
    url: str
    symbol: Optional[str] = None
    scrip_code: Optional[str] = None


@router.post("/companies/extract-yearly")
async def extract_yearly_report(
    body: YearlyReportExtractionRequest,
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key")
):
    """Extract a yearly report from XBRL URL and optionally merge DB + IndianAPI data."""
    if not body.url:
        raise HTTPException(status_code=400, detail="url is required")

    if not x_api_key or not x_api_key.startswith("sk-live-"):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Key")

    try:
        # Fetch XBRL extraction from existing endpoint helper
        yearly = await extract_annual(ExtractAnnualRequest(url=body.url))

        # If the endpoint returned error object, propagate
        if yearly.get("error"):
            raise HTTPException(status_code=422, detail=f"Extraction failed: {yearly.get('error')}")

        # Attempt to resolve company from DB
        company = None
        if body.symbol or body.scrip_code:
            lookup = body.symbol or body.scrip_code
            company = company_service.get_company_details(lookup)

        # DB metadata
        db_metadata = None
        db_annual = None
        db_quarterly = None
        if company:
            db_metadata = company.to_dict()
            db_annual = company_service.get_latest_annual_data(company.symbol)
            db_quarterly = company_service.get_latest_quarterly_data(company.symbol)

        # Call Indian API using provided API key
        indianapi_data = None
        if body.symbol or company:
            query_name = body.symbol or company.symbol
            async with httpx.AsyncClient(timeout=15) as client:
                rsp = await client.get(
                    f"https://stock.indianapi.in/stock",
                    params={"name": query_name},
                    headers={"X-Api-Key": x_api_key},
                )
            if rsp.status_code == 200:
                indianapi_data = rsp.json()

        return {
            "success": True,
            "xbrl_data": yearly,
            "db_metadata": db_metadata,
            "db_annual": db_annual,
            "db_quarterly": db_quarterly,
            "indianapi_data": indianapi_data,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{company_id}")
async def get_company(company_id: str):
    """Resolve company by id/symbol/scrip_code and return company metadata."""
    try:
        company = company_service.get_company_details(company_id)

        if not company:
            # fallback to search resolve if direct lookup fails
            candidates = company_service.search_companies(company_id)
            company = candidates[0] if candidates else None

        if not company:
            raise HTTPException(status_code=404, detail=f"Company {company_id} not found")

        return {
            "success": True,
            "company": company.to_dict(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{company_id}/financials")
async def get_company_financials(company_id: str, years: Optional[int] = 5):
    """Get financial data for a company"""
@router.get("/companies/{scrip_code}")
async def get_company_by_scrip_code(scrip_code: str):
    """Get a single company by scrip code"""
    try:
        company = company_service.get_company_details(company_id)

        if not company:
            # allow symbol fallback
            candidates = company_service.search_companies(company_id)
            company = candidates[0] if candidates else None

        company = company_service.get_company_details(scrip_code)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {company_id} not found")

        financials = company_service.get_company_financials(company_id, years)

            raise HTTPException(status_code=404, detail=f"Company with scrip code '{scrip_code}' not found")

        return {
            "success": True,
            "company_id": company_id,
            "company_symbol": company.symbol,
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


@router.get("/companies/{company_id}/quarterly")
async def get_company_quarterly(company_id: str):
    try:
        company = company_service.get_company_details(company_id)
        symbol = company.symbol if company else company_id

        quarterly = company_service.get_latest_quarterly_data(symbol)
        if not quarterly:
            raise HTTPException(status_code=404, detail=f"No quarterly data for {company_id}")

        return {"success": True, "quarterly": quarterly}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{company_id}/annual")
async def get_company_annual(company_id: str):
    try:
        company = company_service.get_company_details(company_id)
        symbol = company.symbol if company else company_id

        annual = company_service.get_latest_annual_data(symbol)
        if not annual:
            raise HTTPException(status_code=404, detail=f"No annual data for {company_id}")

        return {"success": True, "annual": annual}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/resolve")
async def resolve_company(query: str = Query(..., min_length=1)):
    """Resolve company by id/symbol/scrip_code (fallback for UI stale ids)."""
    try:
        companies = company_service.search_companies(query)
        return {
            "success": True,
            "companies": [c.to_dict() for c in companies],
        }
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


