"""Seed User_Roles and Metrics catalog."""
from __future__ import annotations

from db.models import MetricDefinition, UserRole

DEFAULT_ROLES = ("Analyst", "Admin")

# From Excel Metrics sheet
DEFAULT_METRICS = [
    # quarterly
    ("quarterly", "quarterly", "Sales / Revenue"),
    ("quarterly", "quarterly", "Expenses"),
    ("quarterly", "quarterly", "Operating Profit"),
    ("quarterly", "quarterly", "OPM %"),
    ("quarterly", "quarterly", "Other Income"),
    ("quarterly", "quarterly", "Profit Before Tax (PBT)"),
    ("quarterly", "quarterly", "Current Tax"),
    ("quarterly", "quarterly", "Deferred Tax"),
    ("quarterly", "quarterly", "Total Tax"),
    ("quarterly", "quarterly", "Tax %"),
    ("quarterly", "quarterly", "Basic EPS"),
    ("quarterly", "quarterly", "EPS (Rs)"),
    ("quarterly", "quarterly", "PAT"),
    ("quarterly", "quarterly", "Net Profit Margin %"),
    ("quarterly", "quarterly", "EBITDA"),
    ("quarterly", "quarterly", "EBITDA Margin %"),
    ("quarterly", "quarterly", "EBIT"),
    ("quarterly", "quarterly", "EBIT Margin %"),
    ("quarterly", "quarterly", "Current Ratio"),
    ("quarterly", "quarterly", "Quick Ratio"),
    ("quarterly", "quarterly", "Cash Ratio"),
    ("quarterly", "quarterly", "Debt-to-Equity"),
    ("quarterly", "quarterly", "Debt-to-Assets"),
    ("quarterly", "quarterly", "Working Capital"),
    ("quarterly", "quarterly", "Revenue Growth %"),
    ("quarterly", "quarterly", "Operating Cash Flow"),
    ("quarterly", "quarterly", "OCF Margin %"),
    ("quarterly", "quarterly", "Free Cash Flow"),
    ("quarterly", "quarterly", "Cash Conversion Ratio"),
    ("quarterly", "quarterly", "Diluted EPS"),
    ("quarterly", "quarterly", "Dividend Payout Ratio %"),
    # annual P_L
    ("annual", "P_L", "Sales / Revenue"),
    ("annual", "P_L", "Expenses"),
    ("annual", "P_L", "Operating Profit"),
    ("annual", "P_L", "OPM %"),
    ("annual", "P_L", "Other Income"),
    ("annual", "P_L", "Profit Before Tax (PBT)"),
    ("annual", "P_L", "Current Tax"),
    ("annual", "P_L", "Deferred Tax"),
    ("annual", "P_L", "Total Tax"),
    ("annual", "P_L", "Tax %"),
    ("annual", "P_L", "Basic EPS"),
    ("annual", "P_L", "EPS (Rs)"),
    # annual Balancesheet
    ("annual", "Balancesheet", "Equity Share Capital"),
    ("annual", "Balancesheet", "Reserves"),
    ("annual", "Balancesheet", "Total Equity"),
    ("annual", "Balancesheet", "Borrowings"),
    ("annual", "Balancesheet", "Trade Receivables"),
    ("annual", "Balancesheet", "Inventory"),
    ("annual", "Balancesheet", "Cash & Cash Equivalents"),
    ("annual", "Balancesheet", "Short-Term Investments"),
    ("annual", "Balancesheet", "Current Assets"),
    ("annual", "Balancesheet", "Current Liabilities"),
    ("annual", "Balancesheet", "Trade Payables"),
    ("annual", "Balancesheet", "Fixed Assets"),
    ("annual", "Balancesheet", "CWIP (Capital Work-in-Progress)"),
    ("annual", "Balancesheet", "Investments"),
    ("annual", "Balancesheet", "Total Assets"),
    # annual cashflow
    ("annual", "cashflow", "Cash from Operating Activities (CFO)"),
    ("annual", "cashflow", "Cash from Investing Activities (CFI)"),
    ("annual", "cashflow", "Cash from Financing Activities (CFF)"),
    ("annual", "cashflow", "Capital Expenditure (CapEx)"),
    ("annual", "cashflow", "Dividend Paid"),
    ("annual", "cashflow", "Interest Paid"),
    ("annual", "cashflow", "Cash & Cash Equivalents at End of Period"),
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
                )
                for cat, sub, part in DEFAULT_METRICS
            ]
        )
        print(f"[db] Seeded {len(DEFAULT_METRICS)} metric definitions.")
    else:
        print(f"[db] Metrics catalog already present ({existing} rows).")
