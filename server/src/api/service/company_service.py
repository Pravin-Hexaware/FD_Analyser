from typing import List, Optional
from api.repository.company_repository import CompanyRepository
from api.models.company_model import Company


class CompanyService:
    """Service layer for company business logic"""
    
    def __init__(self):
        self.repository = CompanyRepository()
    
    def get_all_companies(self) -> List[Company]:
        """Get all companies from repository"""
        try:
            return self.repository.get_all_companies()
        except Exception as e:
            print(f"[CompanyService] get_all_companies error: {e}")
            return []
    
    def get_company_details(self, company_id: str) -> Optional[Company]:
        """Get detailed company information"""
        if not company_id:
            return None
        return self.repository.get_company_by_id(company_id)
    
    def search_companies(self, query: str) -> List[Company]:
        """
        Search for companies by name, symbol, or scrip_code
        Input validation and trimming
        """
        if not query or len(query.strip()) < 1:
            return []
        
        return self.repository.search_companies(query.strip())
    
    def get_trending_companies(self, limit: int = 4) -> List[Company]:
        """Get trending companies (top by sales)"""
        return self.repository.get_trending_companies(limit)
    
    def get_company_financials(self, company_id: str, years: Optional[int] = 5):
        """Get financial data for a company (needs company symbol resolved)."""
        if not company_id:
            return []

        company = self.get_company_details(company_id)
        if company and company.symbol:
            symbol = company.symbol
        else:
            symbol = company_id

        return self.repository.get_company_financials(symbol, years)
    
    def _find_best_symbol_or_scrip(self, company_id: str) -> Optional[str]:
        """Resolve company id/symbol/scrip_code into a value for quarterly/annual DB query."""
        if not company_id:
            return None

        company = self.get_company_details(company_id)
        if company:
            # Prefer scrip code (e.g., 500900) for quarterly/annual tables, fallback to symbol if missing
            if company.bse_code:
                return company.bse_code
            if company.symbol:
                return company.symbol
            return company.id

        # Fallback to raw input for direct requests like 500900
        return company_id

    def get_latest_quarterly_data(self, company_id: str) -> Optional[dict]:
        """Get the latest quarterly data for a company by id/symbol/scrip_code."""
        lookup = self._find_best_symbol_or_scrip(company_id)
        if not lookup:
            return None

        # try both scrip_code and symbol
        quarterly = self.repository.get_latest_quarterly_data(lookup)
        if quarterly:
            return quarterly

        # if not found and input appears numeric and company was symbol, check symbol as fallback
        if company_id and not company_id.isdigit():
            quarterly = self.repository.get_latest_quarterly_data(company_id)
            if quarterly:
                return quarterly

        return None

    def get_latest_annual_data(self, company_id: str) -> Optional[dict]:
        """Get the latest annual data for a company by id/symbol/scrip_code."""
        lookup = self._find_best_symbol_or_scrip(company_id)
        if not lookup:
            return None

        annual = self.repository.get_latest_annual_data(lookup)
        if annual:
            return annual

        if company_id and not company_id.isdigit():
            annual = self.repository.get_latest_annual_data(company_id)
            if annual:
                return annual

        return None

