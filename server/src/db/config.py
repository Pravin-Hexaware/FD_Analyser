"""Tortoise ORM configuration and helpers."""
from __future__ import annotations

from pathlib import Path

from config.settings import DB_PATH, DATA_DIR, WIPE_DB_ON_STARTUP

MODELS_MODULES = ["db.models"]


def _sqlite_url(db_path: Path) -> str:
    # Tortoise expects forward slashes for SQLite file URLs
    return f"sqlite://{db_path.resolve().as_posix()}"


def get_tortoise_config(db_path: Path | None = None) -> dict:
    path = db_path or DB_PATH
    return {
        "connections": {"default": _sqlite_url(path)},
        "apps": {
            "models": {
                "models": MODELS_MODULES,
                "default_connection": "default",
            }
        },
        "use_tz": False,
        "timezone": "UTC",
    }


TORTOISE_ORM = get_tortoise_config()


def wipe_database_file(db_path: Path | None = None) -> bool:
    """Delete the SQLite DB file (and WAL/SHM sidecars) if present. Returns True if wiped."""
    path = Path(db_path or DB_PATH)
    wiped = False
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if candidate.exists():
            candidate.unlink()
            wiped = True
    path.parent.mkdir(parents=True, exist_ok=True)
    return wiped


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "XBRLS" / "std").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "XBRLS" / "con").mkdir(parents=True, exist_ok=True)
