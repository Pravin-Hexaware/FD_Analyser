from typing import List, Optional
from ..models.company_model import Company, YearlyFinancials
from repository.sqlite_repository import SqliteRepository


class CompanyRepository:
    """Repository for accessing company data from the existing database"""
    
    def __init__(self):
        # Use existing SqliteRepository which manages the actual database
        self.db = SqliteRepository()
    
    def search_companies(self, query: str) -> List[Company]:
        """
        Search companies by name, symbol, or scrip_code
        Returns list of matching Company objects
        """
        if not query or len(query) < 1:
            return []
        
        query_lower = query.lower()
        conn = self.db._conn
        cursor = conn.cursor()
        
        # Search in company_table for name, symbol, or scrip_code matches
        cursor.execute('''
            SELECT id, company_name, symbol, scrip_code, sector, industry
            FROM company_table 
            WHERE LOWER(company_name) LIKE ? 
               OR LOWER(symbol) LIKE ? 
               OR LOWER(scrip_code) LIKE ?
            ORDER BY symbol
        ''', (f"%{query_lower}%", f"%{query_lower}%", f"%{query_lower}%"))
        
        rows = cursor.fetchall()
        companies = []
        
        for row in rows:
            company = Company(
                id=str(row[0]) if row[0] else "",
                name=row[1] or "",
                symbol=row[2] or "",
                bse_code=row[3] or "",
                sector=row[4] or "",
                industry=row[5] or "",
                xbrl_link="",
                financials=[]
            )
            companies.append(company)
        
        return companies
    
    def get_all_companies(self) -> List[Company]:
        """Get all companies from database with financials"""
        conn = self.db._conn
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, company_name, symbol, scrip_code, sector, industry
            FROM company_table
            ORDER BY company_name
        ''')
        
        rows = cursor.fetchall()
        companies = []
        
        for row in rows:
            company = Company(
                id=str(row[0]) if row[0] else "",
                name=row[1] or "",
                symbol=row[2] or "",
                bse_code=row[3] or "",
                sector=row[4] or "",
                industry=row[5] or "",
                xbrl_link="",
                financials=[]
            )
            # Load financials for each company
            company.financials = self.get_company_financials(company.symbol)
            companies.append(company)
        
        return companies
    
    def get_company_by_id(self, company_id: str) -> Optional[Company]:
        """Get a specific company by ID"""
        conn = self.db._conn
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, company_name, symbol, scrip_code, sector, industry
            FROM company_table
            WHERE id = ? OR symbol = ? OR scrip_code = ?
        ''', (company_id, company_id, company_id))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        company = Company(
            id=str(row[0]) if row[0] else "",
            name=row[1] or "",
            symbol=row[2] or "",
            bse_code=row[3] or "",
            sector=row[4] or "",
            industry=row[5] or "",
            xbrl_link="",
            financials=[]
        )
        
        return company
    
    def get_company_financials(self, company_id: str, years: Optional[int] = None) -> List[YearlyFinancials]:
        """Get financial data for a company from annual_table"""
        conn = self.db._conn
        cursor = conn.cursor()
        
        # Get financials from annual_table using company_symbol or scrip_code
        cursor.execute('''
            SELECT year, sales, net_profit, eps_in_rs
            FROM annual_table
            WHERE company_symbol = ? OR scrip_code = ?
            ORDER BY year DESC
        ''', (company_id, company_id))
        
        rows = cursor.fetchall()
        financials = []
        
        for row in rows:
            try:
                yearly_fin = YearlyFinancials(
                    year=row[0] or "2025",
                    sales=float(row[1]) if row[1] else 0.0,
                    ebitda=0.0,  # Not directly available
                    opm=0.0,     # Not directly available
                    pat=float(row[2]) if row[2] else 0.0,
                    eps=float(row[3]) if row[3] else 0.0,
                    roce=0.0,    # Not directly available
                    de=0.0,      # Not directly available
                    cfo=0.0      # Not directly available
                )
                financials.append(yearly_fin)
            except (ValueError, TypeError):
                continue
        
        if years and len(financials) > years:
            financials = financials[:years]
        
        return financials
    
    def get_trending_companies(self, limit: int = 4) -> List[Company]:
        """Get trending companies (sorted by latest sales)"""
        conn = self.db._conn
        cursor = conn.cursor()
        
        # Get companies with their latest sales figures
        cursor.execute('''
            SELECT DISTINCT c.id, c.company_name, c.symbol, c.scrip_code, c.sector, c.industry
            FROM company_table c
            LEFT JOIN annual_table a ON c.symbol = a.company_symbol
            ORDER BY a.sales DESC, c.company_name
            LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        companies = []
        
        for row in rows:
            company = Company(
                id=str(row[0]) if row[0] else "",
                name=row[1] or "",
                symbol=row[2] or "",
                bse_code=row[3] or "",
                sector=row[4] or "",
                industry=row[5] or "",
                xbrl_link="",
                financials=[]
            )
            companies.append(company)
        
        return companies

