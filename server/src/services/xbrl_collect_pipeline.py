"""
Shared XBRL collect + extract pipeline used by Fetch Filings, missing-companies, etc.

Rules:
1. Upsert company_info BEFORE collecting filings for that company.
2. Collect both std and con; keep existing H/N skip + fiscal-range early-exit.
3. On each stored filing, parse HTML/XML and write Quarterly_Metrics / Annual_Metrics.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from lxml import etree as ET
from lxml import html as lxml_html

from repositories.sqlite_repository import SqliteRepository
from repositories.xbrl_repository import update_metrics_json
from services.html_extraction_service import extract_ix_facts_from_root
from services.html_parser_service import html_dom_to_structured_json_from_content
from services.xbrl_file_store import save_xbrl_raw
from services.xbrl_metrics_service import (
    calculate_metrics,
    calculate_metrics_fourd,
    convert_xml_grouped_to_list,
)
from services.xml_extraction_service import extract_xbrl_data_from_bytes
from utils.fiscal_year import is_within_collection_range


def normalize_category(xbrl_type: Optional[str]) -> str:
    cat = (xbrl_type or "std").strip().lower()
    return cat if cat in ("std", "con") else "std"


def determine_extraction_type(period: Optional[str]) -> str:
    """Q in second char → quarterly; C → annual; else infer from tokens."""
    if not period:
        return "quarterly"
    p = str(period).strip()
    if len(p) >= 2 and p[1].upper() == "C":
        return "annual"
    if len(p) >= 2 and p[1].upper() == "Q":
        return "quarterly"
    low = p.lower()
    if any(tok in low for tok in ("q1", "q2", "q3", "q4", "quarter", "qtr")):
        return "quarterly"
    return "annual"


def is_html_content(raw_text: str, url: str = "") -> bool:
    preview = (raw_text or "").lstrip()[:1024].lower()
    u = (url or "").lower()
    return (
        u.endswith(".html")
        or u.endswith(".htm")
        or "<html" in preview
        or "<!doctype html" in preview
        or "<body" in preview
        or "<ix:" in preview
    )


def _fact_list_from_html(raw_bytes: bytes) -> list:
    """Extract iXBRL facts from HTML when possible."""
    try:
        root = lxml_html.fromstring(raw_bytes)
        rows = extract_ix_facts_from_root(root)
        # normalize keys for metrics calculator
        out = []
        for r in rows or []:
            out.append(
                {
                    "localname": str(r.get("localname") or "").lower(),
                    "contextRef": r.get("contextref") or r.get("contextRef"),
                    "contextref": r.get("contextref") or r.get("contextRef"),
                    "value": r.get("value"),
                }
            )
        return out
    except Exception as exc:
        print(f"[xbrl_pipeline] ix facts from html failed: {exc}")
        return []


def parse_and_compute_metrics(
    raw_text: str,
    url: str,
    extraction_type: str,
) -> Tuple[Any, Optional[dict], Optional[list]]:
    """
    Returns (parsed_json_for_storage, flat_metrics_dict, fact_list_or_none).
    """
    raw_bytes = raw_text.encode("utf-8") if isinstance(raw_text, str) else raw_text
    flat: Optional[dict] = None
    fact_list: Optional[list] = None

    if is_html_content(raw_text, url):
        parsed_json = html_dom_to_structured_json_from_content(raw_bytes)
        fact_list = _fact_list_from_html(raw_bytes)
        if not fact_list:
            # Try XML/iXBRL walk on same bytes
            try:
                grouped = extract_xbrl_data_from_bytes(raw_bytes, only_prefix="in-bse-fin")
                fact_list = convert_xml_grouped_to_list(grouped)
            except Exception:
                fact_list = []
    else:
        grouped = extract_xbrl_data_from_bytes(raw_bytes, only_prefix="in-bse-fin")
        parsed_json = grouped
        fact_list = convert_xml_grouped_to_list(grouped)

    if fact_list:
        if extraction_type == "annual":
            flat = calculate_metrics_fourd(fact_list)
        else:
            flat = calculate_metrics(fact_list)

    return parsed_json, flat, fact_list


def flat_to_quarterly_kwargs(flat: Optional[dict]) -> dict:
    if not flat:
        return {}
    return {
        "sales": flat.get("Sales"),
        "exceptional_items": flat.get("ExceptionalItems"),
        "other_income_normal": flat.get("OtherIncome_normal"),
        "interest": flat.get("Interest"),
        "depreciation": flat.get("Depreciation"),
        "profit_before_tax": flat.get("ProfitBeforeTax"),
        "profit_after_tax": flat.get("ProfitAfterTax"),
        "tax": flat.get("Tax"),
        "eps_in_rs": flat.get("EPS_in_RS"),
        "net_profit": flat.get("NetProfit"),
        "other_income": flat.get("OtherIncome"),
        "expenses": flat.get("Expenses"),
        "operating_profit": flat.get("OperatingProfit"),
        "ebitda": flat.get("EBITDA"),
        "revenue_growth_percent": flat.get("RevenueGrowth_percent"),
        "ebitda_margin_percent": flat.get("EBITDA_Margin_percent"),
        "ebit": flat.get("EBIT"),
        "opm_percent": flat.get("OPM_percentage"),
        "tax_percent": flat.get("Tax_percent"),
        "net_profit_margin": flat.get("NetProfitMargin"),
        "currency": flat.get("currency"),
        "level_of_rounding": flat.get("level_of_rounding"),
    }


def flat_to_annual_kwargs(flat: Optional[dict]) -> dict:
    """Map calculate_metrics_fourd output → Annual_Metrics columns."""
    if not flat:
        return {}
    base = flat_to_quarterly_kwargs(flat)
    base.update(
        {
            "dividend_paid": flat.get("DividendPaid"),
            "dividend_payout_percent": flat.get("DividendPayout_percent"),
            "equity_capital": flat.get("EquityCapital"),
            "reserves": flat.get("Reserves"),
            "total_liabilities": flat.get("TotalLiabilities"),
            "current_ratio": flat.get("CurrentRatio"),
            "quick_ratio": flat.get("QuickRatio"),
            "total_equity": flat.get("TotalEquity"),
            "total_assets": flat.get("TotalAssets"),
            "debt_to_equity": flat.get("DebtToEquity"),
            "working_capital": flat.get("WorkingCapital"),
            "cwip": flat.get("CWIP"),
            "investments": flat.get("Investments"),
            "borrowings": flat.get("Borrowings"),
            "debt_to_assets": flat.get("DebtToAssets"),
            "cash_from_operating_activity": flat.get("CashFromOperatingActivity"),
            "cash_from_investing_activity": flat.get("CashFromInvestingActivity"),
            "dividends_received": flat.get("DividendsReceived"),
            "cash_from_financing_activity": flat.get("CashFromFinancingActivity"),
            "cash_conversion_ratio": flat.get("CashConversionRatio"),
            "net_cash_flow": flat.get("NetCashFlow"),
            "cfo_op": flat.get("CFO_OP"),
            "roa": flat.get("ROA"),
            "roe": flat.get("ROE"),
            "roce_percent": flat.get("ROCE_percent"),
            "debtor_days": flat.get("DebtorDays"),
        }
    )
    return base


async def ensure_company_before_collect(
    repo: SqliteRepository,
    *,
    scrip_code: str,
    company_name: Optional[str] = None,
    symbol: Optional[str] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    isin_no: Optional[str] = None,
) -> dict:
    """
    STRICT: persist company_info BEFORE any XBRL collection for this scrip.
    Returns the upserted company dict. Raises if scrip_code missing.
    """
    code = str(scrip_code or "").strip()
    if not code:
        raise ValueError("scrip_code is required before XBRL collection")
    company = await repo.upsert_company(
        company_name=company_name or symbol or code,
        symbol=symbol,
        scrip_code=code,
        sector=sector,
        industry=industry,
        isin_no=isin_no,
    )
    # Confirm row exists before caller starts scrape/store
    exists = await repo.company_exists(code)
    if not exists:
        raise RuntimeError(f"company_info insert failed for scrip_code={code}")
    print(
        f"[xbrl_pipeline] company_info ready scrip={code} "
        f"name={company_name or symbol} — starting XBRL collection"
    )
    if hasattr(company, "scrip_code"):
        return {
            "scrip_code": company.scrip_code,
            "company_name": getattr(company, "company_name", company_name),
            "symbol": getattr(company, "symbol", symbol),
        }
    return {"scrip_code": code, "company_name": company_name, "symbol": symbol}


async def store_filing_and_extract(
    repo: SqliteRepository,
    *,
    scrip_code: str,
    symbol: Optional[str],
    company_name: Optional[str],
    xbrl_url: str,
    period: str,
    xbrl_type: str,
    raw_content: str,
    industry: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Save raw file → upsert XBRL_Data → parse → update metrics_json →
    upsert Quarterly_Metrics or Annual_Metrics.
    """
    result: Dict[str, Any] = {
        "scrip_code": scrip_code,
        "period": period,
        "category": None,
        "filing_id": None,
        "stored_filing": False,
        "extracted": False,
        "extraction_type": None,
        "error": None,
    }
    if not raw_content:
        result["error"] = "no raw content"
        return result

    category = normalize_category(xbrl_type)
    result["category"] = category
    raw_text = raw_content if isinstance(raw_content, str) else str(raw_content)

    if industry and industry.strip():
        # Industry refresh only — company_info row must already exist from ensure_company_before_collect
        await repo.upsert_company(
            company_name=company_name or symbol or scrip_code,
            symbol=symbol,
            scrip_code=str(scrip_code).strip(),
            industry=industry.strip(),
            sector=industry.strip(),
        )

    save_xbrl_raw(scrip_code, category, period, raw_text, xbrl_url)
    filing_id = await repo.insert_xbrl_filing(
        scrip_code=scrip_code,
        symbol=symbol,
        xbrl_link=xbrl_url,
        publication_date=period,
        report_type=category,
        category=category,
        period=period,
    )
    result["filing_id"] = filing_id
    result["stored_filing"] = True

    extraction_type = determine_extraction_type(period)
    result["extraction_type"] = extraction_type

    try:
        parsed_json, flat, _facts = parse_and_compute_metrics(raw_text, xbrl_url, extraction_type)
        parsed_json_str = json.dumps(parsed_json, ensure_ascii=False, separators=(",", ":"))
        await update_metrics_json(
            scrip_code=scrip_code,
            period=period,
            category=category,
            metrics_json=parsed_json_str,
        )
        if extraction_type == "annual":
            annual_flat = {**(flat or {}), **flat_to_annual_kwargs(flat)}
            await repo.insert_annual_extraction(
                scrip_code=scrip_code,
                company_name=company_name,
                xbrl_link=xbrl_url,
                publication_date=period,
                report_type=category,
                category=category,
                parsed_json=parsed_json_str,
                flat=annual_flat,
            )
        else:
            q_flat = {**(flat or {}), **flat_to_quarterly_kwargs(flat)}
            await repo.insert_quarterly_extraction(
                scrip_code=scrip_code,
                company_name=company_name,
                xbrl_link=xbrl_url,
                publication_date=period,
                report_type=category,
                category=category,
                parsed_json=parsed_json_str,
                flat=q_flat or flat,
            )
        result["extracted"] = True
    except Exception as exc:
        result["error"] = f"extract_failed: {exc}"
        print(f"[xbrl_pipeline] extract failed {scrip_code} {period}: {exc}")

    return result


def period_out_of_range_should_halt(consecutive_out_of_range: int, threshold: int = 2) -> bool:
    return consecutive_out_of_range >= threshold


# Re-export for call sites that previously imported from fiscal_year via local alias
is_within_range = is_within_collection_range
