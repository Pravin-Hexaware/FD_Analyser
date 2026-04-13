from fastapi import APIRouter, Query, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from api.service.company_service import CompanyService
from api.models.company_model import Company
from api.Xbrl_annual_extractor import extract_annual, ExtractAnnualRequest
from api.xbrl_route import extract_xbrl, ExtractXBRLRequest
from repository.sqlite_repository import SqliteRepository
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


class ExtractionCompareRequest(BaseModel):
    scrip_codes: List[str]
    frequency: str = "annual"
    period: Optional[str] = "latest year"


def _flatten_extraction_metrics(extracted: Any, publication_date: Optional[str] = None) -> dict:
    if hasattr(extracted, "dict") and callable(getattr(extracted, "dict")):
        extracted = extracted.dict()

    if not isinstance(extracted, dict):
        return {}

    def map_key(key: str) -> str:
        mapping = {
            "Sales": "sales",
            "Expenses": "expenses",
            "OperatingProfit": "operating_profit",
            "OPM_percentage": "opm_percentage",
            "OtherIncome": "other_income",
            "CostOfMaterialsConsumed": "cost_of_materials_consumed",
            "EmployeeBenefitExpense": "employee_benefit_expense",
            "OtherExpenses": "other_expenses",
            "Interest": "interest",
            "Depreciation": "depreciation",
            "ProfitBeforeTax": "profit_before_tax",
            "CurrentTax": "current_tax",
            "DeferredTax": "deferred_tax",
            "Tax": "tax",
            "Tax_percent": "tax_percent",
            "NetProfit": "net_profit",
            "EPS_in_RS": "eps_in_rs",
            "EquityCapital": "equity_capital",
            "Reserves": "reserves",
            "Borrowings": "borrowings",
            "OtherLiabilities": "other_liabilities",
            "TotalLiabilities": "total_liabilities",
            "TotalEquity": "total_equity",
            "FixedAssets": "fixed_assets",
            "CWIP": "cwip",
            "Investments": "investments",
            "TotalAssets": "total_assets",
            "CashFromOperatingActivity": "cash_from_operating_activity",
            "CashFromInvestingActivity": "cash_from_investing_activity",
            "CashFromFinancingActivity": "cash_from_financing_activity",
            "company_name": "company_name",
            "company_symbol": "company_symbol",
            "currency": "currency",
            "level_of_rounding": "level_of_rounding",
            "reporting_type": "reporting_type",
            "NatureOfReport": "nature_of_report",
            "type": "type",
            "url": "url",
            "error": "error",
        }
        return mapping.get(key, key.lower())

    flattened = {}

    for key, value in extracted.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                flattened[map_key(nested_key)] = nested_value
            continue
        flattened[map_key(key)] = value

    if publication_date and not flattened.get("period"):
        flattened["period"] = publication_date
    return flattened


