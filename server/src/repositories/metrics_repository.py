"""Quarterly_Metrics / Annual_Metrics repository — Tortoise only, no JSON blobs."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from db.models import AnnualMetrics, CompanyInfo, QuarterlyMetrics


def _f(metrics: dict, *keys: str) -> Optional[float]:
    for k in keys:
        if k in metrics and metrics[k] is not None:
            try:
                return float(metrics[k])
            except (TypeError, ValueError):
                continue
    return None


async def upsert_quarterly_metrics(
    *,
    scrip_code: str,
    period: str,
    category: str = "std",
    currency: Optional[str] = None,
    level_of_rounding: Optional[str] = None,
    flat: Optional[dict] = None,
    **_ignored: Any,
) -> int:
    flat = flat or {}
    defaults = {
        "currency": currency or flat.get("currency") or flat.get("Currency"),
        "level_of_rounding": level_of_rounding
        or flat.get("level_of_rounding")
        or flat.get("Level_of_Rounding"),
        "sales": _f(flat, "sales", "Sales"),
        "exceptional_items": _f(flat, "exceptional_items", "ExceptionalItems"),
        "other_income_normal": _f(flat, "other_income_normal", "OtherIncome_normal"),
        "interest": _f(flat, "interest", "Interest"),
        "depreciation": _f(flat, "depreciation", "Depreciation"),
        "profit_before_tax": _f(flat, "profit_before_tax", "ProfitBeforeTax"),
        "profit_after_tax": _f(flat, "profit_after_tax", "ProfitAfterTax", "pat", "PAT"),
        "tax": _f(flat, "tax", "Tax"),
        "eps_in_rs": _f(flat, "eps_in_rs", "EPS_in_RS", "eps"),
        "net_profit": _f(flat, "net_profit", "NetProfit"),
        "other_income": _f(flat, "other_income", "OtherIncome"),
        "expenses": _f(flat, "expenses", "Expenses"),
        "operating_profit": _f(flat, "operating_profit", "OperatingProfit"),
        "ebitda": _f(flat, "ebitda", "EBITDA"),
        "revenue_growth_percent": _f(
            flat, "revenue_growth_percentage", "revenue_growth_percent", "RevenueGrowth_percent"
        ),
        "ebitda_margin_percent": _f(
            flat, "ebitda_margin_percentage", "ebitda_margin_percent", "EBITDA_Margin_percent"
        ),
        "ebit": _f(flat, "ebit", "EBIT"),
        "opm_percent": _f(flat, "opm_percentage", "OPM_percentage", "opm_percent"),
        "tax_percent": _f(flat, "tax_percent", "Tax_percent"),
        "net_profit_margin": _f(
            flat, "net_profit_margin_percentage", "net_profit_margin", "NetProfitMargin"
        ),
    }
    obj, created = await QuarterlyMetrics.get_or_create(
        scrip_code=str(scrip_code).strip(),
        period=str(period).strip(),
        category=(category or "std").strip().lower(),
        defaults=defaults,
    )
    if not created:
        for k, v in defaults.items():
            setattr(obj, k, v)
        await obj.save()
    return obj.id


async def upsert_annual_metrics(
    *,
    scrip_code: str,
    period: str,
    category: str = "std",
    currency: Optional[str] = None,
    level_of_rounding: Optional[str] = None,
    flat: Optional[dict] = None,
    **_ignored: Any,
) -> int:
    flat = flat or {}
    defaults = {
        "currency": currency or flat.get("currency"),
        "level_of_rounding": level_of_rounding or flat.get("level_of_rounding"),
        "sales": _f(flat, "sales", "Sales"),
        "exceptional_items": _f(flat, "exceptional_items", "ExceptionalItems"),
        "other_income_normal": _f(flat, "other_income_normal", "OtherIncome_normal"),
        "interest": _f(flat, "interest", "Interest"),
        "depreciation": _f(flat, "depreciation", "Depreciation"),
        "profit_before_tax": _f(flat, "profit_before_tax", "ProfitBeforeTax"),
        "profit_after_tax": _f(flat, "profit_after_tax", "ProfitAfterTax"),
        "tax": _f(flat, "tax", "Tax"),
        "eps_in_rs": _f(flat, "eps_in_rs", "EPS_in_RS"),
        "net_profit": _f(flat, "net_profit", "NetProfit"),
        "other_income": _f(flat, "other_income", "OtherIncome"),
        "expenses": _f(flat, "expenses", "Expenses"),
        "operating_profit": _f(flat, "operating_profit", "OperatingProfit"),
        "ebitda": _f(flat, "ebitda", "EBITDA"),
        "revenue_growth_percent": _f(
            flat, "revenue_growth_percentage", "revenue_growth_percent", "RevenueGrowth_percent"
        ),
        "ebitda_margin_percent": _f(
            flat, "ebitda_margin_percentage", "ebitda_margin_percent", "EBITDA_Margin_percent"
        ),
        "ebit": _f(flat, "ebit", "EBIT"),
        "opm_percent": _f(flat, "opm_percentage", "OPM_percentage", "opm_percent"),
        "tax_percent": _f(flat, "tax_percent", "Tax_percent"),
        "net_profit_margin": _f(
            flat, "net_profit_margin_percentage", "net_profit_margin", "NetProfitMargin"
        ),
        "dividend_paid": _f(flat, "dividend_paid", "DividendPaid"),
        "dividend_payout_percent": _f(
            flat, "dividend_payout_percent", "DividendPayout_percent"
        ),
        "equity_capital": _f(flat, "equity_capital", "EquityCapital"),
        "reserves": _f(flat, "reserves", "Reserves"),
        "total_liabilities": _f(flat, "total_liabilities", "TotalLiabilities"),
        "current_ratio": _f(flat, "current_ratio", "CurrentRatio"),
        "quick_ratio": _f(flat, "quick_ratio", "QuickRatio"),
        "total_equity": _f(flat, "total_equity", "TotalEquity"),
        "total_assets": _f(flat, "total_assets", "TotalAssets"),
        "debt_to_equity": _f(flat, "debt_to_equity", "DebtToEquity"),
        "working_capital": _f(flat, "working_capital", "WorkingCapital"),
        "cwip": _f(flat, "cwip", "CWIP"),
        "investments": _f(flat, "investments", "Investments"),
        "borrowings": _f(flat, "borrowings", "Borrowings"),
        "debt_to_assets": _f(flat, "debt_to_assets", "DebtToAssets"),
        "cash_from_operating_activity": _f(
            flat, "cash_from_operating_activity", "CashFromOperatingActivity"
        ),
        "cash_from_investing_activity": _f(
            flat, "cash_from_investing_activity", "CashFromInvestingActivity"
        ),
        "dividends_received": _f(flat, "dividends_received", "DividendsReceived"),
        "cash_from_financing_activity": _f(
            flat, "cash_from_financing_activity", "CashFromFinancingActivity"
        ),
        "cash_conversion_ratio": _f(flat, "cash_conversion_ratio", "CashConversionRatio"),
        "net_cash_flow": _f(flat, "net_cash_flow", "NetCashFlow"),
        "cfo_op": _f(flat, "cfo_op", "CFO_OP"),
        "roa": _f(flat, "roa", "ROA"),
        "roe": _f(flat, "roe", "ROE"),
        "roce_percent": _f(flat, "roce_percent", "ROCE_percent"),
        "debtor_days": _f(flat, "debtor_days", "DebtorDays"),
    }
    obj, created = await AnnualMetrics.get_or_create(
        scrip_code=str(scrip_code).strip(),
        period=str(period).strip(),
        category=(category or "std").strip().lower(),
        defaults=defaults,
    )
    if not created:
        for k, v in defaults.items():
            setattr(obj, k, v)
        await obj.save()
    return obj.id


async def insert_quarterly_extraction(
    *,
    scrip_code: str,
    company_name: Optional[str] = None,
    xbrl_link: Optional[str] = None,
    publication_date: Optional[str] = None,
    report_type: Optional[str] = None,
    parsed_json: Optional[str] = None,
    extraction_type: str = "quarterly",
    category: str = "std",
    flat: Optional[dict] = None,
) -> int:
    return await upsert_quarterly_metrics(
        scrip_code=scrip_code,
        period=publication_date or "",
        category=category if category in ("std", "con") else "std",
        flat=flat,
    )


async def insert_annual_extraction(
    *,
    scrip_code: str,
    company_name: Optional[str] = None,
    xbrl_link: Optional[str] = None,
    publication_date: Optional[str] = None,
    report_type: Optional[str] = None,
    parsed_json: Optional[str] = None,
    extraction_type: str = "annual",
    category: str = "std",
    flat: Optional[dict] = None,
) -> int:
    return await upsert_annual_metrics(
        scrip_code=scrip_code,
        period=publication_date or "",
        category=category if category in ("std", "con") else "std",
        flat=flat,
    )


async def xbrl_extraction_exists(
    scrip_code: str,
    xbrl_link: str,
    extraction_type: str = "quarterly",
) -> bool:
    from db.models import XbrlData

    filing = await XbrlData.get_or_none(scrip_code=scrip_code, xbrl_link=xbrl_link)
    if not filing:
        return False
    if extraction_type == "annual":
        return await AnnualMetrics.exists(
            scrip_code=scrip_code, period=filing.period, category=filing.category
        )
    return await QuarterlyMetrics.exists(
        scrip_code=scrip_code, period=filing.period, category=filing.category
    )


def _row_to_extraction_dict(row, extraction_type: str) -> dict:
    return {
        "id": row.id,
        "scrip_code": row.scrip_code,
        "publication_date": row.period,
        "period": row.period,
        "report_type": row.category,
        "category": row.category,
        "extraction_type": extraction_type,
        "sales": row.sales,
        "expenses": row.expenses,
        "operating_profit": row.operating_profit,
        "opm_percentage": row.opm_percent,
        "net_profit": row.net_profit,
        "eps_in_rs": row.eps_in_rs,
        "ebitda": getattr(row, "ebitda", None),
        "currency": row.currency,
        "level_of_rounding": row.level_of_rounding,
        "created_at": str(row.created_at) if row.created_at else None,
    }


async def get_latest_quarterly_data(scrip_code: str) -> Optional[dict]:
    scrip = await _resolve_scrip(scrip_code)
    row = await QuarterlyMetrics.filter(scrip_code=scrip).order_by("-id").first()
    return _row_to_extraction_dict(row, "quarterly") if row else None


async def get_latest_annual_data(scrip_code: str) -> Optional[dict]:
    scrip = await _resolve_scrip(scrip_code)
    row = await AnnualMetrics.filter(scrip_code=scrip).order_by("-id").first()
    return _row_to_extraction_dict(row, "annual") if row else None


async def get_historical_quarterly_data(scrip_code: str, limit: int = 5) -> list[dict]:
    scrip = await _resolve_scrip(scrip_code)
    rows = await QuarterlyMetrics.filter(scrip_code=scrip).order_by("-id").limit(limit)
    return [_row_to_extraction_dict(r, "quarterly") for r in rows]


async def get_historical_annual_data(scrip_code: str, limit: int = 5) -> list[dict]:
    scrip = await _resolve_scrip(scrip_code)
    rows = await AnnualMetrics.filter(scrip_code=scrip).order_by("-id").limit(limit)
    return [_row_to_extraction_dict(r, "annual") for r in rows]


async def get_extraction_records(
    scrip_code: str,
    extraction_type: str = "quarterly",
    limit: Optional[int] = None,
    time_horizon: Optional[str] = None,
) -> list[dict]:
    scrip = await _resolve_scrip(scrip_code)
    if extraction_type == "annual":
        qs = AnnualMetrics.filter(scrip_code=scrip).order_by("-id")
        et = "annual"
    else:
        qs = QuarterlyMetrics.filter(scrip_code=scrip).order_by("-id")
        et = "quarterly"
    if limit:
        qs = qs.limit(limit)
    rows = await qs
    results = [_row_to_extraction_dict(r, et) for r in rows]
    if time_horizon:
        results = _filter_time_horizon(results, time_horizon)
    return results


async def get_latest_extraction(scrip_code: str, extraction_type: str) -> Optional[dict]:
    if extraction_type == "annual":
        return await get_latest_annual_data(scrip_code)
    return await get_latest_quarterly_data(scrip_code)


async def get_historical_extractions(
    scrip_code: str, extraction_type: str, limit: int = 5
) -> list[dict]:
    if extraction_type == "annual":
        return await get_historical_annual_data(scrip_code, limit)
    return await get_historical_quarterly_data(scrip_code, limit)


async def _resolve_scrip(code_or_symbol: str) -> str:
    code = str(code_or_symbol).strip()
    if await QuarterlyMetrics.exists(scrip_code=code) or await AnnualMetrics.exists(scrip_code=code):
        return code
    co = await CompanyInfo.get_or_none(symbol__iexact=code)
    if co:
        return co.scrip_code
    co = await CompanyInfo.get_or_none(scrip_code=code)
    return co.scrip_code if co else code


def _filter_time_horizon(rows: list[dict], time_horizon: str) -> list[dict]:
    th = (time_horizon or "").lower().strip()
    if not th or th in ("all", "everything"):
        return rows
    now = datetime.utcnow()
    filtered = []
    for r in rows:
        period = r.get("period") or r.get("publication_date") or ""
        years = [int(y) for y in re.findall(r"20\d{2}", str(period))]
        if not years:
            filtered.append(r)
            continue
        max_y = max(years)
        if "latest" in th or "current" in th:
            if max_y >= now.year - 1:
                filtered.append(r)
        elif "3" in th:
            if max_y >= now.year - 3:
                filtered.append(r)
        elif "5" in th:
            if max_y >= now.year - 5:
                filtered.append(r)
        else:
            filtered.append(r)
    return filtered
