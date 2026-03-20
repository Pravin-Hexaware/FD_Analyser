# server/src/routers/extract.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, InvalidOperation

from service.html_extraction_service import extract_html_data
from service.xml_extraction_service import extract_xbrl_data
from repository.html_data_repository import HTMLDataRepository
from repository.xml_data_repository import XMLDataRepository
from api.xbrl_route import calculate_metrics

# (router already defined above)
router = APIRouter()


# -------------------- New: Request/Response Models (ANNUAL) --------------------

class ExtractAnnualRequest(BaseModel):
    url: str  # single yearly (or half-yearly) XBRL/iXBRL URL


class AnnualReportMetrics(BaseModel):
    url: str
    type: str
    company_name: Optional[str] = None
    company_symbol: Optional[str] = None
    currency: Optional[str] = None
    level_of_rounding: Optional[str] = None
    reporting_type: Optional[str] = None
    NatureOfReport: Optional[str] = None

    # Profit & Loss (Year level)
    Sales: Optional[float] = None
    Expenses: Optional[float] = None
    OperatingProfit: Optional[float] = None
    OPM_percentage: Optional[float] = None
    OtherIncome: Optional[float] = None
    Interest: Optional[float] = None
    Depreciation: Optional[float] = None
    ProfitBeforeTax: Optional[float] = None
    Tax_percent: Optional[float] = None
    NetProfit: Optional[float] = None
    EPS_in_RS: Optional[float] = None

    # Balance sheet (Year level)
    EquityCapital: Optional[float] = None
    Reserves: Optional[float] = None
    Borrowings: Optional[float] = None
    OtherLiabilities: Optional[float] = None
    TotalLiabilities: Optional[float] = None
    FixedAssets: Optional[float] = None
    CWIP: Optional[float] = None
    Investments: Optional[float] = None
    OtherAssets: Optional[float] = None
    TotalAssets: Optional[float] = None

    # Cash Flow (Year level)
    CashFromOperatingActivity: Optional[float] = None
    CashFromInvestingActivity: Optional[float] = None
    CashFromFinancingActivity: Optional[float] = None

    error: Optional[str] = None


# -------------------- Helpers (reuse from your file; keep identical) --------------------

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


def _div(a: Optional[Decimal], b: Optional[Decimal]) -> Optional[Decimal]:
    if a is None or b in (None, Decimal("0")):
        return None
    try:
        return a / b
    except Exception:
        return None


def _pct(n: Optional[Decimal], d: Optional[Decimal]) -> Optional[Decimal]:
    q = _div(n, d)
    return None if q is None else (q * Decimal(100))


def _first_by_keys(data_map: Dict[str, Decimal], keys: List[str]) -> Optional[Decimal]:
    for k in keys:
        if k in data_map:
            return data_map[k]
    return None


def _find_first_decimal_any_context(extracted_data: List[Dict[str, Any]], keys: List[str]) -> Optional[Decimal]:
    """Get first matching key from any context, no context filtering."""
    keys_set = set(k.lower() for k in keys)
    for item in extracted_data:
        local = str(item.get("localname", "")).strip().lower()
        if local in keys_set:
            val = _to_decimal(item.get("value"))
            if val is not None:
                return val
    return None


# -------------------- Synonyms (reused & slightly extended for annual) --------------------

STRING_SYNONYMS = {
    "company_name": ["nameofthecompany", "nameofcompany", "entityname"],
    "company_symbol": ["symbol", "scripcode", "mseisymbol", "stockticker", "stockcode"],
    "currency": ["descriptionofpresentationcurrency", "reportingcurrency", "currency"],
    "level_of_rounding": ["levelofrounding", "unitofmeasure", "levelofroundingusedinfinancialstatements"],
    "reporting_type": ["typeofreportingperiod", "reportingtype", "reportingperiodtype", "reportingquarter"],
    "nature_of_report": ["natureofreportstandaloneconsolidated", "natureofreport"],
    # optional: dates, if you want to store
    "report_start_date": ["dateofstartofreportingperiod"],
    "report_end_date": ["dateofendofreportingperiod"],
}

