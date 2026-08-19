from typing import List, Optional

from models.company import Company
from repositories.company_repository import CompanyRepository


class CompanyService:
    """Service layer for company business logic"""

    def __init__(self):
        self.repository = CompanyRepository()

    def get_all_companies(self) -> List[Company]:
        try:
            return self.repository.get_all_companies()
        except Exception as e:
            print(f"[CompanyService] get_all_companies error: {e}")
            return []

    def get_company_details(self, company_id: str) -> Optional[Company]:
        if not company_id:
            return None
        return self.repository.get_company_by_id(company_id)

    def search_companies(self, query: str) -> List[Company]:
        if not query or len(query.strip()) < 1:
            return []
        return self.repository.search_companies(query.strip())

    def get_trending_companies(self, limit: int = 4) -> List[Company]:
        return self.repository.get_trending_companies(limit)

    def get_company_financials(self, company_id: str, years: Optional[int] = 5):
        if not company_id:
            return []
        company = self.get_company_details(company_id)
        symbol = company.symbol if company and company.symbol else company_id
        return self.repository.get_company_financials(symbol, years)

    def _find_best_symbol_or_scrip(self, company_id: str) -> Optional[str]:
        if not company_id:
            return None
        company = self.get_company_details(company_id)
        if company:
            if company.bse_code:
                return company.bse_code
            if company.symbol:
                return company.symbol
            return company.id
        return company_id

    def get_latest_quarterly_data(self, company_id: str) -> Optional[dict]:
        lookup = self._find_best_symbol_or_scrip(company_id)
        if not lookup:
            return None
        quarterly = self.repository.get_latest_quarterly_data(lookup)
        if quarterly:
            return quarterly
        if company_id and not company_id.isdigit():
            return self.repository.get_latest_quarterly_data(company_id)
        return None

    def get_latest_annual_data(self, company_id: str) -> Optional[dict]:
        lookup = self._find_best_symbol_or_scrip(company_id)
        if not lookup:
            return None
        annual = self.repository.get_latest_annual_data(lookup)
        if annual:
            return annual
        if company_id and not company_id.isdigit():
            return self.repository.get_latest_annual_data(company_id)
        return None

    def compare_companies(self, scrip_codes: List[str], frequency: str = "annual") -> dict:
        companies_data = self.repository.get_companies_with_latest_financials(scrip_codes, frequency)
        return {
            "companies": companies_data,
            "frequency": frequency,
            "count": len(companies_data),
        }
