"""FastAPI lifespan: wipe (optional), Tortoise init, schema generate, seed."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from tortoise import Tortoise

from config.settings import WIPE_DB_ON_STARTUP
from db.config import ensure_data_dirs, get_tortoise_config, wipe_database_file
from db.seed import seed_defaults

logger = logging.getLogger(__name__)


async def init_db(*, wipe: bool | None = None) -> None:
    ensure_data_dirs()
    do_wipe = WIPE_DB_ON_STARTUP if wipe is None else wipe
    if do_wipe:
        wiped = wipe_database_file()
        logger.info("DB wipe on startup: wiped=%s", wiped)
        print(f"[db] Wipe on startup: wiped={wiped}")
    await Tortoise.init(config=get_tortoise_config())
    await Tortoise.generate_schemas(safe=True)
    await seed_defaults()
    print("[db] Tortoise ORM initialized and schemas ready.")


async def close_db() -> None:
    await Tortoise.close_connections()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield
    await close_db()