@router.post("/companies/extraction_compare")
async def compare_extraction(request: ExtractionCompareRequest):
    try:
        print(f"[EXTRACTION_COMPARE] endpoint triggered")
        print(f"[EXTRACTION_COMPARE] request: frequency={request.frequency}, period={request.period}, scrip_codes={request.scrip_codes}")

        if not request.scrip_codes or len(request.scrip_codes) < 2:
            raise HTTPException(status_code=400, detail="At least 2 companies required for extraction comparison")

        frequency = request.frequency.lower()
        if frequency not in {"annual", "quarterly"}:
            raise HTTPException(status_code=400, detail="frequency must be 'annual' or 'quarterly'")

        repo = SqliteRepository()
        url_to_scrip: Dict[str, str] = {}
        payload_urls: list[str] = []
        companies_payload: Dict[str, Any] = {}
        available_periods: Dict[str, list[str]] = {}

        for scrip_code in request.scrip_codes:
            company = company_service.get_company_details(scrip_code)
            matched = repo.get_extraction_records(
                scrip_code,
                extraction_type=frequency,
                period=request.period,
                latest_only=True,
                limit=1,
            )

            available = repo.get_extraction_records(
                scrip_code,
                extraction_type=frequency,
                limit=10,
            )
            available_periods[scrip_code] = [row.get("publication_date") for row in available if row.get("publication_date")]

            print(f"[EXTRACTION_COMPARE] company={scrip_code} available_records={len(available)} matched_records={len(matched)} available_periods={available_periods.get(scrip_code)}")

            if matched and len(matched) > 0:
                record = matched[0]
                xbrl_link = record.get("xbrl_link")
                print(f"[EXTRACTION_COMPARE] selected_record for {scrip_code}: publication_date={record.get('publication_date')} report_type={record.get('report_type')} xbrl_link={xbrl_link}")
                if xbrl_link:
                    payload_urls.append(xbrl_link)
                    url_to_scrip[xbrl_link] = scrip_code
                    companies_payload[scrip_code] = {
                        "company_name": record.get("company_name") or (company.name if company else None),
                        "company_symbol": record.get("symbol") or (company.symbol if company else None),
                        "scrip_code": scrip_code,
                        "publication_date": record.get("publication_date"),
                        "report_type": record.get("report_type"),
                        "xbrl_url": xbrl_link,
                        "financials": [],
                    }
                else:
                    print(f"[EXTRACTION_COMPARE] warning: matched record for {scrip_code} has no xbrl_link")
            else:
                print(f"[EXTRACTION_COMPARE] no matching extraction record found for company={scrip_code} period={request.period}")
                companies_payload[scrip_code] = {
                    "company_name": company.name if company else None,
                    "company_symbol": company.symbol if company else None,
                    "scrip_code": scrip_code,
                    "publication_date": None,
                    "report_type": None,
                    "xbrl_url": None,
                    "financials": [],
                }

        print(f"[EXTRACTION_COMPARE] payload_urls={payload_urls}")
        extracted_results = []
        if payload_urls:
            if frequency == "annual":
                print("[EXTRACTION_COMPARE] calling endpoint /api/extract/annual")
                extracted_results = await extract_annual(ExtractAnnualRequest(url=payload_urls))
            else:
                print("[EXTRACTION_COMPARE] calling endpoint /api/extract/urls")
                extracted_results = await extract_xbrl(ExtractXBRLRequest(url=payload_urls))

            print(f"[EXTRACTION_COMPARE] extracted_results count={len(extracted_results)}")
            for raw_result in extracted_results:
                result = raw_result.dict() if hasattr(raw_result, "dict") and callable(getattr(raw_result, "dict")) else raw_result
                url = result.get("url") if isinstance(result, dict) else None
                result_type = result.get("type") if isinstance(result, dict) else None
                error_msg = result.get("error") if isinstance(result, dict) else None
                print(f"[EXTRACTION_COMPARE] raw result url={url} type={result_type} error={error_msg}")
                if url and url_to_scrip.get(url):
                    scrip_code = url_to_scrip[url]
                    flattened = _flatten_extraction_metrics(result, companies_payload[scrip_code].get("publication_date"))
                    companies_payload[scrip_code]["financials"] = [flattened]
                    companies_payload[scrip_code]["extraction"] = result
                    print(f"[EXTRACTION_COMPARE] attached extraction result to {scrip_code}")
                else:
                    print(f"[EXTRACTION_COMPARE] warning: extracted result url={url} did not match any requested company")

        else:
            print("[EXTRACTION_COMPARE] no URLs to extract, skipping extraction call")

        response_payload = {
            "success": True,
            "companies": companies_payload,
            "frequency": frequency,
            "period": request.period,
            "available_periods": available_periods,
            "table": {"headers": [], "rows": []},
            "count": len(companies_payload),
        }
        print(f"[EXTRACTION_COMPARE] response prepared count={len(companies_payload)}")
        return response_payload
    except HTTPException:
        raise
    except Exception as e:
        print(f"[EXTRACTION_COMPARE] ERROR: {str(e)}")
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


