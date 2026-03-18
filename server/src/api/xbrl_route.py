# server/src/routers/extract.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from decimal import Decimal, InvalidOperation

from service.html_extraction_service import extract_html_data
from service.xml_extraction_service import extract_xbrl_data
from repository.html_data_repository import HTMLDataRepository
from repository.xml_data_repository import XMLDataRepository

router = APIRouter()


# -------------------- Request/Response Models --------------------

class ExtractXBRLRequest(BaseModel):
    url: List[str]


class CompanyMetrics(BaseModel):
    url: str
    type: str
    company_name: Optional[str] = None
    company_symbol: Optional[str] = None
    currency: Optional[str] = None
    level_of_rounding: Optional[str] = None
    reporting_type: Optional[str] = None
    NatureOfReport: Optional[str] = None
    Sales: Optional[float] = None
    Expenses: Optional[float] = None            # Screener-style Operating Expenses (before depreciation)
    OperatingProfit: Optional[float] = None     # EBITDA (Screener shows this as Operating Profit)
    OPM_percentage: Optional[float] = None      # EBITDA / Sales * 100
    OtherIncome: Optional[float] = None
    Interest: Optional[float] = None            # Finance Costs
    Depreciation: Optional[float] = None
    ProfitBeforeTax: Optional[float] = None
    Tax: Optional[float] = None                 # Tax Amount
    Tax_percent: Optional[float] = None         # (Tax / PBT) * 100
    NetProfit: Optional[float] = None           # ProfitLossForPeriod
    EPS_in_RS: Optional[float] = None
    error: Optional[str] = None                 # optional error info


# -------------------- Helpers --------------------

def _to_decimal(x: Any) -> Optional[Decimal]:
    """Convert value to Decimal safely; return None if not numeric."""
    if x is None:
        return None
    try:
        if isinstance(x, (int, float, Decimal)):
            return Decimal(str(x))
        s = str(x).strip().replace(",", "")
        # parentheses indicate negative in many financials
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


# -------------------- Canonical Synonyms (ALL LOWERCASE localnames) --------------------
# IMPORTANT: localnames in your extractors are lowercased in this module.

STRING_SYNONYMS = {
    "company_name": [
        "nameofthecompany", "nameofcompany", "entityname"
    ],
    "company_symbol": [
        "symbol", "scripcode", "mseisymbol", "stockticker", "stockcode"
    ],
    "currency": [
        "descriptionofpresentationcurrency", "reportingcurrency", "currency","DescriptionOfPresentationCurrency"
    ],
    "level_of_rounding": [
        "levelofrounding", "unitofmeasure","LevelOfRoundingUsedInFinancialStatements","levelofroundingusedinfinancialstatements"
    ],
    "reporting_type": [
        "typeofreportingperiod", "reportingtype", "reportingperiodtype","reportingquarter"
    ],
    "nature_of_report": [
        "natureofreportstandaloneconsolidated", "natureofreport"
    ],
}

NUMERIC_SYNONYMS = {
    # Top line
    "sales": ["revenuefromoperations", "revenuefromoperation", "sales"],

    # Operating costs
    "cost_of_materials": ["costofmaterialsconsumed", "rawmaterialconsumed"],
    "purchases_traded": ["purchasesofstockintrade", "purchaseofstockintrade"],
    "inventory_change": [
        "changesininventoriesoffinishedgoodsworkinprogressandstockintrade",
        "changesininventories"
    ],
    "employee": ["employeebenefitexpense", "employeebenefitexpenses"],
    "power_fuel": ["powerandfuelexpenses", "powerandfuel"],  # optional; often missing
    "other_expenses": ["otherexpenses", "otherexpense"],

    # Non-operating
    "other_income": ["otherincome"],

    # Below operating line
    "finance_costs": ["financecosts", "financecost", "interestexpense", "interestcost"],
    "depreciation": [
        "depreciationdepletionandamortisationexpense",
        "depreciationandamortisationexpense",
        "depreciationexpense", "amortisationexpense"
    ],

    # Bottom line
    "pbt": ["profitbeforetax", "profitlossbeforetax", "pbt"],
    "tax_expense": ["taxexpense", "totaltaxexpenses", "taxexpenses"],
    "net_profit": ["profitlossforperiod", "profitlossforperiodfromcontinuingoperations"],

    # EPS
    "eps_basic": [
        "basicearningslosspersharefromcontinuinganddiscontinuedoperations",
        "basicearningslosspersharefromcontinuingoperations",
        "basicearningspershare"
    ],
}


# -------------------- Metrics Calculator --------------------

