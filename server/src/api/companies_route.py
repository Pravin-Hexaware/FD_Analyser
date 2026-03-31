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
                "name": c.name,
                "company_name": c.name,
                "symbol": c.symbol,
                "bseCode": c.bse_code,
                "scripCode": c.bse_code,
                "scrip_code": c.bse_code,
                "sector": c.sector,
                "industry": c.industry,
                "xbrlLink": "",
                "financials": []
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
async def get_company_financials(
    company_id: str,
    frequency: str = "annual",
    years: Optional[int] = 5
):
    """Get financial data for a company."""
    try:
        company = company_service.get_company_details(company_id)

        if not company:
            candidates = company_service.search_companies(company_id)
            company = candidates[0] if candidates else None

        if not company:
            raise HTTPException(status_code=404, detail=f"Company {company_id} not found")

        symbol_or_scrip = company.bse_code or company.symbol or company_id

        financials_data = None
        if frequency.lower() == "annual":
            annual = company_service.get_latest_annual_data(symbol_or_scrip)
            if annual:
                financials_data = [annual]
        elif frequency.lower() == "quarterly":
            quarterly = company_service.get_latest_quarterly_data(symbol_or_scrip)
            if quarterly:
                financials_data = [quarterly]
        else:
            financials_data = company_service.get_company_financials(symbol_or_scrip, years)

        # Fallback if not found initially
        if not financials_data:
            financials_data = company_service.get_company_financials(symbol_or_scrip, years)

        if not financials_data:
            raise HTTPException(status_code=404, detail=f"Financials for company {company_id} not found")

        # If raw list of YearlyFinancials or dict record
        if isinstance(financials_data, dict):
            financials_data = [financials_data]

        return {
            "success": True,
            "company_id": company.id,
            "company_symbol": company.symbol,
            "scrip_code": company.bse_code,
            "company_name": company.name,
            "sector": company.sector,
            "industry": company.industry,
            "frequency": frequency,
            "years_requested": years,
            "financials": financials_data,
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

        return {"success": True, "financials": [quarterly], "frequency": "quarterly"}
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

        return {"success": True, "financials": [annual], "frequency": "annual"}
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


