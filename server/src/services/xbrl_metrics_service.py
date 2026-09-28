"""XBRL metrics calculation from extracted fact lists."""
from typing import Any, Dict, List, Optional
from decimal import Decimal, InvalidOperation

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
# IMPORTANT: localnames in your extractors should be lowercased in this module.

STRING_SYNONYMS = {
    "company_name": [
        "nameofthecompany", "nameofcompany", "entityname"
    ],
    "company_symbol": [
        "symbol", "scripcode", "mseisymbol", "stockticker", "stockcode"
    ],
    "currency": [
        "descriptionofpresentationcurrency", "reportingcurrency", "currency", "descriptionofpresentationcurrency"
    ],
    "level_of_rounding": [
        "levelofrounding", "unitofmeasure", "levelofroundingusedinfinancialstatements"
    ],
    "reporting_type": [
        "typeofreportingperiod", "reportingtype", "reportingperiodtype", "reportingquarter"
    ],
    "nature_of_report": [
        "natureofreportstandaloneconsolidated", "natureofreport"
    ],
}

NUMERIC_SYNONYMS = {
    # Top line
    "sales": ["revenuefromoperations", "revenuefromoperation", "sales", "revenue"],

    # Operating costs
    "cost_of_materials": ["costofmaterialsconsumed", "rawmaterialconsumed"],
    "purchases_traded": ["purchasesofstockintrade", "purchaseofstockintrade"],
    "inventory_change": [
        "changesininventoriesoffinishedgoodsworkinprogressandstockintrade",
        "changesininventories"
    ],
    "employee": ["employeebenefitexpense", "employeebenefitexpenses"],
    "power_fuel": ["powerandfuelexpenses", "powerandfuel"],
    "other_expenses": ["otherexpenses", "otherexpense"],

    # Non-operating
    "other_income": ["otherincome", "otherincomes"],

    # Below operating line
    "finance_costs": ["financecosts", "financecost", "interestexpense", "interestcost"],
    "depreciation": [
        "depreciationdepletionandamortisationexpense",
        "depreciationandamortisationexpense",
        "depreciationexpense", "amortisationexpense"
    ],

    # Profit
    "pbt": [
        "profitbeforetax", "profitlossbeforetax", "pbt",
        "profitbeforeexceptionalitemsandtax"
    ],
    "exceptional": ["exceptionalitemsbefortax", "exceptionalitemsbeforetax", "exceptionalitems"],

    # Tax
    "tax_expense": ["taxexpense", "totaltaxexpenses", "taxexpenses"],
    "current_tax": ["currenttax", "currenttaxexpense", "currenttaxexpenses", "currenttaxes"],
    "deferred_tax": ["deferredtax", "deferredtaxexpense", "deferredtaxexpenses", "deferredtaxes"],

    # Bottom line
    "net_profit": ["profitlossforperiod", "profitlossforperiodfromcontinuingoperations"],

    # EPS
    "eps_basic": [
        "basicearningslosspersharefromcontinuingoperations",
        "basicearningslosspersharefromcontinuinganddiscontinuedoperations",
        "basicearningspershare", "earningspershare"
    ],

    # Annual BS / CF / ratios tags
    "equity_share_capital": ["equitysharecapital", "equitycapital", "paidupequitysharecapital"],
    "other_equity": ["otherequity", "reserves", "reservesandexcedingrevaluationreserve"],
    "liabilities": ["liabilities", "totalliabilities"],
    "equity": ["equity", "totalequity"],
    "assets": ["assets", "totalassets"],
    "current_assets": ["currentassets"],
    "current_liabilities": ["currentliabilities"],
    "inventories": ["inventories", "inventory"],
    "debt_equity_ratio": ["debtequityratio", "debttoequityratio"],
    "cwip": ["capitalworkinprogress", "cwip"],
    "noncurrent_investments": ["noncurrentinvestments"],
    "current_investments": ["currentinvestments"],
    "cfo": [
        "cashflowsfromusedinoperatingactivities",
        "netcashflowfromoperatingactivities",
        "cashflowfromoperatingactivities",
    ],
    "cfi": [
        "cashflowsfromusedininvestingactivities",
        "cashflowfrominvestingactivities",
    ],
    "cff": [
        "cashflowsfromusedinfinancingactivities",
        "cashflowfromfinancingactivities",
    ],
    "dividends_paid": ["dividendspaidclassifiedasfinancingactivities", "dividendspaid"],
    "dividends_received": ["dividendsreceivedclassifiedasinvestingactivities", "dividendsreceived"],
    "trade_receivables_noncurrent": ["tradereceivablesnoncurrent"],
    "trade_receivables_current": ["tradereceivablescurrent", "tradereceivables"],
}


