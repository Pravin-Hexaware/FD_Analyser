from fastapi import APIRouter, Query, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import re
from api.service.company_service import CompanyService
from api.service.comparision_service import calculate_metrics_fourd
from api.xbrl_route import calculate_metrics, _convert_xml_grouped_to_list
from repository.sqlite_repository import SqliteRepository
from service.html_extraction_service import extract_ix_facts_from_root
from service.xml_extraction_service import extract_xbrl_data_from_bytes
from lxml import html as lxml_html
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
                    "https://stock.indianapi.in/stock",
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


def _resolve_compare_period(period: str, frequency: str, available_periods: list[str]) -> Optional[str]:
    def _parse_year_range(period_text: str) -> Optional[tuple[int, int]]:
        if not period_text:
            return None
        match = re.search(r"(\d{4})\s*[-_/]\s*(\d{4})", period_text)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None

    if not period:
        return None

    normalized = period.strip().lower()

    if frequency == "quarterly":
        if normalized in {"latest quarter", "latest"}:
            return None

        quarter_map = {
            "march": "mq",
            "mar": "mq",
            "mq": "mq",
            "q1": "mq",
            "june": "jq",
            "jun": "jq",
            "jq": "jq",
            "q2": "jq",
            "september": "sq",
            "sep": "sq",
            "sept": "sq",
            "sq": "sq",
            "q3": "sq",
            "december": "dq",
            "dec": "dq",
            "dq": "dq",
            "q4": "dq",
        }

        quarter_prefix = quarter_map.get(normalized)
        if quarter_prefix:
            matches = [p for p in available_periods if p and p.upper().startswith(quarter_prefix.upper())]
            return matches[0] if matches else None

        for p in available_periods:
            if p and p.lower() == normalized:
                return p

        return None

    if frequency == "annual":
        if normalized in {"latest year", "latest"}:
            return None

        period_upper = normalized.upper().replace(" ", "")

        if period_upper.startswith("FY") or period_upper.startswith("MC") or period_upper.startswith("DC"):
            exact_matches = [p for p in available_periods if p and p.upper().replace(" ", "") == period_upper]
            if exact_matches:
                return exact_matches[0]

            requested_range = _parse_year_range(period_upper)
            if requested_range:
                for p in available_periods:
                    parsed = _parse_year_range(str(p).upper())
                    if parsed == requested_range:
                        return p
            return None

        try:
            year = int(normalized)
            matches = [p for p in available_periods if p and p.endswith(f"-{year}")]
            return matches[0] if matches else None
        except ValueError:
            pass

        for p in available_periods:
            if p and p.lower() == normalized:
                return p

        return None


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
    """
    Compare companies using raw_content from xbrl_filing_table.
    NEW APPROACH: 
    1. Query annual_extractions or quarterly_extractions table to find available publication dates
    2. Select appropriate record based on period requested
    3. Use company_name + publication_date to find matching raw_content in xbrl_filing_table
    4. Parse raw_content and extract metrics
    """
    try:
        print("[EXTRACTION_COMPARE] endpoint triggered (NEW: raw_content from DB using extraction tables)")
        print(f"[EXTRACTION_COMPARE] request: frequency={request.frequency}, period={request.period}, scrip_codes={request.scrip_codes}")

        if not request.scrip_codes or len(request.scrip_codes) < 2:
            raise HTTPException(status_code=400, detail="At least 2 companies required for extraction comparison")

        frequency = request.frequency.lower()
        if frequency not in {"annual", "quarterly"}:
            raise HTTPException(status_code=400, detail="frequency must be 'annual' or 'quarterly'")

        repo = SqliteRepository()
        companies_payload: Dict[str, Any] = {}
        available_periods: Dict[str, list[str]] = {}

        # Step 1: Get extraction records from appropriate table (annual or quarterly)
        for scrip_code in request.scrip_codes:
            company = company_service.get_company_details(scrip_code)
            
            # Get extraction records from the appropriate table
            extraction_records = repo.get_extraction_records(
                scrip_code,
                extraction_type=frequency,
                limit=10
            )
            
            # Collect available periods
            available_periods[scrip_code] = [
                r.get("publication_date") for r in extraction_records 
                if r.get("publication_date")
            ]
            print(f"[EXTRACTION_COMPARE] company={scrip_code} extraction_records={len(extraction_records)} periods={available_periods.get(scrip_code)}")

            # Initialize company payload
            companies_payload[scrip_code] = {
                "company_name": company.name if company else None,
                "company_symbol": company.symbol if company else None,
                "scrip_code": scrip_code,
                "publication_date": None,
                "report_type": None,
                "xbrl_url": None,
                "financials": [],
            }

            # Step 2: Select appropriate extraction record based on period
            selected_record = None
            if request.period in ["latest year", "latest quarter", "latest"]:
                # Use the first (most recent) record
                if extraction_records:
                    selected_record = extraction_records[0]
            else:
                selected_period = _resolve_compare_period(request.period or "", frequency, available_periods[scrip_code])
                if selected_period:
                    for record in extraction_records:
                        if record.get("publication_date") == selected_period:
                            selected_record = record
                            break
                if not selected_record and extraction_records:
                    selected_record = extraction_records[0]
                print(f"[EXTRACTION_COMPARE] requested period={request.period}, resolved_period={selected_period}")

            # Step 3: If we have a record, use company_name + publication_date to find raw_content in xbrl_filing_table
            if selected_record:
                company_name = selected_record.get("company_name")
                publication_date = selected_record.get("publication_date")
                xbrl_link = selected_record.get("xbrl_link")
                
                print(f"[EXTRACTION_COMPARE] selected_record for {scrip_code}: company_name={company_name}, publication_date={publication_date}, xbrl_link={xbrl_link}")
                
                # Query xbrl_filing_table using company_name and publication_date as keys
                if company_name and publication_date:
                    cur = repo._conn.cursor()
                    cur.execute(
                        """
                        SELECT scrip_code, symbol, xbrl_link, publication_date, report_type, raw_content
                        FROM xbrl_filing_table
                        WHERE scrip_code = ? AND publication_date = ? AND raw_content IS NOT NULL
                        LIMIT 1
                        """,
                        (scrip_code, publication_date)
                    )
                    xbrl_record = cur.fetchone()
                    
                    if xbrl_record:
                        raw_content = dict(xbrl_record).get("raw_content")
                        print(f"[EXTRACTION_COMPARE] found raw_content in xbrl_filing_table for {scrip_code} with publication_date={publication_date}")
                        
                        # Step 4: Parse raw_content
                        if raw_content:
                            try:
                                print(f"[EXTRACTION_COMPARE] parsing raw_content for {scrip_code}")
                                
                                # Determine content type and parse accordingly
                                xbrl_link = dict(xbrl_record).get("xbrl_link", "")
                                raw_text = raw_content if isinstance(raw_content, str) else raw_content.decode('utf-8', errors='replace')
                                raw_preview = raw_text.lstrip()[:1024].lower()
                                raw_bytes = raw_text.encode('utf-8')

                                # Detect content type by looking at actual content
                                is_html_content = (
                                    '<html' in raw_preview or 
                                    '<!doctype html' in raw_preview or 
                                    '<body' in raw_preview or 
                                    '<ix:' in raw_preview or
                                    xbrl_link.lower().endswith('.html') or 
                                    xbrl_link.lower().endswith('.htm')
                                )
                                
                                is_xml_content = (
                                    '<?xml' in raw_preview or
                                    '<xbrli:xbrl' in raw_preview or
                                    '<xbrl' in raw_preview or
                                    xbrl_link.lower().endswith('.xml')
                                )

                                # Parse content with fallback mechanism
                                if is_html_content:
                                    print(f"[EXTRACTION_COMPARE] parsing HTML/iXBRL content for {scrip_code}")
                                    try:
                                        tree = lxml_html.fromstring(raw_bytes)
                                        extracted_data = extract_ix_facts_from_root(tree)
                                        print(f"[EXTRACTION_COMPARE] extracted {len(extracted_data)} facts from HTML for {scrip_code}")
                                    except Exception as html_error:
                                        print(f"[EXTRACTION_COMPARE] HTML parsing failed, trying XML fallback for {scrip_code}: {str(html_error)}")
                                        try:
                                            extracted_data_grouped = extract_xbrl_data_from_bytes(raw_bytes, only_prefix="in-bse-fin")
                                            extracted_data = _convert_xml_grouped_to_list(extracted_data_grouped)
                                            print(f"[EXTRACTION_COMPARE] XML fallback succeeded - extracted {len(extracted_data)} facts for {scrip_code}")
                                        except Exception as xml_error:
                                            print(f"[EXTRACTION_COMPARE] XML fallback also failed for {scrip_code}: {str(xml_error)}")
                                            raise html_error
                                elif is_xml_content:
                                    print(f"[EXTRACTION_COMPARE] parsing XML content for {scrip_code}")
                                    try:
                                        extracted_data_grouped = extract_xbrl_data_from_bytes(raw_bytes, only_prefix="in-bse-fin")
                                        extracted_data = _convert_xml_grouped_to_list(extracted_data_grouped)
                                        print(f"[EXTRACTION_COMPARE] extracted {len(extracted_data)} facts from XML for {scrip_code}")
                                    except Exception as xml_error:
                                        print(f"[EXTRACTION_COMPARE] XML parsing failed, trying HTML fallback for {scrip_code}: {str(xml_error)}")
                                        try:
                                            tree = lxml_html.fromstring(raw_bytes)
                                            extracted_data = extract_ix_facts_from_root(tree)
                                            print(f"[EXTRACTION_COMPARE] HTML fallback succeeded - extracted {len(extracted_data)} facts for {scrip_code}")
                                        except Exception as html_error:
                                            print(f"[EXTRACTION_COMPARE] HTML fallback also failed for {scrip_code}: {str(html_error)}")
                                            raise xml_error
                                else:
                                    # Unknown format - try HTML first, then XML
                                    print(f"[EXTRACTION_COMPARE] unknown content type for {scrip_code}, trying HTML first")
                                    try:
                                        tree = lxml_html.fromstring(raw_bytes)
                                        extracted_data = extract_ix_facts_from_root(tree)
                                        print(f"[EXTRACTION_COMPARE] HTML parsing succeeded - extracted {len(extracted_data)} facts for {scrip_code}")
                                    except Exception as html_error:
                                        print(f"[EXTRACTION_COMPARE] HTML parsing failed, trying XML fallback for {scrip_code}: {str(html_error)}")
                                        try:
                                            extracted_data_grouped = extract_xbrl_data_from_bytes(raw_bytes, only_prefix="in-bse-fin")
                                            extracted_data = _convert_xml_grouped_to_list(extracted_data_grouped)
                                            print(f"[EXTRACTION_COMPARE] XML fallback succeeded - extracted {len(extracted_data)} facts for {scrip_code}")
                                        except Exception:
                                            print(f"[EXTRACTION_COMPARE] both HTML and XML parsing failed for {scrip_code}")
                                            raise html_error

                                # Extract metrics from parsed content
                                print(f"[EXTRACTION_COMPARE] extracting metrics for {scrip_code}")
                                
                                # Calculate metrics based on frequency
                                if frequency == "annual":
                                    metrics = calculate_metrics_fourd(extracted_data)
                                else:
                                    metrics = calculate_metrics(extracted_data)

                                # Flatten and prepare metrics
                                flattened = _flatten_extraction_metrics(
                                    metrics, 
                                    publication_date
                                )
                                
                                # Update company payload with extracted data
                                companies_payload[scrip_code]["financials"] = [flattened]
                                companies_payload[scrip_code]["publication_date"] = publication_date
                                companies_payload[scrip_code]["report_type"] = dict(xbrl_record).get("report_type")
                                companies_payload[scrip_code]["xbrl_url"] = xbrl_link
                                companies_payload[scrip_code]["extraction"] = metrics
                                
                                print(f"[EXTRACTION_COMPARE] successfully extracted metrics for {scrip_code}")
                                
                            except Exception as e:
                                import traceback
                                print(f"[EXTRACTION_COMPARE] error parsing raw_content for {scrip_code}: {str(e)}")
                                print(f"[EXTRACTION_COMPARE] traceback: {traceback.format_exc()}")
                    else:
                        print(f"[EXTRACTION_COMPARE] no raw_content found in xbrl_filing_table for {scrip_code} with publication_date={publication_date}")
                else:
                    print(f"[EXTRACTION_COMPARE] selected record missing company_name or publication_date for {scrip_code}")
            else:
                print(f"[EXTRACTION_COMPARE] no extraction record found for {scrip_code} with period={request.period}")

        # Prepare response
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
        import traceback
        print(f"[EXTRACTION_COMPARE] traceback: {traceback.format_exc()}")
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