NUMERIC_SYNONYMS = {
    # P&L
    "sales": ["revenuefromoperations", "revenuefromoperation", "sales", "revenue","RevenueFromOperations"],
    "other_income": ["otherincome", "otherincomes"],

    "cost_of_materials": ["costofmaterialsconsumed", "rawmaterialconsumed"],
    "purchases_traded": ["purchasesofstockintrade", "purchaseofstockintrade"],
    "inventory_change": [
        "changesininventoriesoffinishedgoodsworkinprogressandstockintrade",
        "changesininventories"
    ],
    "employee": ["employeebenifitexpense", "employeebenifitexpenses", "employeebenefitexpense", "employeebenefitexpenses"],
    "power_fuel": ["powerandfuelexpenses", "powerandfuel"],
    "other_expenses": ["otherexpenses", "otherexpense"],

    "finance_costs": ["financecosts", "financecost", "interestexpense", "interestcost"],
    "depreciation": [
        "depreciationdepletionandamortisationexpense",
        "depreciationandamortisationexpense",
        "depreciationexpense", "amortisationexpense"
    ],
    "pbt": ["profitbeforetax", "profitlossbeforetax", "pbt", "profitbeforeexceptionalitemsandtax"],
    "tax_expense": ["taxexpense", "totaltaxexpenses", "taxexpenses"],
    "net_profit": ["profitlossforperiod", "profitlossforperiodfromcontinuingoperations"],
    "eps_basic": ["basicearningspershare", "earningspershare",
                  "basicearningslosspersharefromcontinuingoperations",
                  "basicearningslosspersharefromcontinuinganddiscontinuedoperations"],

    # Balance sheet
    "equity_share_capital": ["equitysharecapital", "equitycapital", "sharecapital"],
    "reserves": ["reserves", "otherreserves", "retainedearnings"],
    "borrowings": ["borrowings", "longtermborrowings", "shorttermborrowings"],
    "other_liabilities": ["otherliabilities", "otherliability"],
    "total_liabilities": ["totalliabilities", "totalequityandliabilities"],
    "fixed_assets": ["propertyplantandequipment", "tangibleassets", "fixedassets"],
    "cwip": ["capitalworkinprogress"],
    "investments": ["investments"],
    "other_assets": ["otherassets"],
    "total_assets": ["totalassets", "totalequityandliabilities"],

    # Cash flow
    "cfo": ["cashfromoperatingactivity", "cashflowfromoperatingactivities",
            "netcashflowfromoperatingactivities", "netcashusedinfromoperatingactivities"],
    "cfi": ["cashfrominvestingactivity", "cashflowfrominvestingactivities",
            "netcashusedininvestingactivities", "netcashflowfrominvestingactivities"],
    "cff": ["cashfromfinancingactivity", "cashflowfromfinancingactivities",
            "netcashusedinfinancingactivities", "netcashflowfromfinancingactivities"],
}


def _classify_context(ctx: str) -> str:
    """
    Map contextRef to one of: 'current_year', 'previous_year', 'oned', 'other'.
    """
    if not ctx:
        return "other"
    lc = ctx.strip().lower()
    if lc == "fourd":
        return "fourd"
    if "previous" in lc and "year" in lc:
        return "previous_year"
    if "current" in lc and "year" in lc:
        return "current_year"
    if lc in ("currentyear", "cy", "currentyr"):
        return "current_year"
    if lc in ("previousyear", "py", "prioryear"):
        return "previous_year"
    return "other"


# -------------------- Annual collector (CurrentYear only) --------------------

def _collect_current_year_map(extracted_data: List[Dict[str, Any]]) -> Tuple[Dict[str, Decimal], Dict[str, Any]]:
    cy: Dict[str, Decimal] = {}
    meta: Dict[str, Any] = {}

    for item in extracted_data:
        local = str(item.get("localname", "")).strip().lower()
        raw = item.get("value")

        # meta (from any context)
        if local and raw is not None:
            sval = str(raw).strip()
            if local in STRING_SYNONYMS["currency"]:
                meta.setdefault("currency", sval)
            if local in STRING_SYNONYMS["level_of_rounding"]:
                meta.setdefault("level_of_rounding", sval)
            if local in STRING_SYNONYMS["nature_of_report"]:
                meta.setdefault("nature_of_report", sval)
            if local in STRING_SYNONYMS["reporting_type"]:
                meta.setdefault("reporting_type", sval)
            if local in STRING_SYNONYMS["company_name"]:
                meta.setdefault("company_name", sval)
            if local in STRING_SYNONYMS.get("company_symbol", []):  # fallback if typo
                meta.setdefault("company_symbol", sval)
            if local in STRING_SYNONYMS["company_symbol"]:
                meta.setdefault("company_symbol", sval)
            if local in STRING_SYNONYMS["report_start_date"]:
                meta.setdefault("report_start_date", sval)
            if local in STRING_SYNONYMS["report_end_date"]:
                meta.setdefault("report_end_date", sval)

        # current-year collection
        ctx = (item.get("contextRef") or item.get("contextref") or "").strip()
        if _classify_context(ctx) != "current_year":
            continue

        val = _to_decimal(item.get("value"))
        if val is None or not local:
            continue
        if local not in cy:
            cy[local] = val

    return cy, meta


def _get_from_map(m: Dict[str, Decimal], key: str, patterns: List[str] = None) -> Optional[Decimal]:
    v = _first_by_keys(m, NUMERIC_SYNONYMS.get(key, []))
    if v is not None or not patterns:
        return v
    for p in patterns:
        for k in m.keys():
            if p in k:
                vv = m[k]
                if vv is not None:
                    return vv
    return None


# -------------------- Build Annual (CurrentYear) statements --------------------

