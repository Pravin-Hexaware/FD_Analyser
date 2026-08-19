"""CSV file I/O for missing-companies tracker and BSE metadata."""
import csv
from pathlib import Path
from typing import Any, Dict, List

from config.settings import COMPANY_METADATA_CSV, DATA_DIR, MISSING_COMPANIES_CSV


class MissingCompaniesCsvRepository:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def missing_tracker_path() -> Path:
        return MISSING_COMPANIES_CSV

    @staticmethod
    def company_metadata_path() -> Path:
        return COMPANY_METADATA_CSV

    def read_missing_companies(self) -> List[Dict[str, Any]]:
        csv_path = self.missing_tracker_path()
        if not csv_path.exists():
            return []

        missing_companies = []
        with open(csv_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []
            for row in reader:
                if row.get("company_name") and row.get("company_name").strip():
                    missing_companies.append({
                        "timestamp": row.get("timestamp", ""),
                        "company_name": row.get("company_name", "").strip(),
                        "symbol": row.get("symbol", "").strip(),
                        "scrip_code": row.get("scrip_code", "").strip(),
                        "frequency": row.get("frequency", "quarterly"),
                        "period": row.get("period", "unspecified"),
                        "time_horizon": row.get("time_horizon", "unspecified"),
                        "is_peer": row.get("is_peer", "false").lower() == "true",
                        "query": row.get("query", ""),
                    })
        return missing_companies

    def remove_missing_company(self, scrip_code: str) -> bool:
        csv_path = self.missing_tracker_path()
        if not csv_path.exists():
            return False

        records = []
        with open(csv_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for row in reader:
                if row.get("scrip_code", "").strip() != scrip_code.strip():
                    records.append(row)

        if fieldnames:
            with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(records)
        return True

    def read_metadata_companies(self) -> Dict[str, Dict[str, str]]:
        metadata_path = self.company_metadata_path()
        existing = {}
        if not metadata_path.exists():
            return existing

        with open(metadata_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                for row in reader:
                    scrip = (row.get("Scrip-code") or "").strip()
                    if scrip:
                        existing[scrip.lower()] = row
        return existing

    def write_metadata_companies(self, companies: Dict[str, Dict[str, str]]) -> None:
        metadata_path = self.company_metadata_path()
        fieldnames = ["Company", "Symbol", "Scrip-code", "Sector ", "Industry"]
        with open(metadata_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for _, row in sorted(companies.items()):
                for field in fieldnames:
                    if field not in row:
                        row[field] = ""
                writer.writerow({k: row.get(k, "") for k in fieldnames})
