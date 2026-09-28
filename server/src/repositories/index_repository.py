"""Nifty-500 membership via company_info.is_in_nifty_500 (Indexes table removed)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from db.models import CompanyInfo, XbrlData


async def get_nifty500_last_updated() -> Optional[datetime]:
    row = await CompanyInfo.filter(is_in_nifty_500="T").order_by("-nifty500_updated_at").first()
    return row.nifty500_updated_at if row else None


async def replace_nifty500_rows(rows: list[dict], updated_at: str) -> int:
    """
    Nifty-500 refresh:
      1. Caller downloads the list.
      2. Set every company_info.is_in_nifty_500 = 'F'.
      3. For each row in the list: upsert into company_info (add if missing) and set 'T' + timestamp.
    """
    created = 0
    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00")) if updated_at else datetime.utcnow()
    except Exception:
        ts = datetime.utcnow()

    # Step 2 — clear membership for everyone
    await CompanyInfo.all().update(is_in_nifty_500="F")

    from repositories.company_repository import upsert_company

    for r in rows:
        scrip = str(r.get("scrip_code") or r.get("Scrip Code") or "").strip()
        name = (r.get("company_name") or r.get("Company Name") or "").strip()
        symbol = (r.get("symbol") or r.get("Symbol") or "").strip() or None
        industry = (r.get("industry") or r.get("Industry") or "").strip() or None
        isin = (
            r.get("isin_code") or r.get("ISIN Code") or r.get("isin_no") or ""
        )
        isin = str(isin).strip() or None

        company = None
        if scrip:
            company = await upsert_company(
                company_name=name or symbol or scrip,
                symbol=symbol,
                scrip_code=scrip,
                isin_no=isin,
                industry=industry,
            )
        else:
            # No BSE scrip from Validation.csv — still put the Nifty name into company_info.
            if isin:
                company = await CompanyInfo.get_or_none(isin_no=isin)
            if not company and symbol:
                company = await CompanyInfo.filter(symbol__iexact=symbol).first()
            if not company and symbol:
                company = await upsert_company(
                    company_name=name or symbol,
                    symbol=symbol,
                    scrip_code=symbol,
                    isin_no=isin,
                    industry=industry,
                )
            elif company:
                if name:
                    company.company_name = name
                if symbol:
                    company.symbol = symbol
                if isin:
                    company.isin_no = isin
                await company.save()

        if not company:
            continue

        company.is_in_nifty_500 = "T"
        company.nifty500_updated_at = ts
        await company.save(update_fields=["is_in_nifty_500", "nifty500_updated_at"])
        created += 1
    return created


async def get_all_nifty500() -> list[dict]:
    rows = await CompanyInfo.filter(is_in_nifty_500="T").prefetch_related("industry")
    out = []
    for co in rows:
        out.append(
            {
                "scrip_code": co.scrip_code,
                "company_name": co.company_name,
                "symbol": co.symbol,
                "isin_code": co.isin_no,
                "index_name": "nifty500",
                "updated_at": str(co.nifty500_updated_at) if co.nifty500_updated_at else None,
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
        companies = await CompanyInfo.filter(is_in_nifty_500="T")
        scrip_codes = [c.scrip_code for c in companies]
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
