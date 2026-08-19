"""Admin operations for missing companies CSV and BSE metadata."""
from typing import Any, Dict, List, Optional

from repositories.missing_companies_csv_repository import MissingCompaniesCsvRepository
from repositories.sqlite_repository import SqliteRepository


class MissingCompaniesAdminService:
    def __init__(self):
        self.csv_repo = MissingCompaniesCsvRepository()
        self.db = SqliteRepository()

    def get_missing_companies(self) -> List[Dict[str, Any]]:
        return self.csv_repo.read_missing_companies()

    def get_missing_companies_status(self) -> List[Dict[str, Any]]:
        missing_companies = self.get_missing_companies()
        companies_with_status = []
        for company in missing_companies:
            scrip_code = company.get("scrip_code", "")
            filing_count = self.db.get_xbrl_filings_count(scrip_code)
            companies_with_status.append({
                **company,
                "has_filings": filing_count > 0,
                "filing_count": filing_count,
                "needs_fetching": filing_count == 0,
            })
        return companies_with_status

    def add_companies_to_bse_metadata(self, scrip_codes: List[str]) -> Dict[str, Any]:
        missing_companies = self.get_missing_companies()
        scrip_codes_set = {s.strip().lower() for s in scrip_codes}
        companies_to_add = [
            c for c in missing_companies
            if c["scrip_code"].strip().lower() in scrip_codes_set
        ]

        if not companies_to_add:
            return {
                "success": False,
                "message": "No matching companies found in missing list",
                "added_count": 0,
                "errors": [],
            }

        existing = self.csv_repo.read_metadata_companies()
        added_count = 0
        errors = []

        for company in companies_to_add:
            scrip_code = company["scrip_code"].strip()
            if scrip_code.lower() in existing:
                errors.append(f"{company['company_name']} already exists in BSE metadata")
                continue

            existing[scrip_code.lower()] = {
                "Company": company["company_name"],
                "Symbol": company["symbol"],
                "Scrip-code": scrip_code,
                "Sector ": "",
                "Industry": "",
            }

            if not self.db.company_exists(scrip_code):
                self.db.upsert_company(
                    company_name=company["company_name"],
                    symbol=company["symbol"],
                    scrip_code=scrip_code,
                    sector="",
                    industry="",
                )
                added_count += 1
                self.csv_repo.remove_missing_company(scrip_code)
            else:
                errors.append(f"{company['company_name']} already exists in database")

        if added_count > 0:
            self.csv_repo.write_metadata_companies(existing)

        return {
            "success": added_count > 0,
            "message": f"Added {added_count} companies to BSE Filings and database",
            "added_count": added_count,
            "errors": errors,
        }