def _build_annual_current_year(m: Dict[str, Decimal]) -> Dict[str, Optional[float]]:
    Sales = _get_from_map(m, "sales", ["revenuefromoperations", "revenue", "sales"])
    OtherIncome = _get_from_map(m, "other_income", ["otherincome"])

    CostMaterials = _get_from_map(m, "cost_of_materials") or Decimal(0)
    PurchasesTraded = _get_from_map(m, "purchases_traded") or Decimal(0)
    InventoryChange = _get_from_map(m, "inventory_change") or Decimal(0)
    Employee = _get_from_map(m, "employee") or Decimal(0)
    PowerFuel = _get_from_map(m, "power_fuel") or Decimal(0)
    OtherExp = _get_from_map(m, "other_expenses") or Decimal(0)

    Expenses = CostMaterials + PurchasesTraded + InventoryChange + Employee + PowerFuel + OtherExp

    FinanceCosts = _get_from_map(m, "finance_costs", ["interest", "finance"])
    Depreciation = _get_from_map(m, "depreciation", ["depreciation", "amortisation"])

    PBT = _get_from_map(m, "pbt", ["profitbeforetax", "pbt"])
    TaxTotal = _get_from_map(m, "tax_expense", ["taxexpense"])
    NetProfit = _get_from_map(m, "net_profit", ["profitlossforperiod", "netprofit"])
    EPS = _get_from_map(m, "eps_basic", ["eps", "earningspershare"])

    OperatingProfit = None
    if Sales is not None:
        OperatingProfit = Sales - Expenses

    OPM_percentage = _pct(OperatingProfit, Sales) if (OperatingProfit is not None and Sales not in (None, Decimal("0"))) else None
    Tax_percent = _pct(TaxTotal, PBT) if (TaxTotal is not None and PBT not in (None, Decimal("0"))) else None

    EquityCapital = _get_from_map(m, "equity_share_capital")
    Reserves = _get_from_map(m, "reserves")
    Borrowings = _get_from_map(m, "borrowings")
    OtherLiabilities = _get_from_map(m, "other_liabilities")
    TotalLiabilities = _get_from_map(m, "total_liabilities")
    FixedAssets = _get_from_map(m, "fixed_assets")
    CWIP = _get_from_map(m, "cwip")
    Investments = _get_from_map(m, "investments")
    OtherAssets = _get_from_map(m, "other_assets")
    TotalAssets = _get_from_map(m, "total_assets")

    CFO = _get_from_map(m, "cfo")
    CFI = _get_from_map(m, "cfi")
    CFF = _get_from_map(m, "cff")

    return {
        "Sales": float(Sales) if Sales is not None else None,
        "Expenses": float(Expenses) if Expenses is not None else None,
        "OperatingProfit": float(OperatingProfit) if OperatingProfit is not None else None,
        "OPM_percentage": float(OPM_percentage) if OPM_percentage is not None else None,
        "OtherIncome": float(OtherIncome) if OtherIncome is not None else None,
        "Interest": float(FinanceCosts) if FinanceCosts is not None else None,
        "Depreciation": float(Depreciation) if Depreciation is not None else None,
        "ProfitBeforeTax": float(PBT) if PBT is not None else None,
        "Tax_percent": float(Tax_percent) if Tax_percent is not None else None,
        "NetProfit": float(NetProfit) if NetProfit is not None else None,
        "EPS_in_RS": float(EPS) if EPS is not None else None,

        "EquityCapital": float(EquityCapital) if EquityCapital is not None else None,
        "Reserves": float(Reserves) if Reserves is not None else None,
        "Borrowings": float(Borrowings) if Borrowings is not None else None,
        "OtherLiabilities": float(OtherLiabilities) if OtherLiabilities is not None else None,
        "TotalLiabilities": float(TotalLiabilities) if TotalLiabilities is not None else None,
        "FixedAssets": float(FixedAssets) if FixedAssets is not None else None,
        "CWIP": float(CWIP) if CWIP is not None else None,
        "Investments": float(Investments) if Investments is not None else None,
        "OtherAssets": float(OtherAssets) if OtherAssets is not None else None,
        "TotalAssets": float(TotalAssets) if TotalAssets is not None else None,

        "CashFromOperatingActivity": float(CFO) if CFO is not None else None,
        "CashFromInvestingActivity": float(CFI) if CFI is not None else None,
        "CashFromFinancingActivity": float(CFF) if CFF is not None else None,
    }


