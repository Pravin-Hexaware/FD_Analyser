
"""FastAPI lifespan: wipe (optional), Tortoise init, schema generate, seed."""
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
    _, columns = await connection.execute_query("PRAGMA table_info(company_info)")
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
    await seed_defaults()
    print("[db] Tortoise ORM initialized and schemas ready.")


async def close_db() -> None:
    await Tortoise.close_connections()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield
    await close_db()