def calculate_metrics(extracted_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a key->value map ONLY for OneD context, then compute Screener-style metrics.
    Returns plain python types; FastAPI/Pydantic will coerce.
    """
    # 1) Keep only OneD facts (quarterly), normalize to lowercase localnames
    oned: Dict[str, Decimal] = {}
    for item in extracted_data:
        ctx = (item.get("contextRef") or item.get("contextref") or "").strip().lower()
        if ctx != "oned":
            continue
        local = str(item.get("localname", "")).strip().lower()
        val = _to_decimal(item.get("value"))
        if local and (val is not None) and (local not in oned):
            oned[local] = val

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

    # 3) Resolve fields
    Sales = G("sales") or fuzzy_numeric("sales", ["revenue", "turnover", "sales"])
    OtherIncome = G("other_income") or fuzzy_numeric("other_income", ["otherincome", "nonoperating"])

    CostMaterials = G("cost_of_materials") or Decimal(0)
    PurchasesTraded = G("purchases_traded") or Decimal(0)
    InventoryChange = G("inventory_change") or Decimal(0)
    Employee = G("employee") or Decimal(0)
    PowerFuel = G("power_fuel") or Decimal(0)
    OtherExpenses = G("other_expenses") or Decimal(0)

    # Screener-style Operating Expenses (before depreciation)
    Expenses = CostMaterials + PurchasesTraded + InventoryChange + Employee + PowerFuel + OtherExpenses

    FinanceCosts = G("finance_costs") or fuzzy_numeric("finance_costs", ["interest", "finance"])
    Depreciation = G("depreciation") or fuzzy_numeric("depreciation", ["depreciation", "amortisation"])
    PBT = G("pbt") or fuzzy_numeric("pbt", ["profitbeforetax", "pbt"])
    TaxAmount = G("tax_expense") or fuzzy_numeric("tax_expense", ["taxexpense", "tax"])
    NetProfit = G("net_profit") or fuzzy_numeric("net_profit", ["netprofit", "profitloss"])
    EPS = G("eps_basic") or fuzzy_numeric("eps_basic", ["eps", "earningspershare"])

    # OperatingProfit = EBITDA = Sales - Expenses
    OperatingProfit = None
    if Sales is not None:
        # if Sales exists but we had no operating expenses, Expenses will be 0
        OperatingProfit = Sales - Expenses

    # OPM% = EBITDA / Sales * 100
    OPM_percentage = _pct(OperatingProfit, Sales) if (OperatingProfit is not None and Sales not in (None, Decimal("0"))) else None

    # Tax% (effective tax rate)
    Tax_percent = _pct(TaxAmount, PBT) if (TaxAmount is not None and PBT not in (None, Decimal("0"))) else None

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
        "Interest": float(FinanceCosts) if FinanceCosts is not None else None,
        "Depreciation": float(Depreciation) if Depreciation is not None else None,

        "ProfitBeforeTax": float(PBT) if PBT is not None else None,
        "Tax": float(TaxAmount) if TaxAmount is not None else None,
        "Tax_percent": float(Tax_percent) if Tax_percent is not None else None,
        "NetProfit": float(NetProfit) if NetProfit is not None else None,
        "EPS_in_RS": float(EPS) if EPS is not None else None,
    }
    print(result)
    return result


# -------------------- API Route --------------------

@router.post("/extract/urls", response_model=List[CompanyMetrics])
async def extract_xbrl(request: ExtractXBRLRequest):
    """
    Extract XBRL/iXBRL data from multiple URLs and calculate Screener-style metrics.
    Only OneD (quarterly) context is used for computations.
    """
    if not request.url:
        raise HTTPException(status_code=400, detail="No URLs provided")

    response: List[CompanyMetrics] = []

    for url in request.url:
        try:
            if url.endswith(".xml"):
                # Allow all prefixes to avoid data loss in XML
                only_prefix = None  # keep signature compatibility
                extracted_data = extract_xbrl_data(url, only_prefix)
                data_type = "xml"
            elif url.endswith((".html", ".htm", ".xhtml")):
                extracted_data = extract_html_data(url)
                data_type = "html"
            else:
                response.append(CompanyMetrics(url=url, type="unknown"))
                continue

            print(f"Extracted {len(extracted_data)} items from {url} (type: {data_type})")

            metrics = calculate_metrics(extracted_data)
            print(f"Extracted metrics for {url}: {metrics}")

            # Persist raw extracted facts (optional)
            if data_type == "xml":
                repo = XMLDataRepository()
            else:
                repo = HTMLDataRepository()
            repo.save_to_json(extracted_data)
            repo.save_to_csv(extracted_data)

            response.append(CompanyMetrics(url=url, type=data_type, **metrics))

        except Exception as e:
            response.append(CompanyMetrics(
                url=url,
                type="error",
                error=str(e)[:500]
            ))

    return response