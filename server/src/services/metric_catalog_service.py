"""
Compute Quarterly / Annual metric flats from Metrics.ind_as catalog.

ind_as may be:
  - an IND-AS XBRL localname, e.g. RevenueFromOperations
  - a formula using particulars aliases or XBRL names, e.g. Sales-Expenses, (EBITDA/Sales)*100
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from db.models import MetricDefinition

# particulars → flat dict key used by metrics_repository / pipeline
PARTICULARS_TO_FLAT: Dict[str, str] = {
    "Sales": "Sales",
    "Exceptional items": "ExceptionalItems",
    "Other Income_normal": "OtherIncome_normal",
    "Interest": "Interest",
    "Depreciation": "Depreciation",
    "Profit before tax": "ProfitBeforeTax",
    "Profit After Tax": "ProfitAfterTax",
    "Tax": "Tax",
    "EPS in Rs": "EPS_in_RS",
    "Net Profit": "NetProfit",
    "Other Income": "OtherIncome",
    "Expenses": "Expenses",
    "Operating Profit": "OperatingProfit",
    "EBITDA": "EBITDA",
    "Revenue Growth %": "RevenueGrowth_percent",
    "EBITDA Margin %": "EBITDA_Margin_percent",
    "EBIT": "EBIT",
    "OPM %": "OPM_percentage",
    "Tax %": "Tax_percent",
    "Net Profit Margin": "NetProfitMargin",
    "Divident Paid": "DividendPaid",
    "Divident Payout %": "DividendPayout_percent",
    "Equity Capital": "EquityCapital",
    "Reserves": "Reserves",
    "Total Liabilities": "TotalLiabilities",
    "Current Ratio": "CurrentRatio",
    "Quick Ratio": "QuickRatio",
    "Total Equity": "TotalEquity",
    "Total Assets": "TotalAssets",
    "Debt-to-Equity": "DebtToEquity",
    "Working capital": "WorkingCapital",
    "CWIP": "CWIP",
    "Investments": "Investments",
    "Borrowings": "Borrowings",
    "Debt-to-Assets": "DebtToAssets",
    "Cash from Operating Activity": "CashFromOperatingActivity",
    "Cash from Investing Activity": "CashFromInvestingActivity",
    "Dividends received": "DividendsReceived",
    "Cash from Financing Activity": "CashFromFinancingActivity",
    "Cash Conversion Ratio": "CashConversionRatio",
    "Net Cash Flow": "NetCashFlow",
    "CFO/OP": "CFO_OP",
    "ROA": "ROA",
    "ROE": "ROE",
    "ROCE %": "ROCE_percent",
    "Debtor Days": "DebtorDays",
}

# Extra aliases so formulas like sales-expenses or ExceptionalItems resolve
_ALIAS_TO_FLAT: Dict[str, str] = {}
for _part, _flat in PARTICULARS_TO_FLAT.items():
    _ALIAS_TO_FLAT[_flat.lower()] = _flat
    _ALIAS_TO_FLAT[_part.lower().replace(" ", "").replace("_", "").replace("%", "").replace("-", "")] = _flat
    _ALIAS_TO_FLAT[_part.lower()] = _flat
    _ALIAS_TO_FLAT[_flat.replace("_", "").lower()] = _flat

# Common formula token shortcuts → flat keys
for _shortcut, _flat in {
    "sales": "Sales",
    "expenses": "Expenses",
    "operatingprofit": "OperatingProfit",
    "ebitda": "EBITDA",
    "ebit": "EBIT",
    "netprofit": "NetProfit",
    "profitbeforetax": "ProfitBeforeTax",
    "profitaftertax": "ProfitAfterTax",
    "interest": "Interest",
    "depreciation": "Depreciation",
    "tax": "Tax",
    "otherincome": "OtherIncome",
    "otherincome_normal": "OtherIncome_normal",
    "exceptionalitems": "ExceptionalItems",
    "dividendpaid": "DividendPaid",
    "totalequity": "TotalEquity",
    "totalassets": "TotalAssets",
    "borrowings": "Borrowings",
    "debttoequity": "DebtToEquity",
    "cashfromoperatingactivity": "CashFromOperatingActivity",
    "cashfrominvestingactivity": "CashFromInvestingActivity",
    "cashfromfinancingactivity": "CashFromFinancingActivity",
}.items():
    _ALIAS_TO_FLAT[_shortcut] = _flat

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FORMULA_MARKERS = set("+-*/()")


def _to_decimal(x: Any) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        if isinstance(x, (int, float, Decimal)):
            return Decimal(str(x))
        s = str(x).strip().replace(",", "")
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _is_formula(expr: str) -> bool:
    s = (expr or "").strip()
    if not s:
        return False
    if s.startswith("="):
        return True
    return any(ch in s for ch in _FORMULA_MARKERS)


def _build_fact_maps(
    extracted_data: List[Dict[str, Any]],
    pl_context: str,
) -> Tuple[Dict[str, Decimal], Dict[str, Decimal], Dict[str, str]]:
    """
    Returns (pl_facts, any_facts, meta_strings).
    pl_context: 'oned' | 'fourd'
    """
    wanted = (pl_context or "oned").strip().lower()
    pl: Dict[str, Decimal] = {}
    any_ctx: Dict[str, Decimal] = {}
    meta: Dict[str, str] = {}

    for item in extracted_data or []:
        local = str(item.get("localname") or "").strip().lower()
        if not local:
            continue
        raw = item.get("value")
        ctx = (item.get("contextRef") or item.get("contextref") or "").strip().lower()
        val = _to_decimal(raw)
        if val is not None:
            if local not in any_ctx:
                any_ctx[local] = val
            if ctx == wanted and local not in pl:
                pl[local] = val
        elif raw is not None:
            sval = str(raw).strip()
            if sval:
                if "currency" in local or local == "descriptionofpresentationcurrency":
                    meta.setdefault("currency", sval)
                if "rounding" in local or "levelofrounding" in local:
                    meta.setdefault("level_of_rounding", sval)
                if "nameofthecompany" in local or local == "nameofcompany":
                    meta.setdefault("company_name", sval)
                if local in ("symbol", "scripcode"):
                    meta.setdefault("company_symbol", sval)

    # Fallback: if no PL-context facts, use any-context for PL lookups
    if not pl:
        pl = dict(any_ctx)
    return pl, any_ctx, meta


def _lookup_tag(facts: Dict[str, Decimal], tag: str) -> Optional[Decimal]:
    if not tag:
        return None
    key = tag.strip().lower()
    if key in facts:
        return facts[key]
    # fuzzy contains (handles minor naming drift)
    for k, v in facts.items():
        if key in k or k in key:
            return v
    return None


def _sub_category_uses_pl_context(sub_category: str) -> bool:
    sub = (sub_category or "").strip().lower()
    return sub in ("quarterly", "p&l", "p_l", "pl")


def _safe_eval_arith(expr: str) -> Optional[Decimal]:
    """Evaluate a numeric expression with only + - * / ( ) and decimals."""
    cleaned = expr.replace(" ", "")
    if not cleaned or not re.fullmatch(r"[0-9+\-*/().eE]+", cleaned):
        return None
    try:
        # noqa: S307 — tightly constrained charset above
        value = eval(cleaned, {"__builtins__": {}}, {})
        return _to_decimal(value)
    except Exception:
        return None


def _resolve_identifier(
    name: str,
    computed: Dict[str, Decimal],
    pl_facts: Dict[str, Decimal],
    any_facts: Dict[str, Decimal],
    prefer_pl: bool,
) -> Optional[Decimal]:
    raw = name.strip()
    if not raw:
        return None
    # Already computed flat / particulars aliases
    flat = _ALIAS_TO_FLAT.get(raw.lower()) or _ALIAS_TO_FLAT.get(raw.replace("_", "").lower())
    if flat and flat in computed:
        return computed[flat]
    # Direct computed by same token
    if raw in computed:
        return computed[raw]
    if raw.lower() in {k.lower(): k for k in computed}:
        for k, v in computed.items():
            if k.lower() == raw.lower():
                return v

    facts = pl_facts if prefer_pl else any_facts
    val = _lookup_tag(facts, raw)
    if val is not None:
        return val
    # try the other map
    other = any_facts if prefer_pl else pl_facts
    return _lookup_tag(other, raw)


def _eval_ind_as(
    ind_as: str,
    computed: Dict[str, Decimal],
    pl_facts: Dict[str, Decimal],
    any_facts: Dict[str, Decimal],
    prefer_pl: bool,
) -> Optional[Decimal]:
    expr = (ind_as or "").strip()
    if not expr:
        return None
    if expr.startswith("="):
        expr = expr[1:].strip()

    if not _is_formula(expr):
        return _resolve_identifier(expr, computed, pl_facts, any_facts, prefer_pl)

    # Replace identifiers longest-first so Sales is not eaten by Sale etc.
    idents = list({m.group(0) for m in _IDENT_RE.finditer(expr)})
    idents.sort(key=len, reverse=True)
    replaced = expr
    for ident in idents:
        if ident.lower() in ("e",):  # scientific notation remnant — skip lone e
            continue
        val = _resolve_identifier(ident, computed, pl_facts, any_facts, prefer_pl)
        if val is None:
            # Missing operand — cannot evaluate yet
            return None
        replaced = re.sub(rf"\b{re.escape(ident)}\b", f"({val})", replaced)

    return _safe_eval_arith(replaced)


def evaluate_metrics_catalog(
    extracted_data: List[Dict[str, Any]],
    definitions: List[MetricDefinition],
    *,
    pl_context: str = "oned",
) -> Dict[str, Any]:
    """
    Evaluate Metrics rows into a flat dict (Sales, Expenses, …) plus meta fields.
    """
    pl_facts, any_facts, meta = _build_fact_maps(extracted_data, pl_context)
    computed: Dict[str, Decimal] = {}

    # Multi-pass so formulas can depend on earlier particulars
    pending = list(definitions)
    for _ in range(len(definitions) + 3):
        if not pending:
            break
        still: List[MetricDefinition] = []
        progressed = False
        for row in pending:
            ind = (row.ind_as or "").strip()
            if not ind:
                continue
            prefer_pl = _sub_category_uses_pl_context(row.sub_category)
            val = _eval_ind_as(ind, computed, pl_facts, any_facts, prefer_pl)
            if val is None:
                still.append(row)
                continue
            flat_key = PARTICULARS_TO_FLAT.get(row.particulars) or row.particulars
            computed[flat_key] = val
            # also store under particulars-based aliases
            _ALIAS_TO_FLAT[row.particulars.lower()] = flat_key
            progressed = True
        pending = still
        if not progressed:
            break

    out: Dict[str, Any] = {
        "currency": meta.get("currency"),
        "level_of_rounding": meta.get("level_of_rounding"),
        "company_name": meta.get("company_name"),
        "company_symbol": meta.get("company_symbol"),
    }
    for k, v in computed.items():
        out[k] = float(v)
    return out


async def load_metric_definitions(metric_category: str) -> List[MetricDefinition]:
    cat = (metric_category or "").strip()
    rows = await MetricDefinition.filter(metric_category__iexact=cat).order_by("id")
    if rows:
        return list(rows)
    # tolerate case variants
    return list(await MetricDefinition.filter(metric_category__icontains=cat).order_by("id"))


async def calculate_metrics_from_catalog(
    extracted_data: List[Dict[str, Any]],
    *,
    extraction_type: str = "quarterly",
) -> Dict[str, Any]:
    """
    Load Metrics.ind_as for quarterly or Annual and compute flat values.
    """
    if (extraction_type or "").lower().startswith("annual"):
        defs = await load_metric_definitions("Annual")
        return evaluate_metrics_catalog(extracted_data, defs, pl_context="fourd")
    defs = await load_metric_definitions("quarterly")
    return evaluate_metrics_catalog(extracted_data, defs, pl_context="oned")
