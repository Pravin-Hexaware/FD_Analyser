"""Company validation against BSE Validation.csv."""
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import VALIDATION_CSV

_validation_companies_cache: Optional[List[Dict[str, str]]] = None


def validation_csv_path() -> Path:
    return VALIDATION_CSV


def normalize_text(text: Optional[str]) -> str:
    if text is None:
        return ""
    normalized = text.strip().lower()
    normalized = re.sub(r"\.|,|\(|\)|&", "", normalized)
    normalized = re.sub(r"\b(ltd|ltd\b|limited)\b", "limited", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def load_validation_companies() -> List[Dict[str, str]]:
    global _validation_companies_cache
    if _validation_companies_cache is not None:
        return _validation_companies_cache

    validation_path = validation_csv_path()
    rows: List[Dict[str, str]] = []
    if not validation_path.exists():
        print(f"Validation CSV not found: {validation_path}")
        _validation_companies_cache = rows
        return rows

    with open(validation_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({
                "security_code": row.get("Security Code", "").strip(),
                "issuer_name": row.get("Issuer Name", "").strip(),
                "security_id": row.get("Security Id", "").strip(),
                "security_name": row.get("Security Name", "").strip(),
            })

    _validation_companies_cache = rows
    return rows


def resolve_company_validation(company_name: str, symbol: Optional[str] = None) -> Dict[str, Any]:
    normalized_query_name = normalize_text(company_name)
    validation_rows = load_validation_companies()
    if not validation_rows:
        return {
            "valid": False,
            "company_name": company_name,
            "reason": "Validation data unavailable.",
        }

    normalized_symbol = normalize_text(symbol) if symbol else ""
    matched_row = None
    symbol_matched = False
    name_matches: List[Dict[str, str]] = []

    if normalized_symbol:
        symbol_candidates = [
            row for row in validation_rows
            if normalized_symbol == normalize_text(row["security_id"])
            or normalized_symbol == normalize_text(row["security_code"])
        ]
        if symbol_candidates:
            matched_row = symbol_candidates[0]
            symbol_matched = True

    if matched_row is None:
        if not normalized_query_name:
            return {
                "valid": False,
                "company_name": company_name,
                "reason": "Company name not provided and symbol did not match Validation.csv.",
            }

        name_matches = [
            row for row in validation_rows
            if normalized_query_name in normalize_text(row["issuer_name"])
            or normalize_text(row["issuer_name"]).find(normalized_query_name) >= 0
            or normalized_query_name in normalize_text(row["security_name"])
        ]

        if not name_matches:
            return {
                "valid": False,
                "company_name": company_name,
                "reason": "Company name not found in Validation.csv.",
            }

        matched_row = sorted(
            name_matches,
            key=lambda row: len(normalize_text(row["issuer_name"])),
            reverse=True,
        )[0]
        symbol_matched = False if symbol else True

    return {
        "valid": True,
        "company_name": company_name,
        "resolved_issuer_name": matched_row["issuer_name"],
        "resolved_scrip_code": matched_row["security_code"],
        "resolved_security_id": matched_row["security_id"],
        "parsed_symbol": symbol,
        "symbol_matched": symbol_matched,
        "name_matches": [row["issuer_name"] for row in name_matches],
    }
