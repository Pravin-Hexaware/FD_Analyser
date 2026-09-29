"""Seed User_Roles and Metrics catalog (particulars + IND-AS tags/formulas)."""
from __future__ import annotations

from db.models import MetricDefinition, UserRole

DEFAULT_ROLES = ("Analyst", "Admin")

# (metric_category, sub_category, particulars, ind_as)
# ind_as: XBRL localname OR formula using particulars / XBRL names / *100 for percents
DEFAULT_METRICS = [
    # ---------- quarterly (OneD) ----------
    ("quarterly", "quarterly", "Sales", "RevenueFromOperations"),
    ("quarterly", "quarterly", "Exceptional items", "ExceptionalItemsBeforeTax"),
    ("quarterly", "quarterly", "Other Income_normal", "OtherIncome"),
    ("quarterly", "quarterly", "Interest", "FinanceCosts"),
    ("quarterly", "quarterly", "Depreciation", "DepreciationDepletionAndAmortisationExpense"),
    ("quarterly", "quarterly", "Profit before tax", "ProfitBeforeTax"),
    ("quarterly", "quarterly", "Profit After Tax", "ProfitLossForPeriod"),
    ("quarterly", "quarterly", "Tax", "TaxExpense"),
    ("quarterly", "quarterly", "EPS in Rs", "BasicEarningsLossPerShareFromContinuingOperations"),
    ("quarterly", "quarterly", "Net Profit", "ProfitLossForPeriod"),
    ("quarterly", "quarterly", "Other Income", "OtherIncome_normal+ExceptionalItems"),
    ("quarterly", "quarterly", "Expenses", "Sales+OtherIncome-ProfitBeforeTax-Depreciation-Interest"),
    ("quarterly", "quarterly", "Operating Profit", "Sales-Expenses"),
    ("quarterly", "quarterly", "EBITDA", "OperatingProfit"),
    ("quarterly", "quarterly", "Revenue Growth %", "Sales-OperatingProfit"),
    ("quarterly", "quarterly", "EBITDA Margin %", "(EBITDA/Sales)*100"),
    ("quarterly", "quarterly", "EBIT", "ProfitBeforeTax+Interest-OtherIncome"),
    ("quarterly", "quarterly", "OPM %", "(OperatingProfit/Sales)*100"),
    ("quarterly", "quarterly", "Tax %", "(Tax/ProfitBeforeTax)*100"),
    ("quarterly", "quarterly", "Net Profit Margin", "(NetProfit/Sales)*100"),
    # ---------- Annual P&L (FourD) ----------
    ("Annual", "P&L", "Sales", "RevenueFromOperations"),
    ("Annual", "P&L", "Exceptional items", "ExceptionalItemsBeforeTax"),
    ("Annual", "P&L", "Other Income_normal", "OtherIncome"),
    ("Annual", "P&L", "Interest", "FinanceCosts"),
    ("Annual", "P&L", "Depreciation", "DepreciationDepletionAndAmortisationExpense"),
    ("Annual", "P&L", "Profit before tax", "ProfitBeforeTax"),
    ("Annual", "P&L", "Profit After Tax", "ProfitLossForPeriod"),
    ("Annual", "P&L", "Tax", "TaxExpense"),
    ("Annual", "P&L", "EPS in Rs", "BasicEarningsLossPerShareFromContinuingOperations"),
    ("Annual", "P&L", "Net Profit", "ProfitLossForPeriod"),
    ("Annual", "P&L", "Other Income", "OtherIncome_normal+ExceptionalItems"),
    ("Annual", "P&L", "Expenses", "Sales+OtherIncome-ProfitBeforeTax-Depreciation-Interest"),
    ("Annual", "P&L", "Operating Profit", "Sales-Expenses"),
    ("Annual", "P&L", "EBITDA", "OperatingProfit"),
    ("Annual", "P&L", "Revenue Growth %", "Sales-OperatingProfit"),
    ("Annual", "P&L", "EBITDA Margin %", "(EBITDA/Sales)*100"),
    ("Annual", "P&L", "EBIT", "ProfitBeforeTax+Interest-OtherIncome"),
    ("Annual", "P&L", "OPM %", "(OperatingProfit/Sales)*100"),
    ("Annual", "P&L", "Tax %", "(Tax/ProfitBeforeTax)*100"),
    ("Annual", "P&L", "Net Profit Margin", "(NetProfit/Sales)*100"),
    ("Annual", "P&L", "Divident Paid", "DividendsPaid"),
    ("Annual", "P&L", "Divident Payout %", "(DividendPaid/NetProfit)*100"),
    # ---------- Annual Balancesheet (any context) ----------
    ("Annual", "Balancesheet", "Equity Capital", "EquityShareCapital"),
    ("Annual", "Balancesheet", "Reserves", "OtherEquity"),
    ("Annual", "Balancesheet", "Total Liabilities", "Liabilities"),
    ("Annual", "Balancesheet", "Current Ratio", "CurrentAssets/CurrentLiabilities"),
    ("Annual", "Balancesheet", "Quick Ratio", "(CurrentAssets-Inventories)/CurrentLiabilities"),
    ("Annual", "Balancesheet", "Total Equity", "Equity"),
    ("Annual", "Balancesheet", "Total Assets", "Assets"),
    ("Annual", "Balancesheet", "Debt-to-Equity", "DebtEquityRatio"),
    ("Annual", "Balancesheet", "Working capital", "CurrentAssets-CurrentLiabilities"),
    ("Annual", "Balancesheet", "CWIP", "CapitalWorkInProgress"),
    ("Annual", "Balancesheet", "Investments", "NonCurrentInvestments+CurrentInvestments"),
    ("Annual", "Balancesheet", "Borrowings", "DebtToEquity*TotalEquity"),
    ("Annual", "Balancesheet", "Debt-to-Assets", "Borrowings/TotalAssets"),
    # ---------- Annual Cashflow ----------
    ("Annual", "Cashflow", "Cash from Operating Activity", "CashFlowsFromUsedInOperatingActivities"),
    ("Annual", "Cashflow", "Cash from Investing Activity", "CashFlowsFromUsedInInvestingActivities"),
    ("Annual", "Cashflow", "Dividends received", "DividendsReceivedClassifiedAsInvestingActivities"),
    ("Annual", "Cashflow", "Cash from Financing Activity", "CashFlowsFromUsedInFinancingActivities"),
    ("Annual", "Cashflow", "Cash Conversion Ratio", "CashFromOperatingActivity/EBITDA"),
    ("Annual", "Cashflow", "Net Cash Flow", "CashFromOperatingActivity+CashFromInvestingActivity+CashFromFinancingActivity"),
    ("Annual", "Cashflow", "CFO/OP", "CashFromOperatingActivity/OperatingProfit"),
    # ---------- Annual Ratios ----------
    ("Annual", "Ratios", "ROA", "(NetProfit/TotalAssets)*100"),
    ("Annual", "Ratios", "ROE", "(NetProfit/TotalEquity)*100"),
    ("Annual", "Ratios", "ROCE %", "(EBIT/(TotalEquity+Borrowings))*100"),
    ("Annual", "Ratios", "Debtor Days", "((TradeReceivablesNonCurrent+TradeReceivablesCurrent)/Sales)*365"),
]


