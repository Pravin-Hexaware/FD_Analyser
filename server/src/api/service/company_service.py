from typing import List, Optional
from api.repository.company_repository import CompanyRepository
from api.models.company_model import Company


class CompanyService:
    """Service layer for company business logic"""
    
    def __init__(self):
        self.repository = CompanyRepository()
    
    def get_all_companies(self) -> List[Company]:
        """Get all companies from repository"""
        return self.repository.get_all_companies()
    
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
        """Get financial data for a company"""
        if not company_id:
            return []
        return self.repository.get_company_financials(company_id, years)

