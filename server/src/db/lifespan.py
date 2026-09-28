"""FastAPI lifespan: wipe (optional), Tortoise init, schema migrate, seed."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from tortoise import Tortoise, connections

from config.settings import WIPE_DB_ON_STARTUP
from db.config import ensure_data_dirs, get_tortoise_config, wipe_database_file
from db.seed import seed_defaults

logger = logging.getLogger(__name__)


async def _migrate_company_membership_schema() -> None:
    """Backfill the company_info membership columns for existing SQLite files."""
    connection = connections.get("default")
    try:
        _, columns = await connection.execute_query("PRAGMA table_info(company_info)")
    except Exception:
        return
    column_names = {row[1] for row in columns}

    if "is_in_nifty_500" not in column_names:
        await connection.execute_query(
            "ALTER TABLE company_info ADD COLUMN is_in_nifty_500 VARCHAR(1) NOT NULL DEFAULT 'F'"
        )
    if "nifty500_updated_at" not in column_names:
        await connection.execute_query(
            "ALTER TABLE company_info ADD COLUMN nifty500_updated_at DATETIME"
        )
    await connection.execute_query(
        "CREATE INDEX IF NOT EXISTS idx_company_info_is_in_nifty_500 "
        "ON company_info (is_in_nifty_500)"
    )
    await connection.execute_query('DROP TABLE IF EXISTS "Indexes"')


async def _migrate_metrics_ind_as_column() -> None:
    """Add Metrics.ind_as if missing."""
    connection = connections.get("default")
    try:
        _, columns = await connection.execute_query('PRAGMA table_info("Metrics")')
    except Exception:
        return
    column_names = {row[1] for row in columns}
    if "ind_as" not in column_names:
        await connection.execute_query(
            'ALTER TABLE "Metrics" ADD COLUMN ind_as VARCHAR(512)'
        )
        print("[db] Added Metrics.ind_as column")


async def _rebuild_table_without_json(
    table: str,
    create_sql: str,
    copy_columns: list[str],
) -> None:
    """
    If `table` still has JSON blob columns, rebuild it without them (SQLite).
    Preserves scalar metric values.
    """
    connection = connections.get("default")
    try:
        _, columns = await connection.execute_query(f'PRAGMA table_info("{table}")')
    except Exception:
        return
    if not columns:
        return
    column_names = {row[1] for row in columns}
    json_markers = {
        "metrics_json",
        "p_l_json",
        "balance_sheet_json",
        "cash_flow_json",
        "ratios_json",
    }
    if not (column_names & json_markers):
        return

    tmp = f"{table}__new"
    await connection.execute_query(f'DROP TABLE IF EXISTS "{tmp}"')
    await connection.execute_query(create_sql.replace(f'"{table}"', f'"{tmp}"', 1))

    present = [c for c in copy_columns if c in column_names]
    cols_csv = ", ".join(f'"{c}"' for c in present)
    await connection.execute_query(
        f'INSERT INTO "{tmp}" ({cols_csv}) SELECT {cols_csv} FROM "{table}"'
    )
    await connection.execute_query(f'DROP TABLE "{table}"')
    await connection.execute_query(f'ALTER TABLE "{tmp}" RENAME TO "{table}"')
    print(f"[db] Rebuilt {table} without JSON columns")


_QUARTERLY_CREATE = """
CREATE TABLE "Quarterly_Metrics" (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    scrip_code VARCHAR(32) NOT NULL,
    period VARCHAR(64) NOT NULL,
    category VARCHAR(16) NOT NULL,
    currency VARCHAR(16),
    level_of_rounding VARCHAR(64),
    sales REAL,
    exceptional_items REAL,
    other_income_normal REAL,
    interest REAL,
    depreciation REAL,
    profit_before_tax REAL,
    profit_after_tax REAL,
    tax REAL,
    eps_in_rs REAL,
    net_profit REAL,
    other_income REAL,
    expenses REAL,
    operating_profit REAL,
    ebitda REAL,
    revenue_growth_percent REAL,
    ebitda_margin_percent REAL,
    ebit REAL,
    opm_percent REAL,
    tax_percent REAL,
    net_profit_margin REAL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_QUARTERLY_COPY = [
    "id", "scrip_code", "period", "category", "currency", "level_of_rounding",
    "sales", "exceptional_items", "other_income_normal", "interest", "depreciation",
    "profit_before_tax", "profit_after_tax", "tax", "eps_in_rs", "net_profit",
    "other_income", "expenses", "operating_profit", "ebitda",
    "revenue_growth_percent", "ebitda_margin_percent", "ebit", "opm_percent",
    "tax_percent", "net_profit_margin", "created_at",
]

_ANNUAL_CREATE = """
CREATE TABLE "Annual_Metrics" (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    scrip_code VARCHAR(32) NOT NULL,
    period VARCHAR(64) NOT NULL,
    category VARCHAR(16) NOT NULL,
    currency VARCHAR(16),
    level_of_rounding VARCHAR(64),
    sales REAL,
    exceptional_items REAL,
    other_income_normal REAL,
    interest REAL,
    depreciation REAL,
    profit_before_tax REAL,
    profit_after_tax REAL,
    tax REAL,
    eps_in_rs REAL,
    net_profit REAL,
    other_income REAL,
    expenses REAL,
    operating_profit REAL,
    ebitda REAL,
    revenue_growth_percent REAL,
    ebitda_margin_percent REAL,
    ebit REAL,
    opm_percent REAL,
    tax_percent REAL,
    net_profit_margin REAL,
    dividend_paid REAL,
    dividend_payout_percent REAL,
    equity_capital REAL,
    reserves REAL,
    total_liabilities REAL,
    current_ratio REAL,
    quick_ratio REAL,
    total_equity REAL,
    total_assets REAL,
    debt_to_equity REAL,
    working_capital REAL,
    cwip REAL,
    investments REAL,
    borrowings REAL,
    debt_to_assets REAL,
    cash_from_operating_activity REAL,
    cash_from_investing_activity REAL,
    dividends_received REAL,
    cash_from_financing_activity REAL,
    cash_conversion_ratio REAL,
    net_cash_flow REAL,
    cfo_op REAL,
    roa REAL,
    roe REAL,
    roce_percent REAL,
    debtor_days REAL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_ANNUAL_COPY = [
    "id", "scrip_code", "period", "category", "currency", "level_of_rounding",
    "sales", "exceptional_items", "other_income_normal", "interest", "depreciation",
    "profit_before_tax", "profit_after_tax", "tax", "eps_in_rs", "net_profit",
    "other_income", "expenses", "operating_profit", "ebitda",
    "revenue_growth_percent", "ebitda_margin_percent", "ebit", "opm_percent",
    "tax_percent", "net_profit_margin", "dividend_paid", "dividend_payout_percent",
    "equity_capital", "reserves", "total_liabilities", "current_ratio", "quick_ratio",
    "total_equity", "total_assets", "debt_to_equity", "working_capital", "cwip",
    "investments", "borrowings", "debt_to_assets",
    "cash_from_operating_activity", "cash_from_investing_activity",
    "dividends_received", "cash_from_financing_activity", "cash_conversion_ratio",
    "net_cash_flow", "cfo_op", "roa", "roe", "roce_percent", "debtor_days",
    "created_at",
]


async def _migrate_drop_metrics_json_columns() -> None:
    await _rebuild_table_without_json("Quarterly_Metrics", _QUARTERLY_CREATE, _QUARTERLY_COPY)
    await _rebuild_table_without_json("Annual_Metrics", _ANNUAL_CREATE, _ANNUAL_COPY)
    # Recreate unique indexes Tortoise expects
    connection = connections.get("default")
    await connection.execute_query(
        'CREATE UNIQUE INDEX IF NOT EXISTS uid_Quarterly_Metrics_scrip_period_cat '
        'ON "Quarterly_Metrics" (scrip_code, period, category)'
    )
    await connection.execute_query(
        'CREATE UNIQUE INDEX IF NOT EXISTS uid_Annual_Metrics_scrip_period_cat '
        'ON "Annual_Metrics" (scrip_code, period, category)'
    )
    await connection.execute_query(
        'CREATE INDEX IF NOT EXISTS idx_Quarterly_Metrics_scrip_code ON "Quarterly_Metrics" (scrip_code)'
    )
    await connection.execute_query(
        'CREATE INDEX IF NOT EXISTS idx_Annual_Metrics_scrip_code ON "Annual_Metrics" (scrip_code)'
    )


async def init_db(*, wipe: bool | None = None) -> None:
    ensure_data_dirs()
    do_wipe = WIPE_DB_ON_STARTUP if wipe is None else wipe
    if do_wipe:
        wiped = wipe_database_file()
        logger.info("DB wipe on startup: wiped=%s", wiped)
        print(f"[db] Wipe on startup: wiped={wiped}")
    await Tortoise.init(config=get_tortoise_config())
    await Tortoise.generate_schemas(safe=True)
    await _migrate_company_membership_schema()
    await _migrate_metrics_ind_as_column()
    await _migrate_drop_metrics_json_columns()
    await seed_defaults()
    print("[db] Tortoise ORM initialized and schemas ready.")


async def close_db() -> None:
    await Tortoise.close_connections()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield
    await close_db()