async def seed_defaults() -> None:
    for role_name in DEFAULT_ROLES:
        await UserRole.get_or_create(role=role_name)

    existing = await MetricDefinition.all().count()
    if existing == 0:
        await MetricDefinition.bulk_create(
            [
                MetricDefinition(
                    metric_category=cat,
                    sub_category=sub,
                    particulars=part,
                    ind_as=ind_as,
                )
                for cat, sub, part, ind_as in DEFAULT_METRICS
            ]
        )
        print(f"[db] Seeded {len(DEFAULT_METRICS)} metric definitions with IND-AS.")
        return

    # Backfill / refresh IND-AS for existing catalog rows
    updated = 0
    for cat, sub, part, ind_as in DEFAULT_METRICS:
        row = await MetricDefinition.get_or_none(
            metric_category=cat,
            sub_category=sub,
            particulars=part,
        )
        if row is None:
            await MetricDefinition.create(
                metric_category=cat,
                sub_category=sub,
                particulars=part,
                ind_as=ind_as,
            )
            updated += 1
        elif not row.ind_as or row.ind_as != ind_as:
            row.ind_as = ind_as
            await row.save(update_fields=["ind_as"])
            updated += 1
    print(f"[db] Metrics catalog present ({existing} rows); IND-AS upserted/refreshed ({updated} changes).")
