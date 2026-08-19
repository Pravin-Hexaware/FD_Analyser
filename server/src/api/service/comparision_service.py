# server/src/routers/extract.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, InvalidOperation

from service.html_extraction_service import extract_html_data
from service.xml_extraction_service import extract_xbrl_data
from repository.html_data_repository import HTMLDataRepository
from api.xbrl_route import _convert_xml_grouped_to_list

# (router already defined above)
router = APIRouter()


# -------------------- New: Request/Response Models (ANNUAL) --------------------

class ExtractAnnualRequest(BaseModel):
    url: List[str]  # array of yearly (or half-yearly) XBRL/iXBRL URLs

    @field_validator('url', mode='before')
    @classmethod
    def convert_url_to_list(cls, v):
        """Convert single URL string to list for consistency"""
        if isinstance(v, str):
            return [v]  # wrap single string in list
        if isinstance(v, list):
            return v
        raise ValueError("url must be a string or list of strings")


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
    "sales": ["revenuefromoperations", "revenuefromoperation", "sales", "revenue", "RevenueFromOperations"],
    "other_income": ["otherincome", "otherincomes"],

    "cost_of_materials": ["costofmaterialsconsumed", "rawmaterialconsumed"],
    "purchases_traded": ["purchasesofstockintrade", "purchaseofstockintrade"],
    "inventory_change": [
        "changesininventoriesoffinishedgoodsworkinprogressandstockintrade",
        "changesininventories"
    ],
    "employee": ["employeebenifitexpense", "employeebenifitexpenses", "employeebenefitexpense",
                 "employeebenefitexpenses"],
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

    OPM_percentage = _pct(OperatingProfit, Sales) if (
                OperatingProfit is not None and Sales not in (None, Decimal("0"))) else None
    Tax_percent = _pct(TaxTotal, PBT) if (TaxTotal is not None and PBT not in (None, Decimal("0"))) else None

    # Resolve the balance sheet and cashflow fields by name mappings for FourD
    EquityCapital = G("equity_share_capital") or fuzzy_numeric("equity_share_capital",
                                                               ["equitysharecapital", "equitycapital", "sharecapital"])
    Reserves = G("reserves") or fuzzy_numeric("reserves", ["otherequity", "reserves", "retainedearnings"])
    Borrowings = G("borrowings") or fuzzy_numeric("borrowings",
                                                  ["borrowings", "longtermborrowings", "shorttermborrowings"])
    OtherLiabilities = G("other_liabilities") or fuzzy_numeric("other_liabilities",
                                                               ["otherliabilities", "otherliability"])
    TotalLiabilities = G("total_liabilities") or fuzzy_numeric("total_liabilities",
                                                               ["liabilities", "equityandliabilities",
                                                                "totalliabilities"])
    Assets = G("total_assets") or fuzzy_numeric("total_assets", ["assets", "totalassets"])
    TotalEquity = G("equity") or fuzzy_numeric("equity", ["equity", "totalequity"])

    PropertyPlantAndEquipment = _first_by_keys(fourd,
                                               ["propertyplantandequipment", "ppe"]) if fourd is not None else None
    OtherIntangibleAssets = _first_by_keys(fourd,
                                           ["otherintangibleassets", "intangibleassets"]) if fourd is not None else None
    FixedAssets = (PropertyPlantAndEquipment or Decimal(0)) + (OtherIntangibleAssets or Decimal(0)) if (
                PropertyPlantAndEquipment is not None or OtherIntangibleAssets is not None) else None

    CWIP = G("cwip") or fuzzy_numeric("cwip", ["capitalworkinprogress"])
    Investments = (G("investments") or Decimal(0))
    NoncurrentInvestments = _first_by_keys(fourd, ["noncurrentinvestments",
                                                   "noncurrentinvestment"]) if fourd is not None else None
    CurrentInvestments = _first_by_keys(fourd,
                                        ["currentinvestments", "currentinvestment"]) if fourd is not None else None
    Investments = (NoncurrentInvestments or Decimal(0)) + (CurrentInvestments or Decimal(0)) if (
                NoncurrentInvestments is not None or CurrentInvestments is not None) else Investments

    CashFromOperatingActivity = _first_by_keys(fourd, ["cashflowsfromusedinoperatingactivities",
                                                       "netcashflowfromoperatingactivities",
                                                       "cashflowfromoperatingactivities"]) if fourd is not None else None
    CashFromInvestingActivity = _first_by_keys(fourd, ["cashflowsfromusedininvestingactivities",
                                                       "cashflowfrominvestingactivities"]) if fourd is not None else None
    CashFromFinancingActivity = _first_by_keys(fourd, ["cashflowsfromusedinfinancingactivities",
                                                       "cashflowfromfinancingactivities"]) if fourd is not None else None

    return {
        # Include metadata from the meta dict collected above
        "company_name": meta.get("company_name"),
        "company_symbol": meta.get("company_symbol"),
        "currency": meta.get("currency"),
        "level_of_rounding": meta.get("level_of_rounding"),
        "reporting_type": meta.get("reporting_type"),

        # Financial metrics
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

        "CashFromOperatingActivity": float(
            CashFromOperatingActivity) if CashFromOperatingActivity is not None else None,
        "CashFromInvestingActivity": float(
            CashFromInvestingActivity) if CashFromInvestingActivity is not None else None,
        "CashFromFinancingActivity": float(
            CashFromFinancingActivity) if CashFromFinancingActivity is not None else None,
    }

