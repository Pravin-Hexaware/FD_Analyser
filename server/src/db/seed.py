"""Seed User_Roles and Metrics catalog."""
from __future__ import annotations

from db.models import MetricDefinition, UserRole

DEFAULT_ROLES = ("Analyst", "Admin")

# From Excel Metrics sheet
DEFAULT_METRICS = [
    # quarterly
    ("quarterly", "quarterly", "Sales"),
    ("quarterly", "quarterly", "Exceptional items"),
    ("quarterly", "quarterly", "Other Income_normal"),
    ("quarterly", "quarterly", "Interest"),
    ("quarterly", "quarterly", "Depreciation"),
    ("quarterly", "quarterly", "Profit before tax"),
    ("quarterly", "quarterly", "Profit After Tax"),
    ("quarterly", "quarterly", "Tax"),
    ("quarterly", "quarterly", "EPS in Rs"),
    ("quarterly", "quarterly", "Net Profit"),
    ("quarterly", "quarterly", "Other Income"),
    ("quarterly", "quarterly", "Expenses"),
    ("quarterly", "quarterly", "Operating Profit"),
    ("quarterly", "quarterly", "EBITDA"),
    ("quarterly", "quarterly", "Revenue Growth %"),
    ("quarterly", "quarterly", "EBITDA Margin %"),
    ("quarterly", "quarterly", "EBIT"),
    ("quarterly", "quarterly", "OPM %"),
    ("quarterly", "quarterly", "Tax %"),
    ("quarterly", "quarterly", "Net Profit Margin"),
    # annual P_L
    ("Annual", "P&L", "Sales"),
    ("Annual", "P&L", "Exceptional items"),
    ("Annual", "P&L", "Other Income_normal"),
    ("Annual", "P&L", "Interest"),
    ("Annual", "P&L", "Depreciation"),
    ("Annual", "P&L", "Profit before tax"),
    ("Annual", "P&L", "Profit After Tax"),
    ("Annual", "P&L", "Tax"),
    ("Annual", "P&L", "EPS in Rs"),
    ("Annual", "P&L", "Net Profit"),
    ("Annual", "P&L", "Other Income"),
    ("Annual", "P&L", "Expenses"),
    ("Annual", "P&L", "Operating Profit"),
    ("Annual", "P&L", "EBITDA"),
    ("Annual", "P&L", "Revenue Growth %"),
    ("Annual", "P&L", "EBITDA Margin %"),
    ("Annual", "P&L", "EBIT"),
    ("Annual", "P&L", "OPM %"),
    ("Annual", "P&L", "Tax %"),
    ("Annual", "P&L", "Net Profit Margin"),
    ("Annual", "P&L", "Divident Paid"),
    ("Annual", "P&L", "Divident Payout %"),
    # annual Balancesheet
    ("Annual", "Balancesheet", "Equity Capital"),
    ("Annual", "Balancesheet", "Reserves"),
    ("Annual", "Balancesheet", "Total Liabilities"),
    ("Annual", "Balancesheet", "Current Ratio"),
    ("Annual", "Balancesheet", "Quick Ratio"),
    ("Annual", "Balancesheet", "Total Equity"),
    ("Annual", "Balancesheet", "Total Assets"),
    ("Annual", "Balancesheet", "Debt-to-Equity"),
    ("Annual", "Balancesheet", "Working capital"),
    ("Annual", "Balancesheet", "CWIP"),
    ("Annual", "Balancesheet", "Investments"),
    ("Annual", "Balancesheet", "Borrowings"),
    ("Annual", "Balancesheet", "Debt-to-Assets"),
    # annual cashflow
    ("Annual", "Cashflow", "Cash from Operating Activity"),
    ("Annual", "Cashflow", "Cash from Investing Activity"),
    ("Annual", "Cashflow", "Dividends received"),
    ("Annual", "Cashflow", "Cash from Financing Activity"),
    ("Annual", "Cashflow", "Cash Conversion Ratio"),
    ("Annual", "Cashflow", "Net Cash Flow"),
    ("Annual", "Cashflow", "CFO/OP"),

    ("Annual", "Ratios", "ROA"),
    ("Annual", "Ratios", "ROE"),
    ("Annual", "Ratios", "ROCE %"),
    ("Annual", "Ratios", "Debtor Days"),
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
