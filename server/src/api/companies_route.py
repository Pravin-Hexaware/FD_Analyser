from fastapi import APIRouter, Query, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional
from api.service.company_service import CompanyService
from api.models.company_model import Company
from api.Xbrl_annual_extractor import extract_annual, ExtractAnnualRequest
from repository.sqlite_repository import SqliteRepository
import httpx
import json

router = APIRouter()

# Initialize service and repository
company_service = CompanyService()
db_repository = SqliteRepository()


# ===== PYDANTIC MODELS =====
class CompareCompaniesRequest(BaseModel):
    scrip_codes: List[str]
    frequency: str  # "annual" or "quarterly"
    year: Optional[str] = None
    quarter_type: Optional[str] = None  # MQ, JQ, SQ, DQ


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


@router.post("/companies/available-periods")
async def get_available_periods(request: CompareCompaniesRequest):
    """
    Get available financial periods that are common across all selected companies.
    
    For annual: Returns MC/DC format years available for all companies
    For quarterly: Returns quarter types (MQ, JQ, SQ, DQ) available for all companies
    
    This ensures we only show periods where ALL companies have data.
    """
    try:
        scrip_codes = request.scrip_codes
        frequency = request.frequency.lower()
        
        if not scrip_codes or len(scrip_codes) < 2:
            raise HTTPException(status_code=400, detail="At least 2 companies required")
        
        if frequency not in ["annual", "quarterly"]:
            raise HTTPException(status_code=400, detail="Frequency must be 'annual' or 'quarterly'")
        
        extraction_type = "annual" if frequency == "annual" else "quarterly"
        
        # Collect available periods for each company
        company_periods = {}
        
        for scrip_code in scrip_codes:
            try:
                extractions = db_repository.get_historical_extractions(
                    scrip_code=scrip_code,
                    extraction_type=extraction_type,
                    limit=20  # Get more records to check availability
                )
                
                # Extract period identifiers
                periods = set()
                for e in extractions:
                    pub_date = str(e.get("publication_date", ""))
                    if pub_date:
                        periods.add(pub_date)
                
                company_periods[scrip_code] = periods
                print(f"[PERIODS] Company {scrip_code} has {len(periods)} {frequency} periods: {sorted(list(periods))[:5]}...")
                
            except Exception as e:
                print(f"[PERIODS] Error getting periods for {scrip_code}: {e}")
                company_periods[scrip_code] = set()
        
        # Find common periods across ALL companies
        if not company_periods or len(company_periods) < len(scrip_codes):
            common_periods = set()
        else:
            # Intersection of all periods
            all_period_sets = list(company_periods.values())
            common_periods = all_period_sets[0].copy()
            for periods_set in all_period_sets[1:]:
                common_periods = common_periods.intersection(periods_set)
        
        # Sort for consistent ordering (most recent first)
        common_periods_sorted = sorted(list(common_periods), reverse=True)
        
        # Filter to last 5 years for annual, or all for quarterly
        if frequency == "annual":
            # Extract year from period (e.g., "2024" from "MC2024-2025")
            # Keep only the FIRST (most recent) period per year
            years_seen = {}
            filtered_periods = []
            for period in common_periods_sorted:
                # Extract year: "MC2024-2025" → "2024"
                year_part = period.split("-")[0][-4:]  # Get last 4 digits before dash
                if year_part not in years_seen and len(years_seen) < 5:
                    years_seen[year_part] = period
                    filtered_periods.append(period)
            common_periods_sorted = filtered_periods
            print(f"[PERIODS] Filtered to {len(filtered_periods)} unique years (last 5): {filtered_periods}")
        
        print(f"[PERIODS] Final available periods: {common_periods_sorted}")
        
        # Determine default period (first common one)
        default_period = common_periods_sorted[0] if common_periods_sorted else None
        
        return {
            "success": True,
            "frequency": frequency,
            "available_periods": common_periods_sorted,
            "default_period": default_period,
            "company_periods": {code: sorted(list(periods), reverse=True) for code, periods in company_periods.items()}
        }
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[PERIODS] Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/companies/compare-extract")
async def compare_companies_extract(request: CompareCompaniesRequest):
    """
    Compare companies using actual XBRL extraction endpoints.
    
    Workflow:
    1. Get scrip_codes from request
    2. Query database for XBRL links based on frequency
    3. Call /extract/annual or /extract/urls endpoint
    4. Return the extracted metrics from those endpoints
    5. Frontend will display only these metrics
    """
    try:
        scrip_codes = request.scrip_codes
        frequency = request.frequency.lower()
        
        if not scrip_codes or len(scrip_codes) < 2:
            raise HTTPException(status_code=400, detail="At least 2 companies required")
        
        if frequency not in ["annual", "quarterly"]:
            raise HTTPException(status_code=400, detail="Frequency must be 'annual' or 'quarterly'")

        
        # Container for results: {scrip_code: {company_name, data: []}}
        comparison_result = {}
        
        for scrip_code in scrip_codes:
            print(f"\n[COMPARE] Processing company {scrip_code}")
            
            # Get company details
            company = company_service.get_company_details(scrip_code)
            company_name = company.name if company else scrip_code
            
            # Get XBRL links from database using repository
            extraction_type = "annual" if frequency == "annual" else "quarterly"
            try:
                all_extractions = db_repository.get_historical_extractions(
                    scrip_code=scrip_code,
                    extraction_type=extraction_type,
                    limit=10  # Get more records for filtering
                )
            except Exception as e:
                print(f"[COMPARE] Error getting extractions: {e}")
                all_extractions = []
            
            # Filter by quarter_type if specified (for quarterly)
            if frequency == "quarterly" and request.quarter_type:
                quarter_type = request.quarter_type  # MQ, JQ, SQ, or DQ
                filtered = []
                for e in all_extractions:
                    pub_date = str(e.get("publication_date", ""))
                    # publication_date is like "MQ2025-2026", "JQ2025-2026", etc.
                    if pub_date.startswith(quarter_type):
                        filtered.append(e)
                extractions = filtered
                print(f"[COMPARE] Filtered to {len(extractions)} {frequency} extractions for quarter {quarter_type}")
            
            # Filter by year if specified (for annual)
            elif frequency == "annual" and request.year:
                year_filter = request.year  # e.g., "MC2024-2025" or "DC2024-2025"
                filtered = []
                for e in all_extractions:
                    pub_date = str(e.get("publication_date", ""))
                    # publication_date for annual is like "MC2024-2025", "DC2024-2025", etc.
                    # Frontend sends full format like "MC2024-2025", so we match directly or by year
                    # If it's a full format from frontend (MC/DC), match exactly
                    # If it's just a year, match by year
                    if pub_date == year_filter or f"{year_filter.split('-')[0]}-" in pub_date:
                        filtered.append(e)
                extractions = filtered
                print(f"[COMPARE] Filtered to {len(extractions)} {frequency} extractions for year {year_filter}")
                print(f"[COMPARE] Sample dates checked: {[e.get('publication_date') for e in all_extractions[:3]]}")
            
            else:
                extractions = all_extractions
            
            print(f"[COMPARE] Found {len(extractions)} {frequency} extractions for {scrip_code}")
            
            if not extractions:
                comparison_result[scrip_code] = {
                    "company_name": company_name,
                    "data": [],
                    "error": f"No {frequency} extractions found"
                }
                continue
            
            # Get XBRL links from extractions
            xbrl_links = [e.get("xbrl_link") for e in extractions if e.get("xbrl_link")]
            
            if not xbrl_links:
                comparison_result[scrip_code] = {
                    "company_name": company_name,
                    "data": [],
                    "error": "No XBRL links found in database"
                }
                continue
            
            print(f"[COMPARE] Got {len(xbrl_links)} XBRL links for {scrip_code}")
            
            # Call the appropriate extraction endpoint
            extracted_data = []
            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    if frequency == "annual":
                        # Call /extract/annual endpoint
                        response = await client.post(
                            "http://localhost:8001/api/extract/annual",
                            json={"url": xbrl_links}
                        )
                    else:
                        # Call /extract/urls endpoint (for quarterly)
                        response = await client.post(
                            "http://localhost:8001/api/extract/urls",
                            json={"url": xbrl_links}
                        )
                    
                    if response.status_code == 200:
                        extracted_data = response.json()
                        print(f"[COMPARE] Extraction successful, got {len(extracted_data)} records")
                    else:
                        print(f"[COMPARE] Extraction failed with status {response.status_code}")
                        extracted_data = []
            
            except Exception as extract_err:
                print(f"[COMPARE] Error calling extraction endpoint: {extract_err}")
                extracted_data = []
            
            # Process extracted data
            processed_records = []
            for record in extracted_data:
                if isinstance(record, dict):
                    # Skip error records
                    if record.get("type") == "error":
                        continue
                    
                    # Build normalized record
                    normalized = {
                        "url": record.get("url"),
                        "company_name": company_name,
                        "scrip_code": scrip_code,
                    }
                    
                    # Add metrics based on frequency
                    if frequency == "annual":
                        # From /extract/annual response
                        normalized.update({
                            "currency": record.get("currency"),
                            "level_of_rounding": record.get("level_of_rounding"),
                            # P&L metrics
                            "sales": record.get("Profit_and_Loss", {}).get("Sales"),
                            "expenses": record.get("Profit_and_Loss", {}).get("Expenses"),
                            "operating_profit": record.get("Profit_and_Loss", {}).get("OperatingProfit"),
                            "opm_percent": record.get("Profit_and_Loss", {}).get("OPM_percentage"),
                            "other_income": record.get("Profit_and_Loss", {}).get("OtherIncome"),
                            "interest": record.get("Profit_and_Loss", {}).get("Interest"),
                            "depreciation": record.get("Profit_and_Loss", {}).get("Depreciation"),
                            "pbt": record.get("Profit_and_Loss", {}).get("ProfitBeforeTax"),
                            "current_tax": record.get("Profit_and_Loss", {}).get("CurrentTax"),
                            "deferred_tax": record.get("Profit_and_Loss", {}).get("DeferredTax"),
                            "tax_total": record.get("Profit_and_Loss", {}).get("Tax"),
                            "tax_percent": record.get("Profit_and_Loss", {}).get("Tax_percent"),
                            "net_profit": record.get("Profit_and_Loss", {}).get("NetProfit"),
                            "eps": record.get("Profit_and_Loss", {}).get("EPS_in_RS"),
                            # Balance Sheet metrics
                            "equity_capital": record.get("Balance_Sheet", {}).get("EquityCapital"),
                            "reserves": record.get("Balance_Sheet", {}).get("Reserves"),
                            "borrowings": record.get("Balance_Sheet", {}).get("Borrowings"),
                            "other_liabilities": record.get("Balance_Sheet", {}).get("OtherLiabilities"),
                            "total_liabilities": record.get("Balance_Sheet", {}).get("TotalLiabilities"),
                            "total_equity": record.get("Balance_Sheet", {}).get("TotalEquity"),
                            "fixed_assets": record.get("Balance_Sheet", {}).get("FixedAssets"),
                            "cwip": record.get("Balance_Sheet", {}).get("CWIP"),
                            "investments": record.get("Balance_Sheet", {}).get("Investments"),
                            "total_assets": record.get("Balance_Sheet", {}).get("TotalAssets"),
                            # Cash Flow metrics
                            "cash_from_operations": record.get("Cash_Flow", {}).get("CashFromOperatingActivity"),
                            "cash_from_investing": record.get("Cash_Flow", {}).get("CashFromInvestingActivity"),
                            "cash_from_financing": record.get("Cash_Flow", {}).get("CashFromFinancingActivity"),
                        })
                    else:  # quarterly
                        # From /extract/urls response (CompanyMetrics model)
                        # This contains screener-style metrics
                        normalized.update({
                            "sales": record.get("Sales"),
                            "expenses": record.get("Expenses"),
                            "operating_profit": record.get("OperatingProfit"),
                            "opm_percent": record.get("OPM_percentage"),
                            "other_income": record.get("OtherIncome"),
                            "interest": record.get("InterestExpense"),
                            "depreciation": record.get("Depreciation"),
                            "pbt": record.get("ProfitBeforeTax"),
                            "tax": record.get("Tax"),
                            "net_profit": record.get("NetProfit"),
                            "eps": record.get("EPS"),
                            "equity": record.get("TotalEquity"),
                            "borrowings": record.get("Borrowings"),
                            "book_value": record.get("BookValue"),
                            "roe": record.get("ROE"),
                            "roce": record.get("ROCE"),
                            "de_ratio": record.get("DE"),
                        })
                    
                    processed_records.append(normalized)
            
            comparison_result[scrip_code] = {
                "company_name": company_name,
                "data": processed_records
            }
            
            print(f"[COMPARE] Final result for {scrip_code}: {len(processed_records)} records")
        
        return {
            "success": True,
            "frequency": frequency,
            "comparison": comparison_result
        }
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[COMPARE] Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


