"""Startup scheduler: refresh Nifty 500 list and enqueue missing FY XBRL coverage."""
from __future__ import annotations

import csv
import io
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

from config.settings import (
    NIFTY500_CSV,
    NIFTY500_CSV_URL,
    NIFTY500_REFRESH_DAYS,
    VALIDATION_CSV,
)
from repositories.sqlite_repository import SqliteRepository
from services.llm_missing_company_tracker import (
    append_missing_company,
    missing_tracker_csv_path,
    schedule_missing_company_processing,
)

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}


def current_fiscal_year_pair(now: Optional[datetime] = None) -> str:
    """
    Return current FY label year pair, matching xbrl_ws._calculate_5year_fiscal_range.
    month >= 3 → {year}-{year+1}; else → {year-1}-{year}.
    """
    current = now or datetime.utcnow()
    if current.month >= 3:
        start = current.year
        end = current.year + 1
    else:
        start = current.year - 1
        end = current.year
    return f"{start}-{end}"


def _load_isin_to_scrip_map(validation_path: Path) -> dict[str, str]:
    """Map ISIN No → Security Code; prefer Active Equity when duplicates exist."""
    mapping: dict[str, str] = {}
    preferred: dict[str, str] = {}
    if not validation_path.exists():
        print(f"[nifty500] Validation.csv not found: {validation_path}")
        return mapping

    with open(validation_path, mode="r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            isin = (row.get("ISIN No") or "").strip().upper()
            scrip = (row.get("Security Code") or "").strip()
            if not isin or not scrip:
                continue
            status = (row.get("Status") or "").strip().lower()
            instrument = (row.get("Instrument") or "").strip().lower()
            if isin not in mapping:
                mapping[isin] = scrip
            if status == "active" and instrument == "equity":
                preferred[isin] = scrip

    mapping.update(preferred)
    return mapping


def _parse_nifty_csv_text(text: str, isin_to_scrip: dict[str, str]) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    unmatched = 0
    for raw in reader:
        isin = (raw.get("ISIN Code") or "").strip().upper()
        if not isin:
            continue
        scrip = isin_to_scrip.get(isin, "")
        if not scrip:
            unmatched += 1
        rows.append(
            {
                "scrip_code": scrip,
                "company_name": (raw.get("Company Name") or "").strip(),
                "industry": (raw.get("Industry") or "").strip(),
                "symbol": (raw.get("Symbol") or "").strip(),
                "series": (raw.get("Series") or "").strip(),
                "isin_code": isin,
            }
        )
    if unmatched:
        print(f"[nifty500] {unmatched} ISIN(s) had no Validation.csv Security Code match")
    return rows


def _download_nifty_csv(url: str, timeout: int = 60) -> Optional[str]:
    try:
        req = Request(url, headers=_NSE_HEADERS)
        with urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed NSE URL
            raw = resp.read()
        text = raw.decode("utf-8-sig", errors="replace")
        if "Company Name" not in text or "ISIN Code" not in text:
            print("[nifty500] Downloaded content does not look like Nifty 500 CSV")
            return None
        return text
    except Exception as exc:
        print(f"[nifty500] NSE download failed: {exc}")
        return None


def _read_local_nifty_csv(path: Path) -> Optional[str]:
    if not path.exists():
        print(f"[nifty500] Local fallback CSV missing: {path}")
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        print(f"[nifty500] Failed to read local CSV: {exc}")
        return None


def _existing_missing_scrip_codes() -> set[str]:
    path = missing_tracker_csv_path()
    if not path.exists():
        return set()
    codes: set[str] = set()
    try:
        with open(path, mode="r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                code = (row.get("scrip_code") or "").strip()
                if code:
                    codes.add(code)
    except Exception as exc:
        print(f"[nifty500] Could not read missing_companies.csv for dedupe: {exc}")
    return codes


class Nifty500SchedulerService:
    """Refresh nifty_500_list when stale and enqueue companies missing current-FY XBRL."""

    @staticmethod
    def needs_refresh(repo: SqliteRepository, now: Optional[datetime] = None) -> bool:
        current = now or datetime.utcnow()
        last = repo.get_nifty500_last_updated()
        if last is None:
            return True
        return (current - last) > timedelta(days=NIFTY500_REFRESH_DAYS)

    @staticmethod
    def refresh_nifty500_list(repo: SqliteRepository) -> int:
        isin_to_scrip = _load_isin_to_scrip_map(VALIDATION_CSV)
        text = _download_nifty_csv(NIFTY500_CSV_URL)
        if text:
            try:
                NIFTY500_CSV.parent.mkdir(parents=True, exist_ok=True)
                NIFTY500_CSV.write_text(text, encoding="utf-8")
                print(f"[nifty500] Cached NSE CSV to {NIFTY500_CSV}")
            except Exception as exc:
                print(f"[nifty500] Could not write local CSV cache: {exc}")
        else:
            print("[nifty500] Falling back to local ind_nifty500list.csv")
            text = _read_local_nifty_csv(NIFTY500_CSV)
            if not text:
                return 0

        rows = _parse_nifty_csv_text(text, isin_to_scrip)
        if not rows:
            print("[nifty500] No rows parsed from Nifty CSV")
            return 0

        updated_at = datetime.utcnow().isoformat()
        count = repo.replace_nifty500_rows(rows, updated_at)
        print(f"[nifty500] Replaced nifty_500_list with {count} rows at {updated_at}")
        return count

    @staticmethod
    def enqueue_missing_fiscal_coverage(repo: SqliteRepository) -> int:
        year_pair = current_fiscal_year_pair()
        companies = repo.get_all_nifty500()
        scrip_codes = [
            (c.get("scrip_code") or "").strip()
            for c in companies
            if (c.get("scrip_code") or "").strip()
        ]
        missing_codes = repo.get_scrip_codes_missing_fiscal_year(scrip_codes, year_pair)
        if not missing_codes:
            print(f"[nifty500] All Nifty companies have filings for {year_pair}")
            return 0

        already_queued = _existing_missing_scrip_codes()
        by_scrip = {
            (c.get("scrip_code") or "").strip(): c
            for c in companies
            if (c.get("scrip_code") or "").strip()
        }

        enqueued = 0
        for scrip in sorted(missing_codes):
            if scrip in already_queued:
                continue
            company = by_scrip.get(scrip) or {}
            append_missing_company(
                company_name=company.get("company_name") or scrip,
                symbol=company.get("symbol"),
                scrip_code=scrip,
                frequency="quarterly",
                period=year_pair,
                time_horizon=year_pair,
                is_peer=False,
                query="nifty500_scheduler",
                schedule_processing=False,
            )
            already_queued.add(scrip)
            enqueued += 1

        print(
            f"[nifty500] Enqueued {enqueued} companies missing FY {year_pair} "
            f"({len(missing_codes)} total without coverage)"
        )
        return enqueued

    @classmethod
    def run_on_startup(cls) -> None:
        print("[nifty500] Startup scheduler begin")
        repo = SqliteRepository()
        try:
            if cls.needs_refresh(repo):
                print(
                    f"[nifty500] List stale or empty (>{NIFTY500_REFRESH_DAYS} days); refreshing"
                )
                cls.refresh_nifty500_list(repo)
            else:
                last = repo.get_nifty500_last_updated()
                print(f"[nifty500] List fresh (last updated {last}); skipping download")

            enqueued = cls.enqueue_missing_fiscal_coverage(repo)
            if enqueued > 0:
                schedule_missing_company_processing()
                print("[nifty500] Scheduled missing-company XBRL batch")
            else:
                # Still process any pre-existing queue entries
                if _existing_missing_scrip_codes():
                    schedule_missing_company_processing()
                    print("[nifty500] Scheduled existing missing-company queue")
        except Exception as exc:
            print(f"[nifty500] Startup scheduler failed: {exc}")
        finally:
            try:
                repo.close()
            except Exception:
                pass
        print("[nifty500] Startup scheduler end")

    @classmethod
    def schedule_on_startup(cls) -> None:
        thread = threading.Thread(target=cls.run_on_startup, daemon=True, name="nifty500-scheduler")
        thread.start()
        print("[nifty500] Background scheduler thread started")
