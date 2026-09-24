"""XBRL_Data repository — Tortoise only, no raw SQL."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, List, Optional

from db.models import CompanyInfo, XbrlData


async def upsert_xbrl_filing(
    *,
    scrip_code: str,
    period: str,
    xbrl_link: str,
    category: str = "std",
    metrics_json: Optional[str] = None,
    symbol: Optional[str] = None,  # compat; ignored for XBRL_Data
) -> int:
    cat = (category or "std").strip().lower()
    obj, created = await XbrlData.get_or_create(
        scrip_code=str(scrip_code).strip(),
        period=str(period).strip(),
        category=cat,
        defaults={
            "xbrl_link": xbrl_link,
            "metrics_json": metrics_json,
        },
    )
    if not created:
        obj.xbrl_link = xbrl_link
        if metrics_json is not None:
            obj.metrics_json = metrics_json
        await obj.save()
    return obj.id


# Alias matching old SqliteRepository method name
async def insert_xbrl_filing(
    *,
    scrip_code: str,
    symbol: Optional[str] = None,
    xbrl_link: str,
    publication_date: Optional[str] = None,
    report_type: Optional[str] = None,
    raw_content: Optional[str] = None,  # ignored — files on disk
    category: Optional[str] = None,
    period: Optional[str] = None,
) -> int:
    """Insert/upsert XBRL_Data row. publication_date maps to period; report_type/category map to category."""
    cat = (category or report_type or "std").strip().lower()
    if cat in ("quarterly", "annual", "std", "con"):
        if cat not in ("std", "con"):
            cat = "std"
    else:
        cat = "std" if cat != "con" else "con"
    # Old code used report_type as "std"/"con" or "quarterly"/"annual"
    if report_type and report_type.lower() in ("std", "con"):
        cat = report_type.lower()
    if category and category.lower() in ("std", "con"):
        cat = category.lower()
    per = (period or publication_date or "").strip()
    return await upsert_xbrl_filing(
        scrip_code=scrip_code,
        period=per,
        xbrl_link=xbrl_link,
        category=cat,
        symbol=symbol,
    )


async def xbrl_filing_exists(
    scrip_code: str,
    xbrl_link: str,
    report_type: Optional[str] = None,
    publication_date: Optional[str] = None,
) -> bool:
    qs = XbrlData.filter(scrip_code=str(scrip_code).strip(), xbrl_link=xbrl_link)
    if publication_date:
        qs = qs.filter(period=publication_date)
    if report_type and report_type.lower() in ("std", "con"):
        qs = qs.filter(category=report_type.lower())
    return await qs.exists()


async def get_xbrl_filing_id(
    scrip_code: str,
    xbrl_link: str,
    report_type: Optional[str] = None,
) -> Optional[int]:
    qs = XbrlData.filter(scrip_code=str(scrip_code).strip(), xbrl_link=xbrl_link)
    if report_type and report_type.lower() in ("std", "con"):
        qs = qs.filter(category=report_type.lower())
    row = await qs.first()
    return row.id if row else None


async def get_xbrl_filings(scrip_code: Optional[str] = None) -> list[dict]:
    qs = XbrlData.all()
    if scrip_code:
        qs = qs.filter(scrip_code=str(scrip_code).strip())
    rows = await qs.order_by("-id")
    return [_to_dict(r) for r in rows]


async def get_xbrl_filings_with_company_and_content() -> list[dict]:
    """Join company info; raw content is NOT in DB — callers read from file store."""
    rows = await XbrlData.all().order_by("scrip_code", "-id")
    out = []
    for r in rows:
        company = await CompanyInfo.get_or_none(scrip_code=r.scrip_code)
        d = _to_dict(r)
        d["company_name"] = company.company_name if company else None
        d["symbol"] = company.symbol if company else None
        d["report_type"] = r.category
        d["publication_date"] = r.period
        # raw_content intentionally absent — use xbrl_file_store
        out.append(d)
    return out


async def get_xbrl_filings_by_scrip_codes(scrip_codes: List[str]) -> list[dict]:
    if not scrip_codes:
        return []
    rows = await XbrlData.filter(scrip_code__in=[str(s) for s in scrip_codes])
    return [_to_dict(r) for r in rows]


async def get_xbrl_filings_count(scrip_code: str) -> int:
    return await XbrlData.filter(scrip_code=str(scrip_code).strip()).count()


async def get_period_by_xbrl_link(xbrl_link: str) -> Optional[str]:
    row = await XbrlData.get_or_none(xbrl_link=xbrl_link)
    return row.period if row else None


async def xbrl_filing_recent(scrip_code: str, days: int = 10) -> bool:
    cutoff = datetime.utcnow() - timedelta(days=days)
    return await XbrlData.filter(
        scrip_code=str(scrip_code).strip(),
        created_at__gte=cutoff,
    ).exists()


async def update_metrics_json(
    scrip_code: str,
    period: str,
    category: str,
    metrics_json: Any,
) -> Optional[int]:
    row = await XbrlData.get_or_none(
        scrip_code=str(scrip_code).strip(),
        period=str(period).strip(),
        category=(category or "std").strip().lower(),
    )
    if not row:
        return None
    if not isinstance(metrics_json, str):
        metrics_json = json.dumps(metrics_json, ensure_ascii=False, separators=(",", ":"))
    row.metrics_json = metrics_json
    await row.save()
    return row.id


def _to_dict(r: XbrlData) -> dict:
    return {
        "id": r.id,
        "scrip_code": r.scrip_code,
        "period": r.period,
        "publication_date": r.period,
        "xbrl_link": r.xbrl_link,
        "category": r.category,
        "report_type": r.category,
        "metrics_json": r.metrics_json,
        "parsed_json": r.metrics_json,
        "created_at": str(r.created_at) if r.created_at else None,
        "symbol": None,
        "raw_content": None,
    }