def calculate_metrics_fourd(extracted_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    # duplicate of calculate_metrics() with FourD context filtering
    fourd: Dict[str, Decimal] = {}
    for item in extracted_data:
        ctx = (item.get("contextRef") or item.get("contextref") or "").strip().lower()
        if ctx != "fourd":
            continue
        local = str(item.get("localname", "")).strip().lower()
        val = _to_decimal(item.get("value"))
        if local and (val is not None) and (local not in fourd):
            fourd[local] = val

    meta: Dict[str, Any] = {}
    for item in extracted_data:
        local = str(item.get("localname", "")).strip().lower()
        raw = item.get("value")
        if not local or raw is None:
            continue
        sval = str(raw).strip()
        if not sval:
            continue

        if local in STRING_SYNONYMS["currency"]:
            meta.setdefault("currency", sval)
        if local in STRING_SYNONYMS["level_of_rounding"]:
            meta.setdefault("level_of_rounding", sval)
        if local in STRING_SYNONYMS["nature_of_report"]:
            meta.setdefault("nature_of_report", sval)
        if local in STRING_SYNONYMS["reporting_type"]:
            meta.setdefault("reporting_type", sval)
        if local in STRING_SYNONYMS["company_name"]:
            meta.setdefault("company_name", sval)
        if local in STRING_SYNONYMS["company_symbol"]:
            meta.setdefault("company_symbol", sval)

    def G(key: str) -> Optional[Decimal]:
        return _first_by_keys(fourd, NUMERIC_SYNONYMS.get(key, []))

    def fuzzy_numeric(key: str, patterns: List[str]) -> Optional[Decimal]:
        if key in fourd and fourd[key] is not None:
            return fourd[key]
        low_keys = list(fourd.keys())
        for p in patterns:
            for k in low_keys:
                if p in k:
                    v = fourd.get(k)
                    if v is not None:
                        return v
        return None

    Sales = G("sales") or fuzzy_numeric("sales", ["revenuefromoperations", "revenue", "turnover", "sales"])
    OtherIncome = G("other_income") or fuzzy_numeric("other_income", ["otherincome", "nonoperating"])

    CostMaterials = G("cost_of_materials") or Decimal(0)
    PurchasesTraded = G("purchases_traded") or Decimal(0)
    InventoryChange = G("inventory_change") or Decimal(0)
    Employee = G("employee") or Decimal(0)
    PowerFuel = G("power_fuel") or Decimal(0)
    OtherExp = G("other_expenses") or Decimal(0)

    Expenses = CostMaterials + PurchasesTraded + InventoryChange + Employee + PowerFuel + OtherExp

    FinanceCosts = G("finance_costs") or fuzzy_numeric("finance_costs", ["interest", "finance"])
    Depreciation = G("depreciation") or fuzzy_numeric("depreciation", ["depreciation", "amortisation"])

    PBT = G("pbt") or fuzzy_numeric("pbt", ["profitbeforetax", "pbt"])

    TaxTotal = G("tax_expense") or fuzzy_numeric("tax_expense", ["taxexpense", "taxexpenses"])
    CurrentTax = G("current_tax") or fuzzy_numeric("current_tax", ["currenttax"])
    DeferredTax = G("deferred_tax") or fuzzy_numeric("deferred_tax", ["deferredtax"])

    if TaxTotal is not None:
        if CurrentTax is None and DeferredTax is not None:
            CurrentTax = TaxTotal - DeferredTax
        elif DeferredTax is None and CurrentTax is not None:
            DeferredTax = TaxTotal - CurrentTax
    else:
        if CurrentTax is not None and DeferredTax is not None:
            TaxTotal = CurrentTax + DeferredTax

    NetProfit = G("net_profit") or fuzzy_numeric("net_profit", ["profitlossforperiod", "netprofit"])
    EPS = G("eps_basic") or fuzzy_numeric("eps_basic", ["eps", "earningspershare"])

    OperatingProfit = None
    if Sales is not None:
        OperatingProfit = Sales - Expenses

    OPM_percentage = _pct(OperatingProfit, Sales) if (OperatingProfit is not None and Sales not in (None, Decimal("0"))) else None
    Tax_percent = _pct(TaxTotal, PBT) if (TaxTotal is not None and PBT not in (None, Decimal("0"))) else None

    # Resolve the balance sheet and cashflow fields by name mappings for FourD
    EquityCapital = G("equity_share_capital") or fuzzy_numeric("equity_share_capital", ["equitysharecapital", "equitycapital", "sharecapital"])
    Reserves = G("reserves") or fuzzy_numeric("reserves", ["otherequity", "reserves", "retainedearnings"])
    Borrowings = G("borrowings") or fuzzy_numeric("borrowings", ["borrowings", "longtermborrowings", "shorttermborrowings"])
    OtherLiabilities = G("other_liabilities") or fuzzy_numeric("other_liabilities", ["otherliabilities", "otherliability"])
    TotalLiabilities = G("total_liabilities") or fuzzy_numeric("total_liabilities", ["liabilities", "equityandliabilities", "totalliabilities"])
    Assets = G("total_assets") or fuzzy_numeric("total_assets", ["assets", "totalassets"])
    TotalEquity = G("equity") or fuzzy_numeric("equity", ["equity", "totalequity"])

    PropertyPlantAndEquipment = _first_by_keys(fourd, ["propertyplantandequipment", "ppe"]) if fourd is not None else None
    OtherIntangibleAssets = _first_by_keys(fourd, ["otherintangibleassets", "intangibleassets"]) if fourd is not None else None
    FixedAssets = (PropertyPlantAndEquipment or Decimal(0)) + (OtherIntangibleAssets or Decimal(0)) if (PropertyPlantAndEquipment is not None or OtherIntangibleAssets is not None) else None

    CWIP = G("cwip") or fuzzy_numeric("cwip", ["capitalworkinprogress"])
    Investments = (G("investments") or Decimal(0))
    NoncurrentInvestments = _first_by_keys(fourd, ["noncurrentinvestments", "noncurrentinvestment"]) if fourd is not None else None
    CurrentInvestments = _first_by_keys(fourd, ["currentinvestments", "currentinvestment"]) if fourd is not None else None
    Investments = (NoncurrentInvestments or Decimal(0)) + (CurrentInvestments or Decimal(0)) if (NoncurrentInvestments is not None or CurrentInvestments is not None) else Investments

    CashFromOperatingActivity = _first_by_keys(fourd, ["cashflowsfromusedinoperatingactivities", "netcashflowfromoperatingactivities", "cashflowfromoperatingactivities"]) if fourd is not None else None
    CashFromInvestingActivity = _first_by_keys(fourd, ["cashflowsfromusedininvestingactivities", "cashflowfrominvestingactivities"]) if fourd is not None else None
    CashFromFinancingActivity = _first_by_keys(fourd, ["cashflowsfromusedinfinancingactivities", "cashflowfromfinancingactivities"]) if fourd is not None else None

    return {
        "Sales": float(Sales) if Sales is not None else None,
        "Expenses": float(Expenses) if Expenses is not None else None,
        "OperatingProfit": float(OperatingProfit) if OperatingProfit is not None else None,
        "OPM_percentage": float(OPM_percentage) if OPM_percentage is not None else None,
        "OtherIncome": float(OtherIncome) if OtherIncome is not None else None,
        "Interest": float(FinanceCosts) if FinanceCosts is not None else None,
        "Depreciation": float(Depreciation) if Depreciation is not None else None,
        "ProfitBeforeTax": float(PBT) if PBT is not None else None,
        "CurrentTax": float(CurrentTax) if CurrentTax is not None else None,
        "DeferredTax": float(DeferredTax) if DeferredTax is not None else None,
        "Tax": float(TaxTotal) if TaxTotal is not None else None,
        "Tax_percent": float(Tax_percent) if Tax_percent is not None else None,
        "NetProfit": float(NetProfit) if NetProfit is not None else None,
        "EPS_in_RS": float(EPS) if EPS is not None else None,

        "EquityCapital": float(EquityCapital) if EquityCapital is not None else None,
        "Reserves": float(Reserves) if Reserves is not None else None,
        "Borrowings": float(Borrowings) if Borrowings is not None else None,
        "OtherLiabilities": float(OtherLiabilities) if OtherLiabilities is not None else None,
        "TotalLiabilities": float(TotalLiabilities) if TotalLiabilities is not None else None,
        "TotalAssets": float(Assets) if Assets is not None else None,
        "TotalEquity": float(TotalEquity) if TotalEquity is not None else None,
        "FixedAssets": float(FixedAssets) if FixedAssets is not None else None,
        "CWIP": float(CWIP) if CWIP is not None else None,
        "Investments": float(Investments) if Investments is not None else None,

        "CashFromOperatingActivity": float(CashFromOperatingActivity) if CashFromOperatingActivity is not None else None,
        "CashFromInvestingActivity": float(CashFromInvestingActivity) if CashFromInvestingActivity is not None else None,
        "CashFromFinancingActivity": float(CashFromFinancingActivity) if CashFromFinancingActivity is not None else None,
    }

# -------------------- New Endpoint --------------------
    # 2) Collect meta strings from ANY context (these may not be OneD)
    meta: Dict[str, Any] = {}
    for item in extracted_data:
        local = str(item.get("localname", "")).strip().lower()
        raw = item.get("value")
        if not local or raw is None:
            continue
        sval = str(raw).strip()
        if not sval:
            continue

        if local in STRING_SYNONYMS["currency"]:
            meta.setdefault("currency", sval)
        if local in STRING_SYNONYMS["level_of_rounding"]:
            meta.setdefault("level_of_rounding", sval)
        if local in STRING_SYNONYMS["nature_of_report"]:
            meta.setdefault("nature_of_report", sval)
        if local in STRING_SYNONYMS["reporting_type"]:
            meta.setdefault("reporting_type", sval)
        if local in STRING_SYNONYMS["company_name"]:
            meta.setdefault("company_name", sval)
        if local in STRING_SYNONYMS["company_symbol"]:
            meta.setdefault("company_symbol", sval)

    # Helper to resolve numeric via synonyms
    def G(key: str) -> Optional[Decimal]:
        return _first_by_keys(oned, NUMERIC_SYNONYMS.get(key, []))

    # Fallback fuzzy lookup for missing numbers (tries to match key fragments)
    def fuzzy_numeric(key: str, patterns: List[str]) -> Optional[Decimal]:
        if key in oned and oned[key] is not None:
            return oned[key]
        low_keys = list(oned.keys())
        for p in patterns:
            for k in low_keys:
                if p in k:
                    v = oned.get(k)
                    if v is not None:
                        return v
        return None

    # 3) Resolve fields (raw components)
    Sales = G("sales") or fuzzy_numeric("sales", ["revenuefromoperations", "revenue", "turnover", "sales"])
    OtherIncome = G("other_income") or fuzzy_numeric("other_income", ["otherincome", "nonoperating"])

    CostMaterials = G("cost_of_materials") or Decimal(0)
    PurchasesTraded = G("purchases_traded") or Decimal(0)
    InventoryChange = G("inventory_change") or Decimal(0)
    Employee = G("employee") or Decimal(0)
    PowerFuel = G("power_fuel") or Decimal(0)
    OtherExp = G("other_expenses") or Decimal(0)

    # Screener-style Operating Expenses (before depreciation)
    Expenses = CostMaterials + PurchasesTraded + InventoryChange + Employee + PowerFuel + OtherExp

    FinanceCosts = G("finance_costs") or fuzzy_numeric("finance_costs", ["interest", "finance"])
    Depreciation = G("depreciation") or fuzzy_numeric("depreciation", ["depreciation", "amortisation"])

    # Profit before tax (prefer true PBT; if only PBEIT + Exceptional available, we could adjust)
    PBT = G("pbt") or fuzzy_numeric("pbt", ["profitbeforetax", "pbt"])

    # Tax pieces
    TaxTotal = G("tax_expense") or fuzzy_numeric("tax_expense", ["taxexpense", "taxexpenses"])
    CurrentTax = G("current_tax") or fuzzy_numeric("current_tax", ["currenttax"])
    DeferredTax = G("deferred_tax") or fuzzy_numeric("deferred_tax", ["deferredtax"])

    # Infer missing components from available totals (without overriding explicit facts)
    if TaxTotal is not None:
        if CurrentTax is None and DeferredTax is not None:
            CurrentTax = TaxTotal - DeferredTax
        elif DeferredTax is None and CurrentTax is not None:
            DeferredTax = TaxTotal - CurrentTax
    else:
        # If total not present but both components exist, set total = sum
        if CurrentTax is not None and DeferredTax is not None:
            TaxTotal = CurrentTax + DeferredTax

    NetProfit = G("net_profit") or fuzzy_numeric("net_profit", ["profitlossforperiod", "netprofit"])
    EPS = G("eps_basic") or fuzzy_numeric("eps_basic", ["eps", "earningspershare"])

    # OperatingProfit = EBITDA = Sales - Expenses
    OperatingProfit = None
    if Sales is not None:
        OperatingProfit = Sales - Expenses

    # Percentages
    OPM_percentage = _pct(OperatingProfit, Sales) if (
                OperatingProfit is not None and Sales not in (None, Decimal("0"))) else None
    Tax_percent = _pct(TaxTotal, PBT) if (TaxTotal is not None and PBT not in (None, Decimal("0"))) else None

    # 4) Build result (return None for components we truly did not find)
    # For components where we "assumed 0" only for arithmetic, expose None if the exact tag was missing
    def _as_float_or_none(val: Optional[Decimal], was_present: bool) -> Optional[float]:
        return float(val) if (val is not None and was_present) else (float(val) if was_present else None)

    # Presence flags for explicit component discovery
    present_cost = _first_by_keys(oned, NUMERIC_SYNONYMS["cost_of_materials"]) is not None
    present_emp = _first_by_keys(oned, NUMERIC_SYNONYMS["employee"]) is not None
    present_otherexp = _first_by_keys(oned, NUMERIC_SYNONYMS["other_expenses"]) is not None

    result = {
        "company_name": meta.get("company_name"),
        "company_symbol": meta.get("company_symbol"),
        "currency": meta.get("currency"),
        "level_of_rounding": meta.get("level_of_rounding"),
        "reporting_type": meta.get("reporting_type"),
        "NatureOfReport": meta.get("nature_of_report"),

        "Sales": float(Sales) if Sales is not None else None,
        "Expenses": float(Expenses) if Expenses is not None else None,
        "OperatingProfit": float(OperatingProfit) if OperatingProfit is not None else None,
        "OPM_percentage": float(OPM_percentage) if OPM_percentage is not None else None,

        "OtherIncome": float(OtherIncome) if OtherIncome is not None else None,
        "CostOfMaterialsConsumed": float(CostMaterials) if present_cost else None,
        "EmployeeBenefitExpense": float(Employee) if present_emp else None,
        "OtherExpenses": float(OtherExp) if present_otherexp else None,

        "Interest": float(FinanceCosts) if FinanceCosts is not None else None,
        "Depreciation": float(Depreciation) if Depreciation is not None else None,

        "ProfitBeforeTax": float(PBT) if PBT is not None else None,
        "CurrentTax": float(CurrentTax) if CurrentTax is not None else None,
        "DeferredTax": float(DeferredTax) if DeferredTax is not None else None,
        "Tax": float(TaxTotal) if TaxTotal is not None else None,
        "Tax_percent": float(Tax_percent) if Tax_percent is not None else None,

        "NetProfit": float(NetProfit) if NetProfit is not None else None,
        "EPS_in_RS": float(EPS) if EPS is not None else None,
    }

    # Optional: print for debug
    # print(result)
    return result

# -------------------- New Endpoint --------------------

@router.post("/extract/annual")
async def extract_annual(report: ExtractAnnualRequest):
    """
    Extract Annual (or Half-yearly) statements from a single XBRL/iXBRL URL.
    Returns aNested structure with Quarterly_Earnings, Profit and Loss, Balance sheet, Cashflow and no null metric values.
    """
    def _to_safe_float(val):
        if val is None:
            return 0.0
        try:
            return float(val)
        except Exception:
            return 0.0

    if not report.url:
        raise HTTPException(status_code=400, detail="No URL provided")

    url = report.url
    try:
        # parse file
        if url.endswith(".xml"):
            only_prefix = None
            extracted_data = extract_xbrl_data(url, only_prefix)
            data_type = "xml"
        elif url.endswith((".html", ".htm", ".xhtml")):
            extracted_data = extract_html_data(url)
            data_type = "html"
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Provide .xml or iXBRL (.html/.htm/.xhtml)")

        # optional persistence
        repo = XMLDataRepository() if data_type == "xml" else HTMLDataRepository()
        repo.save_to_json(extracted_data)
        repo.save_to_csv(extracted_data)

        # collect current-year map + meta
        cy_map, meta = _collect_current_year_map(extracted_data)
        annual = _build_annual_current_year(cy_map)
        quarterly = calculate_metrics(extracted_data)
        fourd = calculate_metrics_fourd(extracted_data)

        # helper for each metric: prefer FourD -> annual -> quarterly -> 0.0
        def _metric_fallback(key):
            if fourd.get(key) is not None:
                return _to_safe_float(fourd.get(key))
            if annual.get(key) is not None:
                return _to_safe_float(annual.get(key))
            if quarterly.get(key) is not None:
                return _to_safe_float(quarterly.get(key))
            return 0.0

        # standardize numeric fields to avoid nulls
        quarterly_section = {
            "Sales": _to_safe_float(quarterly.get("Sales")),
            "Expenses": _to_safe_float(quarterly.get("Expenses")),
            "OperatingProfit": _to_safe_float(quarterly.get("OperatingProfit")),
            "OPM_percentage": _to_safe_float(quarterly.get("OPM_percentage")),
            "OtherIncome": _to_safe_float(quarterly.get("OtherIncome")),
            "CostOfMaterialsConsumed": _to_safe_float(quarterly.get("CostOfMaterialsConsumed")),
            "EmployeeBenefitExpense": _to_safe_float(quarterly.get("EmployeeBenefitExpense")),
            "OtherExpenses": _to_safe_float(quarterly.get("OtherExpenses")),
            "Interest": _to_safe_float(quarterly.get("Interest")),
            "Depreciation": _to_safe_float(quarterly.get("Depreciation")),
            "ProfitBeforeTax": _to_safe_float(quarterly.get("ProfitBeforeTax")),
            "CurrentTax": _to_safe_float(quarterly.get("CurrentTax")),
            "DeferredTax": _to_safe_float(quarterly.get("DeferredTax")),
            "Tax": _to_safe_float(quarterly.get("Tax")),
            "Tax_percent": _to_safe_float(quarterly.get("Tax_percent")),
            "NetProfit": _to_safe_float(quarterly.get("NetProfit")),
            "EPS_in_RS": _to_safe_float(quarterly.get("EPS_in_RS")),
        }

        pnl_section = {
            "Sales": _metric_fallback("Sales"),
            "Expenses": _metric_fallback("Expenses"),
            "OperatingProfit": _metric_fallback("OperatingProfit"),
            "OPM_percentage": _metric_fallback("OPM_percentage"),
            "OtherIncome": _metric_fallback("OtherIncome"),
            "Interest": _metric_fallback("Interest"),
            "Depreciation": _metric_fallback("Depreciation"),
            "ProfitBeforeTax": _metric_fallback("ProfitBeforeTax"),
            "Tax_percent": _metric_fallback("Tax_percent"),
            "NetProfit": _metric_fallback("NetProfit"),
            "EPS_in_RS": _metric_fallback("EPS_in_RS"),
        }

        # Balance sheet values from any context with required mapping names
        EquityCapital_val = _find_first_decimal_any_context(extracted_data, ["equitysharecapital", "equitycapital", "sharecapital"])
        Reserves_val = _find_first_decimal_any_context(extracted_data, ["otherequity", "reserves", "retainedearnings"])
        Borrowings_val = _find_first_decimal_any_context(extracted_data, ["borrowings", "longtermborrowings", "shorttermborrowings"])
        OtherLiabilities_val = _find_first_decimal_any_context(extracted_data, ["otherliabilities", "otherliability"])
        TotalLiabilities_val = _find_first_decimal_any_context(extracted_data, ["liabilities", "equityandliabilities", "totalliabilities"])

        PropertyPlantAndEquipment_val = _find_first_decimal_any_context(extracted_data, ["propertyplantandequipment", "ppe"])
        OtherIntangibleAssets_val = _find_first_decimal_any_context(extracted_data, ["otherintangibleassets", "intangibleassets"])
        FixedAssets_val = None
        if PropertyPlantAndEquipment_val is not None or OtherIntangibleAssets_val is not None:
            FixedAssets_val = (PropertyPlantAndEquipment_val or Decimal(0)) + (OtherIntangibleAssets_val or Decimal(0))

        CWIP_val = _find_first_decimal_any_context(extracted_data, ["capitalworkinprogress"])

        NoncurrentInvestments_val = _find_first_decimal_any_context(extracted_data, ["noncurrentinvestments", "noncurrentinvestment"])
        CurrentInvestments_val = _find_first_decimal_any_context(extracted_data, ["currentinvestments", "currentinvestment"])
        Investments_val = None
        if NoncurrentInvestments_val is not None or CurrentInvestments_val is not None:
            Investments_val = (NoncurrentInvestments_val or Decimal(0)) + (CurrentInvestments_val or Decimal(0))

        TotalAssets_val = _find_first_decimal_any_context(extracted_data, ["assets", "totalassets"])
        TotalEquity_val = _find_first_decimal_any_context(extracted_data, ["equity", "totalequity"])

        TradePayablesCurrent_val = _find_first_decimal_any_context(extracted_data, ["tradepayablescurrent"])

        balance_sheet_section = {
            "EquityCapital": _to_safe_float(EquityCapital_val),
            "Reserves": _to_safe_float(Reserves_val),
            "TradePayablesCurrent": _to_safe_float(TradePayablesCurrent_val),
            "Borrowings": _to_safe_float(Borrowings_val),
            "OtherLiabilities": _to_safe_float(OtherLiabilities_val),
            "TotalLiabilities": _to_safe_float(TotalLiabilities_val),
            "TotalEquity": _to_safe_float(TotalEquity_val),
            "FixedAssets": _to_safe_float(FixedAssets_val),
            "CWIP": _to_safe_float(CWIP_val),
            "Investments": _to_safe_float(Investments_val),
            "TotalAssets": _to_safe_float(TotalAssets_val),
        }

        CashFromOperatingActivity_val = _find_first_decimal_any_context(extracted_data, ["cashflowsfromusedinoperatingactivities", "netcashflowfromoperatingactivities", "cashflowfromoperatingactivities"])
        CashFromInvestingActivity_val = _find_first_decimal_any_context(extracted_data, ["cashflowsfromusedininvestingactivities", "cashflowfrominvestingactivities"])
        CashFromFinancingActivity_val = _find_first_decimal_any_context(extracted_data, ["cashflowsfromusedinfinancingactivities", "cashflowfromfinancingactivities"])

        cashflow_section = {
            "CashFromOperatingActivity": _to_safe_float(CashFromOperatingActivity_val),
            "CashFromInvestingActivity": _to_safe_float(CashFromInvestingActivity_val),
            "CashFromFinancingActivity": _to_safe_float(CashFromFinancingActivity_val),
        }

        return {
            "url": url,
            "type": data_type,
            "company_name": meta.get("company_name"),
            "company_symbol": meta.get("company_symbol"),
            "currency": meta.get("currency"),
            "level_of_rounding": meta.get("level_of_rounding"),
            "reporting_type": meta.get("reporting_type"),
            "NatureOfReport": meta.get("nature_of_report"),
            "Quarterly_Earnings": quarterly_section,
            "Profit and Loss": pnl_section,
            "Balance sheet": balance_sheet_section,
            "Cashflow": cashflow_section,
            "error": None,
        }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "url": url,
            "type": "error",
            "company_name": None,
            "company_symbol": None,
            "currency": None,
            "level_of_rounding": None,
            "reporting_type": None,
            "NatureOfReport": None,
            "Quarterly_Earnings": {},
            "Profit and Loss": {},
            "Balance sheet": {},
            "Cashflow": {},
            "error": str(e)[:500],
        }
