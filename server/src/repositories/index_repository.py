"""Index membership repository (replaces nifty_500_list)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from db.models import CompanyInfo, IndexMembership, XbrlData


async def get_nifty500_last_updated() -> Optional[datetime]:
    row = await IndexMembership.filter(index_name__iexact="nifty500").order_by("-timestamp_date").first()
    return row.timestamp_date if row else None


async def replace_nifty500_rows(rows: list[dict], updated_at: str) -> int:
    """Replace all nifty500 index memberships from CSV-like rows."""
    await IndexMembership.filter(index_name__iexact="nifty500").delete()
    created = 0
    ts = None
    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00")) if updated_at else datetime.utcnow()
    except Exception:
        ts = datetime.utcnow()

    for r in rows:
        scrip = str(r.get("scrip_code") or r.get("Scrip Code") or "").strip()
        if not scrip:
            continue
        name = r.get("company_name") or r.get("Company Name") or scrip
        symbol = r.get("symbol") or r.get("Symbol")
        industry = r.get("industry") or r.get("Industry")
        isin = r.get("isin_code") or r.get("ISIN Code") or r.get("isin_no")

        from repositories.company_repository import upsert_company

        company = await upsert_company(
            company_name=name,
            symbol=symbol,
            scrip_code=scrip,
            isin_no=isin,
            industry=industry,
        )
        await IndexMembership.create(
            company=company,
            scrip_code=scrip,
            index_name="nifty500",
            timestamp_date=ts,
        )
        created += 1
    return created


async def get_all_nifty500() -> list[dict]:
    rows = await IndexMembership.filter(index_name__iexact="nifty500").prefetch_related("company")
    out = []
    for r in rows:
        co = r.company
        out.append(
            {
                "scrip_code": r.scrip_code,
                "company_name": co.company_name if co else None,
                "symbol": co.symbol if co else None,
                "isin_code": co.isin_no if co else None,
                "index_name": r.index_name,
                "updated_at": str(r.timestamp_date) if r.timestamp_date else None,
            }
        )
    return out


async def get_scrip_codes_missing_fiscal_year(
    fiscal_year_label: str,
    scrip_codes: Optional[List[str]] = None,
) -> list[str]:
    """
    Return scrip codes that lack an XBRL_Data row whose period contains the fiscal year label.
    fiscal_year_label e.g. '2025-2026' or 'FY2025'.
    """
    if scrip_codes is None:
        memberships = await IndexMembership.filter(index_name__iexact="nifty500")
        scrip_codes = [m.scrip_code for m in memberships]
    missing = []
    needle = str(fiscal_year_label).strip()
    for scrip in scrip_codes:
        has = await XbrlData.filter(scrip_code=scrip, period__contains=needle).exists()
        if not has:
            # Also try year fragments
            years = [y for y in needle.replace("FY", "").split("-") if y.isdigit()]
            found = False
            for y in years:
                if await XbrlData.filter(scrip_code=scrip, period__contains=y).exists():
                    # Prefer annual (ends with C) for FY coverage
                    annual = await XbrlData.filter(
                        scrip_code=scrip, period__contains=y, period__endswith="C"
                    ).exists()
                    if annual or not years:
                        found = True
                        break
            if not found:
                missing.append(scrip)
    return missing