# -------------------- Metrics Calculator --------------------

def calculate_metrics(extracted_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build Screener-style quarterly metrics from OneD XBRL facts.

    Mapping (tags / formulas):
      Sales                 = RevenueFromOperations
      Exceptional items     = signed ExceptionalItemsBeforeTax
      Other Income_normal   = OtherIncome
      Interest              = FinanceCosts
      Depreciation          = DepreciationDepletionAndAmortisationExpense
      Profit before tax     = ProfitBeforeTax
      Profit After Tax      = ProfitLossForPeriod
      Tax                   = TaxExpense
      EPS in Rs             = BasicEarningsLossPerShareFromContinuingOperations
      Net Profit            = Profit After Tax
      Other Income          = Other Income_normal + Exceptional items
      Expenses              = Sales + Other Income - PBT - Depreciation - Interest
      Operating Profit      = Sales - Expenses
      EBITDA                = Operating Profit
      Revenue Growth %      = Sales - Operating Profit
      EBITDA Margin %       = (EBITDA / Sales) × 100
      EBIT                  = PBT + Interest - Other Income
      OPM %                 = (Operating Profit / Sales) × 100
      Tax %                 = (Tax / PBT) × 100
      Net Profit Margin     = (Net Profit / Sales) × 100
    """
    oned: Dict[str, Decimal] = {}
    for item in extracted_data:
        ctx = (item.get("contextRef") or item.get("contextref") or "").strip().lower()
        if ctx and ctx != "oned":
            continue
        local = str(item.get("localname", "")).strip().lower()
        val = _to_decimal(item.get("value"))
        if local and (val is not None) and (local not in oned):
            oned[local] = val

    # If nothing matched OneD, fall back to first numeric per localname from any context
    if not oned:
        for item in extracted_data:
            local = str(item.get("localname", "")).strip().lower()
            val = _to_decimal(item.get("value"))
            if local and val is not None and local not in oned:
                oned[local] = val

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
        return _first_by_keys(oned, NUMERIC_SYNONYMS.get(key, []))

    def fuzzy_numeric(patterns: List[str]) -> Optional[Decimal]:
        for p in patterns:
            for k, v in oned.items():
                if p in k and v is not None:
                    return v
        return None

    Sales = G("sales") or fuzzy_numeric(["revenuefromoperations", "revenue", "turnover", "sales"])
    OtherIncome_normal = G("other_income") or fuzzy_numeric(["otherincome", "nonoperating"])
    Exceptional = G("exceptional") or fuzzy_numeric(["exceptionalitemsbefortax", "exceptionalitemsbeforetax", "exceptionalitems"])
    # Keep signed exceptional value (sign(ExceptionalItemsBeforeTax))
    if Exceptional is not None:
        Exceptional = Decimal(Exceptional)  # already signed from parser

    FinanceCosts = G("finance_costs") or fuzzy_numeric(["financecosts", "interest", "finance"])
    Depreciation = G("depreciation") or fuzzy_numeric(["depreciationdepletionandamortisationexpense", "depreciation", "amortisation"])
    PBT = G("pbt") or fuzzy_numeric(["profitbeforetax", "pbt"])
    TaxTotal = G("tax_expense") or fuzzy_numeric(["taxexpense", "totaltaxexpenses", "taxexpenses"])
    CurrentTax = G("current_tax") or fuzzy_numeric(["currenttax"])
    DeferredTax = G("deferred_tax") or fuzzy_numeric(["deferredtax"])
    if TaxTotal is not None:
        if CurrentTax is None and DeferredTax is not None:
            CurrentTax = TaxTotal - DeferredTax
        elif DeferredTax is None and CurrentTax is not None:
            DeferredTax = TaxTotal - CurrentTax
    elif CurrentTax is not None and DeferredTax is not None:
        TaxTotal = CurrentTax + DeferredTax

    PAT = G("net_profit") or fuzzy_numeric(["profitlossforperiod", "netprofit"])
    EPS = G("eps_basic") or fuzzy_numeric(
        ["basicearningslosspersharefromcontinuingoperations", "basicearningslosspershare", "eps", "earningspershare"]
    )

    # Other Income = Other Income_normal + Exceptional items
    oi_n = OtherIncome_normal if OtherIncome_normal is not None else Decimal(0)
    exc = Exceptional if Exceptional is not None else Decimal(0)
    OtherIncome = None
    if OtherIncome_normal is not None or Exceptional is not None:
        OtherIncome = oi_n + exc

    # Expenses = sales + Other Income - Profit Before tax - Depreciation - Interest
    Expenses = None
    if Sales is not None and PBT is not None:
        oi = OtherIncome if OtherIncome is not None else Decimal(0)
        dep = Depreciation if Depreciation is not None else Decimal(0)
        interest = FinanceCosts if FinanceCosts is not None else Decimal(0)
        Expenses = Sales + oi - PBT - dep - interest

    # Operating Profit = Sales - Expenses
    OperatingProfit = (Sales - Expenses) if (Sales is not None and Expenses is not None) else None
    EBITDA = OperatingProfit
    # Revenue Growth % mapping provided as Sales - Operating Profit
    RevenueGrowth = (Sales - OperatingProfit) if (Sales is not None and OperatingProfit is not None) else None
    EBITDAMargin = _pct(EBITDA, Sales) if EBITDA is not None else None
    # EBIT = PBT + Interest - Other Income
    EBIT = None
    if PBT is not None:
        interest = FinanceCosts if FinanceCosts is not None else Decimal(0)
        oi = OtherIncome if OtherIncome is not None else Decimal(0)
        EBIT = PBT + interest - oi
    OPM = _pct(OperatingProfit, Sales) if OperatingProfit is not None else None
    Tax_percent = _pct(TaxTotal, PBT) if TaxTotal is not None else None
    NetProfit = PAT
    NetProfitMargin = _pct(NetProfit, Sales) if NetProfit is not None else None

    return {
        "company_name": meta.get("company_name"),
        "company_symbol": meta.get("company_symbol"),
        "currency": meta.get("currency"),
        "level_of_rounding": meta.get("level_of_rounding"),
        "reporting_type": meta.get("reporting_type"),
        "NatureOfReport": meta.get("nature_of_report"),
        "Sales": float(Sales) if Sales is not None else None,
        "ExceptionalItems": float(Exceptional) if Exceptional is not None else None,
        "OtherIncome_normal": float(OtherIncome_normal) if OtherIncome_normal is not None else None,
        "OtherIncome": float(OtherIncome) if OtherIncome is not None else None,
        "Interest": float(FinanceCosts) if FinanceCosts is not None else None,
        "Depreciation": float(Depreciation) if Depreciation is not None else None,
        "ProfitBeforeTax": float(PBT) if PBT is not None else None,
        "ProfitAfterTax": float(PAT) if PAT is not None else None,
        "Tax": float(TaxTotal) if TaxTotal is not None else None,
        "CurrentTax": float(CurrentTax) if CurrentTax is not None else None,
        "DeferredTax": float(DeferredTax) if DeferredTax is not None else None,
        "Tax_percent": float(Tax_percent) if Tax_percent is not None else None,
        "EPS_in_RS": float(EPS) if EPS is not None else None,
        "NetProfit": float(NetProfit) if NetProfit is not None else None,
        "Expenses": float(Expenses) if Expenses is not None else None,
        "OperatingProfit": float(OperatingProfit) if OperatingProfit is not None else None,
        "EBITDA": float(EBITDA) if EBITDA is not None else None,
        "RevenueGrowth_percent": float(RevenueGrowth) if RevenueGrowth is not None else None,
        "EBITDA_Margin_percent": float(EBITDAMargin) if EBITDAMargin is not None else None,
        "EBIT": float(EBIT) if EBIT is not None else None,
        "OPM_percentage": float(OPM) if OPM is not None else None,
        "NetProfitMargin": float(NetProfitMargin) if NetProfitMargin is not None else None,
    }


# -------------------- API Route --------------------



# -------------------- Format Conversion for XML --------------------

def convert_xml_grouped_to_list(grouped_data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Convert XML extraction's grouped dictionary format to flat list format (matching HTML service format).
    XML returns: {"elementname": [{"contextRef": "oned", "value": 123}, ...]}
    HTML returns: [{"localname": "elementname", "contextRef": "oned", "value": 123}, ...]
    """
    flat_list: List[Dict[str, Any]] = []
    
    if not grouped_data:
        return flat_list
    
    for element_name, occurrences in grouped_data.items():
        if not occurrences:
            continue
        for occurrence in occurrences:
            record = {
                "localname": element_name.lower(),
                "contextRef": occurrence.get("contextRef"),
                "contextref": occurrence.get("contextRef"),
                "unitRef": occurrence.get("unitRef"),
                "value": occurrence.get("value"),
            }
            flat_list.append(record)
    
    return flat_list


def calculate_metrics_fourd(extracted_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Annual metrics for Annual_Metrics (aligned with db/seed.py Annual catalog).

    - Annual P&L particulars: values ONLY from contextRef=FourD
    - Balancesheet / Cashflow / Ratios: ignore contextRef (first numeric per tag from any context)
    """
    # P&L map: FourD only (no fallback to other contexts)
    fourd: Dict[str, Decimal] = {}
    for item in extracted_data:
        ctx = (item.get("contextRef") or item.get("contextref") or "").strip().lower()
        if ctx != "fourd":
            continue
        local = str(item.get("localname", "")).strip().lower()
        val = _to_decimal(item.get("value"))
        if local and val is not None and local not in fourd:
            fourd[local] = val

    # BS / CF / Ratios map: any context
    any_ctx: Dict[str, Decimal] = {}
    for item in extracted_data:
        local = str(item.get("localname", "")).strip().lower()
        val = _to_decimal(item.get("value"))
        if local and val is not None and local not in any_ctx:
            any_ctx[local] = val

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

    def g_pl(key: str) -> Optional[Decimal]:
        return _first_by_keys(fourd, NUMERIC_SYNONYMS.get(key, []))

    def fuzzy_pl(patterns: List[str]) -> Optional[Decimal]:
        for p in patterns:
            for k, v in fourd.items():
                if p in k and v is not None:
                    return v
        return None

    def g_any(key: str) -> Optional[Decimal]:
        return _first_by_keys(any_ctx, NUMERIC_SYNONYMS.get(key, []))

    def fuzzy_any(patterns: List[str]) -> Optional[Decimal]:
        for p in patterns:
            for k, v in any_ctx.items():
                if p in k and v is not None:
                    return v
        return None

    # --- Annual P&L (seed: Annual / P&L) — FourD only ---
    Sales = g_pl("sales") or fuzzy_pl(["revenuefromoperations", "revenue", "turnover", "sales"])
    OtherIncome_normal = g_pl("other_income") or fuzzy_pl(["otherincome"])
    Exceptional = g_pl("exceptional") or fuzzy_pl(
        ["exceptionalitemsbeforetax", "exceptionalitemsbefortax", "exceptionalitems"]
    )
    FinanceCosts = g_pl("finance_costs") or fuzzy_pl(["financecosts", "interest"])
    Depreciation = g_pl("depreciation") or fuzzy_pl(
        ["depreciationdepletionandamortisationexpense", "depreciation"]
    )
    PBT = g_pl("pbt") or fuzzy_pl(["profitbeforetax", "pbt"])
    TaxTotal = g_pl("tax_expense") or fuzzy_pl(["taxexpense", "totaltaxexpenses"])
    CurrentTax = g_pl("current_tax") or fuzzy_pl(["currenttax"])
    DeferredTax = g_pl("deferred_tax") or fuzzy_pl(["deferredtax"])
    if TaxTotal is not None:
        if CurrentTax is None and DeferredTax is not None:
            CurrentTax = TaxTotal - DeferredTax
        elif DeferredTax is None and CurrentTax is not None:
            DeferredTax = TaxTotal - CurrentTax
    elif CurrentTax is not None and DeferredTax is not None:
        TaxTotal = CurrentTax + DeferredTax

    PAT = g_pl("net_profit") or fuzzy_pl(["profitlossforperiod", "netprofit"])
    EPS = g_pl("eps_basic") or fuzzy_pl(
        ["basicearningslosspersharefromcontinuingoperations", "eps"]
    )

    oi_n = OtherIncome_normal if OtherIncome_normal is not None else Decimal(0)
    exc = Exceptional if Exceptional is not None else Decimal(0)
    OtherIncome = (oi_n + exc) if (OtherIncome_normal is not None or Exceptional is not None) else None

    Expenses = None
    if Sales is not None and PBT is not None:
        oi = OtherIncome if OtherIncome is not None else Decimal(0)
        dep = Depreciation if Depreciation is not None else Decimal(0)
        interest = FinanceCosts if FinanceCosts is not None else Decimal(0)
        Expenses = Sales + oi - PBT - dep - interest

    OperatingProfit = (Sales - Expenses) if (Sales is not None and Expenses is not None) else None
    EBITDA = OperatingProfit
    RevenueGrowth = (Sales - OperatingProfit) if (Sales is not None and OperatingProfit is not None) else None
    EBITDAMargin = _pct(EBITDA, Sales)
    EBIT = None
    if PBT is not None:
        interest = FinanceCosts if FinanceCosts is not None else Decimal(0)
        oi = OtherIncome if OtherIncome is not None else Decimal(0)
        EBIT = PBT + interest - oi
    OPM = _pct(OperatingProfit, Sales)
    Tax_percent = _pct(TaxTotal, PBT)
    NetProfit = PAT
    NetProfitMargin = _pct(NetProfit, Sales)

    # Dividend Paid / Payout are Annual P&L in seed → FourD only
    DividendPaid = g_any("dividends_paid") or fuzzy_pl(
        ["dividendspaidclassifiedasfinancingactivities", "dividendspaid"]
    )
    DividendPayout = _pct(DividendPaid, NetProfit) if DividendPaid is not None else None

    # --- Balancesheet (seed: Annual / Balancesheet) — any context ---
    EquityCapital = g_any("equity_share_capital") or fuzzy_any(["equitysharecapital", "equitycapital"])
    Reserves = g_any("other_equity") or fuzzy_any(["otherequity", "reserves"])
    TotalLiabilities = g_any("liabilities") or fuzzy_any(["liabilities", "totalliabilities"])
    CurrentAssets = g_any("current_assets") or fuzzy_any(["currentassets"])
    CurrentLiabilities = g_any("current_liabilities") or fuzzy_any(["currentliabilities"])
    Inventories = g_any("inventories") or fuzzy_any(["inventories", "inventory"])
    TotalEquity = g_any("equity") or fuzzy_any(["equity", "totalequity"])
    TotalAssets = g_any("assets") or fuzzy_any(["assets", "totalassets"])
    DebtEquityRatio = g_any("debt_equity_ratio") or fuzzy_any(["debtequityratio", "debttoequity"])

    CurrentRatio = _div(CurrentAssets, CurrentLiabilities)
    QuickRatio = None
    if CurrentAssets is not None and CurrentLiabilities not in (None, Decimal("0")):
        inv = Inventories if Inventories is not None else Decimal(0)
        QuickRatio = (CurrentAssets - inv) / CurrentLiabilities

    WorkingCapital = None
    if CurrentAssets is not None and CurrentLiabilities is not None:
        WorkingCapital = CurrentAssets - CurrentLiabilities

    CWIP = g_any("cwip") or fuzzy_any(["capitalworkinprogress"])
    NonCurInv = g_any("noncurrent_investments") or fuzzy_any(["noncurrentinvestments"])
    CurInv = g_any("current_investments") or fuzzy_any(["currentinvestments"])
    Investments = None
    if NonCurInv is not None or CurInv is not None:
        Investments = (NonCurInv or Decimal(0)) + (CurInv or Decimal(0))

    Borrowings = None
    if DebtEquityRatio is not None and TotalEquity is not None:
        Borrowings = DebtEquityRatio * TotalEquity

    DebtToAssets = _div(Borrowings, TotalAssets)

    # --- Cashflow (seed: Annual / Cashflow) — any context ---
    CFO = g_any("cfo") or fuzzy_any(["cashflowsfromusedinoperatingactivities", "cashflowfromoperating"])
    CFI = g_any("cfi") or fuzzy_any(["cashflowsfromusedininvestingactivities", "cashflowfrominvesting"])
    CFF = g_any("cff") or fuzzy_any(["cashflowsfromusedinfinancingactivities", "cashflowfromfinancing"])
    DividendsReceived = g_any("dividends_received") or fuzzy_any(
        ["dividendsreceivedclassifiedasinvestingactivities", "dividendsreceived"]
    )

    CashConversion = _div(CFO, EBITDA)
    NetCashFlow = None
    if CFO is not None or CFI is not None or CFF is not None:
        NetCashFlow = (CFO or Decimal(0)) + (CFI or Decimal(0)) + (CFF or Decimal(0))
    CFO_OP = _div(CFO, OperatingProfit)

    # --- Ratios (seed: Annual / Ratios) — any context inputs + P&L FourD where needed ---
    ROA = _pct(NetProfit, TotalAssets)
    ROE = _pct(NetProfit, TotalEquity)
    ROCE = None
    if EBIT is not None and TotalEquity is not None:
        capital = TotalEquity + (Borrowings or Decimal(0))
        ROCE = _pct(EBIT, capital)

    TradeRecvNC = g_any("trade_receivables_noncurrent") or fuzzy_any(["tradereceivablesnoncurrent"])
    TradeRecvC = g_any("trade_receivables_current") or fuzzy_any(
        ["tradereceivablescurrent", "tradereceivables"]
    )
    DebtorDays = None
    if Sales not in (None, Decimal("0")) and (TradeRecvNC is not None or TradeRecvC is not None):
        recv = (TradeRecvNC or Decimal(0)) + (TradeRecvC or Decimal(0))
        DebtorDays = (recv / Sales) * Decimal(365)

    return {
        "company_name": meta.get("company_name"),
        "company_symbol": meta.get("company_symbol"),
        "currency": meta.get("currency"),
        "level_of_rounding": meta.get("level_of_rounding"),
        "reporting_type": meta.get("reporting_type"),
        "Sales": float(Sales) if Sales is not None else None,
        "ExceptionalItems": float(Exceptional) if Exceptional is not None else None,
        "OtherIncome_normal": float(OtherIncome_normal) if OtherIncome_normal is not None else None,
        "OtherIncome": float(OtherIncome) if OtherIncome is not None else None,
        "Interest": float(FinanceCosts) if FinanceCosts is not None else None,
        "Depreciation": float(Depreciation) if Depreciation is not None else None,
        "ProfitBeforeTax": float(PBT) if PBT is not None else None,
        "ProfitAfterTax": float(PAT) if PAT is not None else None,
        "Tax": float(TaxTotal) if TaxTotal is not None else None,
        "CurrentTax": float(CurrentTax) if CurrentTax is not None else None,
        "DeferredTax": float(DeferredTax) if DeferredTax is not None else None,
        "Tax_percent": float(Tax_percent) if Tax_percent is not None else None,
        "EPS_in_RS": float(EPS) if EPS is not None else None,
        "NetProfit": float(NetProfit) if NetProfit is not None else None,
        "Expenses": float(Expenses) if Expenses is not None else None,
        "OperatingProfit": float(OperatingProfit) if OperatingProfit is not None else None,
        "EBITDA": float(EBITDA) if EBITDA is not None else None,
        "RevenueGrowth_percent": float(RevenueGrowth) if RevenueGrowth is not None else None,
        "EBITDA_Margin_percent": float(EBITDAMargin) if EBITDAMargin is not None else None,
        "EBIT": float(EBIT) if EBIT is not None else None,
        "OPM_percentage": float(OPM) if OPM is not None else None,
        "NetProfitMargin": float(NetProfitMargin) if NetProfitMargin is not None else None,
        "DividendPaid": float(DividendPaid) if DividendPaid is not None else None,
        "DividendPayout_percent": float(DividendPayout) if DividendPayout is not None else None,
        "EquityCapital": float(EquityCapital) if EquityCapital is not None else None,
        "Reserves": float(Reserves) if Reserves is not None else None,
        "TotalLiabilities": float(TotalLiabilities) if TotalLiabilities is not None else None,
        "CurrentRatio": float(CurrentRatio) if CurrentRatio is not None else None,
        "QuickRatio": float(QuickRatio) if QuickRatio is not None else None,
        "TotalEquity": float(TotalEquity) if TotalEquity is not None else None,
        "TotalAssets": float(TotalAssets) if TotalAssets is not None else None,
        "DebtToEquity": float(DebtEquityRatio) if DebtEquityRatio is not None else None,
        "WorkingCapital": float(WorkingCapital) if WorkingCapital is not None else None,
        "CWIP": float(CWIP) if CWIP is not None else None,
        "Investments": float(Investments) if Investments is not None else None,
        "Borrowings": float(Borrowings) if Borrowings is not None else None,
        "DebtToAssets": float(DebtToAssets) if DebtToAssets is not None else None,
        "CashFromOperatingActivity": float(CFO) if CFO is not None else None,
        "CashFromInvestingActivity": float(CFI) if CFI is not None else None,
        "DividendsReceived": float(DividendsReceived) if DividendsReceived is not None else None,
        "CashFromFinancingActivity": float(CFF) if CFF is not None else None,
        "CashConversionRatio": float(CashConversion) if CashConversion is not None else None,
        "NetCashFlow": float(NetCashFlow) if NetCashFlow is not None else None,
        "CFO_OP": float(CFO_OP) if CFO_OP is not None else None,
        "ROA": float(ROA) if ROA is not None else None,
        "ROE": float(ROE) if ROE is not None else None,
        "ROCE_percent": float(ROCE) if ROCE is not None else None,
        "DebtorDays": float(DebtorDays) if DebtorDays is not None else None,
    }
