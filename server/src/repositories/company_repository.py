"""Async Tortoise repositories for company_info + Industry."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.company import Company, YearlyFinancials
from db.models import AnnualMetrics, CompanyInfo, Industry, QuarterlyMetrics


async def get_or_create_industry(name: Optional[str]) -> Optional[Industry]:
    if not name or not str(name).strip():
        return None
    industry, _ = await Industry.get_or_create(industry_name=str(name).strip())
    return industry


async def upsert_company(
    *,
    company_name: Optional[str] = None,
    symbol: Optional[str] = None,
    scrip_code: str,
    isin_no: Optional[str] = None,
    industry: Optional[str] = None,
    sector: Optional[str] = None,  # accepted for compat; stored via Industry
) -> CompanyInfo:
    industry_name = industry or sector
    ind = await get_or_create_industry(industry_name)
    existing = await CompanyInfo.get_or_none(scrip_code=str(scrip_code).strip())
    if existing:
        if company_name:
            existing.company_name = company_name
        if symbol is not None:
            existing.symbol = symbol
        if isin_no is not None:
            existing.isin_no = isin_no
        if ind is not None:
            existing.industry = ind
        await existing.save()
        return existing
    return await CompanyInfo.create(
        company_name=company_name or symbol or scrip_code,
        symbol=symbol,
        scrip_code=str(scrip_code).strip(),
        isin_no=isin_no,
        industry=ind,
    )


async def company_exists(scrip_code: str) -> bool:
    return await CompanyInfo.exists(scrip_code=str(scrip_code).strip())


async def get_all_companies() -> List[dict]:
    rows = await CompanyInfo.all().prefetch_related("industry").order_by("company_name")
    return [_company_to_dict(r) for r in rows]


async def search_companies(query: str) -> List[Company]:
    if not query or len(query) < 1:
        return []
    q = query.strip()
    rows = await CompanyInfo.filter(
        company_name__icontains=q
    ).prefetch_related("industry").order_by("symbol")
    # Also match symbol / scrip
    extra = await CompanyInfo.filter(
        symbol__icontains=q
    ).prefetch_related("industry")
    extra2 = await CompanyInfo.filter(
        scrip_code__icontains=q
    ).prefetch_related("industry")
    by_id = {}
    for r in list(rows) + list(extra) + list(extra2):
        by_id[r.id] = r
    return [_to_pydantic(r) for r in by_id.values()]


async def get_all_companies_pydantic() -> List[Company]:
    rows = await CompanyInfo.all().prefetch_related("industry").order_by("company_name")
    return [_to_pydantic(r) for r in rows]


async def get_company_by_id(company_id: str) -> Optional[Company]:
    if not company_id:
        return None
    row = None
    if str(company_id).isdigit():
        row = await CompanyInfo.filter(id=int(company_id)).prefetch_related("industry").first()
    if not row:
        row = await CompanyInfo.filter(symbol__iexact=company_id).prefetch_related("industry").first()
    if not row:
        row = await CompanyInfo.filter(scrip_code__iexact=company_id).prefetch_related("industry").first()
    return _to_pydantic(row) if row else None


async def get_company_financials(company_id: str, years: Optional[int] = None) -> List[YearlyFinancials]:
    company = await get_company_by_id(company_id)
    if not company or not company.bse_code:
        return []
    scrip = company.bse_code
    rows = await AnnualMetrics.filter(scrip_code=scrip).order_by("-id")
    if not rows:
        rows = await QuarterlyMetrics.filter(scrip_code=scrip).order_by("-id")
    financials: List[YearlyFinancials] = []
    for row in rows:
        financials.append(
            YearlyFinancials(
                year=str(row.period or "N/A"),
                sales=float(row.sales or 0.0),
                ebitda=float(getattr(row, "ebitda", None) or 0.0),
                opm=float(getattr(row, "opm_percent", None) or 0.0),
                pat=float(row.net_profit or getattr(row, "profit_after_tax", None) or 0.0),
                eps=float(row.eps_in_rs or 0.0),
                roce=float(getattr(row, "roce_percent", None) or 0.0),
                de=float(getattr(row, "debt_to_equity", None) or 0.0),
                cfo=float(getattr(row, "cash_from_operating_activity", None) or 0.0),
            )
        )
    if years and len(financials) > years:
        financials = financials[:years]
    return financials


async def get_trending_companies(limit: int = 4) -> List[Company]:
    # Prefer companies that have annual sales metrics
    annuals = await AnnualMetrics.filter(sales__isnull=False).order_by("-sales").limit(limit * 3)
    seen = set()
    result: List[Company] = []
    for a in annuals:
        if a.scrip_code in seen:
            continue
        seen.add(a.scrip_code)
        co = await CompanyInfo.filter(scrip_code=a.scrip_code).prefetch_related("industry").first()
        if co:
            result.append(_to_pydantic(co))
        if len(result) >= limit:
            return result
    if len(result) < limit:
        for co in await CompanyInfo.all().prefetch_related("industry").order_by("company_name").limit(limit):
            if co.scrip_code not in seen:
                result.append(_to_pydantic(co))
            if len(result) >= limit:
                break
    return result


async def get_companies_with_latest_financials(
    scrip_codes: List[str], frequency: str = "annual"
) -> List[Dict[str, Any]]:
    is_quarterly = frequency.lower() == "quarterly"
    out: List[Dict[str, Any]] = []
    for scrip_code in scrip_codes:
        company = await CompanyInfo.filter(scrip_code=scrip_code).prefetch_related("industry").first()
        if not company:
            continue
        industry_name = company.industry.industry_name if company.industry else None
        if is_quarterly:
            fin = await QuarterlyMetrics.filter(scrip_code=scrip_code).order_by("-id").first()
        else:
            fin = await AnnualMetrics.filter(scrip_code=scrip_code).order_by("-id").first()
        if not fin:
            continue
        item: Dict[str, Any] = {
            "scrip_code": scrip_code,
            "company_name": company.company_name,
            "symbol": company.symbol,
            "sector": industry_name,
            "industry": industry_name,
            "sales": fin.sales,
            "expenses": fin.expenses,
            "operating_profit": fin.operating_profit,
            "opm": fin.opm_percent,
            "pat": fin.net_profit or getattr(fin, "profit_after_tax", None),
            "eps": fin.eps_in_rs,
            "equity": getattr(fin, "equity_capital", None),
            "total_assets": getattr(fin, "total_assets", None),
            "borrowings": getattr(fin, "borrowings", None),
            "cfo": getattr(fin, "cash_from_operating_activity", None),
            "date": str(fin.created_at) if fin.created_at else None,
        }
        out.append(item)
    return out


async def delete_companies_by_sector(sector: str) -> int:
    industries = await Industry.filter(industry_name__iexact=sector)
    if not industries:
        return 0
    ids = [i.id for i in industries]
    deleted = await CompanyInfo.filter(industry_id__in=ids).delete()
    return deleted


async def find_peers(symbol: str) -> dict:
    """Peers = other companies in same industry."""
    company = await CompanyInfo.filter(symbol__iexact=symbol).prefetch_related("industry").first()
    if not company or not company.industry_id:
        return {"symbol": symbol, "peers": []}
    peers = await CompanyInfo.filter(industry_id=company.industry_id).exclude(id=company.id)
    return {
        "symbol": symbol,
        "industry": company.industry.industry_name if company.industry else None,
        "peers": [_company_to_dict(p) for p in peers],
    }


def _company_to_dict(row: CompanyInfo) -> dict:
    industry_name = None
    try:
        if row.industry:
            industry_name = row.industry.industry_name
    except Exception:
        industry_name = None
    return {
        "id": row.id,
        "company_name": row.company_name,
        "symbol": row.symbol,
        "scrip_code": row.scrip_code,
        "isin_no": row.isin_no,
        "sector": industry_name,
        "industry": industry_name,
    }


def _to_pydantic(row: CompanyInfo) -> Company:
    d = _company_to_dict(row)
    return Company(
        id=str(d["id"]),
        name=d["company_name"] if d["company_name"] and str(d["company_name"]).strip() else (d["symbol"] or ""),
        symbol=d["symbol"] or "",
        bse_code=d["scrip_code"] or "",
        sector=d["sector"] or "Unknown Sector",
        industry=d["industry"] or "Unknown Industry",
        xbrl_link="",
        financials=[],
    )


# Sync-style facade used by CompanyService (async methods called via asyncio)
class CompanyRepository:
    """Thin facade; prefer module-level async functions for new code."""

    async def search_companies(self, query: str) -> List[Company]:
        return await search_companies(query)

    async def get_all_companies(self) -> List[Company]:
        return await get_all_companies_pydantic()

    async def get_company_by_id(self, company_id: str) -> Optional[Company]:
        return await get_company_by_id(company_id)

    async def get_company_financials(self, company_id: str, years: Optional[int] = None) -> List[YearlyFinancials]:
        return await get_company_financials(company_id, years)

    async def get_trending_companies(self, limit: int = 4) -> List[Company]:
        return await get_trending_companies(limit)

    async def get_latest_quarterly_data(self, symbol: str) -> Optional[dict]:
        from repositories.metrics_repository import get_latest_quarterly_data
        return await get_latest_quarterly_data(symbol)

    async def get_latest_annual_data(self, symbol: str) -> Optional[dict]:
        from repositories.metrics_repository import get_latest_annual_data
        return await get_latest_annual_data(symbol)

    async def get_companies_with_latest_financials(
        self, scrip_codes: List[str], frequency: str = "annual"
    ) -> List[Dict[str, Any]]:
        return await get_companies_with_latest_financials(scrip_codes, frequency)
