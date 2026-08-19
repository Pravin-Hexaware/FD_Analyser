"""Track missing companies in CSV and schedule background processing."""
import asyncio
import csv
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import MISSING_COMPANIES_CSV


def missing_tracker_csv_path() -> Path:
    MISSING_COMPANIES_CSV.parent.mkdir(parents=True, exist_ok=True)
    return MISSING_COMPANIES_CSV


def schedule_missing_company_processing() -> None:
    try:
        from services.missing_company_service import MissingCompanyService

        def _run():
            try:
                asyncio.run(MissingCompanyService.process_missing_companies_batch(None))
            except Exception as exc:
                print(f"[WARN] Missing company background task failed: {exc}")

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
    except Exception as exc:
        print(f"[WARN] Failed to schedule missing company processing: {exc}")


def append_missing_company(
    company_name: str,
    symbol: Optional[str],
    scrip_code: Optional[str],
    frequency: str,
    period: str,
    time_horizon: str,
    is_peer: bool,
    query: str,
    background_tasks=None,
    schedule_processing: bool = False,
) -> None:
    file_path = missing_tracker_csv_path()
    header = [
        "timestamp", "company_name", "symbol", "scrip_code",
        "frequency", "period", "time_horizon", "is_peer", "query",
    ]
    row = {
        "timestamp": datetime.now().isoformat(),
        "company_name": company_name,
        "symbol": symbol or "",
        "scrip_code": scrip_code or "",
        "frequency": frequency,
        "period": period,
        "time_horizon": time_horizon,
        "is_peer": "true" if is_peer else "false",
        "query": query,
    }
    write_header = not file_path.exists()
    print(f"Tracking missing company to CSV: {file_path} -> {company_name} ({scrip_code})")
    with open(file_path, mode="a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    if background_tasks is not None and schedule_processing:
        background_tasks.add_task(schedule_missing_company_processing)
