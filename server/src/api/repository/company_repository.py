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
            WHERE id = ? OR LOWER(symbol) = LOWER(?) OR LOWER(scrip_code) = LOWER(?)
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
        """Get financial data for a company from annual_table (fallback quarterly_table)."""
        if not company_id:
            return []

        conn = self.db._conn
        cursor = conn.cursor()

        rows = []
        try:
            cursor.execute('''
                SELECT period, sales, net_profit, eps_in_rs
                FROM annual_table
                WHERE LOWER(company_symbol) = LOWER(?) OR LOWER(scrip_code) = LOWER(?)
                ORDER BY datetime(created_at) DESC, id DESC
            ''', (company_id, company_id))
            rows = cursor.fetchall()
        except Exception as e:
            print(f"[CompanyRepository] get_company_financials annual lookup failed for {company_id}: {e}")

        if not rows:
            # Fallback to latest quarterly data when annual data is missing.
            try:
                cursor.execute('''
                    SELECT period, sales, net_profit, eps_in_rs
                    FROM quarterly_table
                    WHERE LOWER(company_symbol) = LOWER(?) OR LOWER(scrip_code) = LOWER(?)
                    ORDER BY datetime(created_at) DESC, id DESC
                ''', (company_id, company_id))
                rows = cursor.fetchall()
            except Exception as e:
                print(f"[CompanyRepository] get_company_financials quarterly lookup failed for {company_id}: {e}")
                rows = []

        financials = []

        for row in rows:
            try:
                raw_year = row[0] if row and row[0] is not None else "N/A"
                if isinstance(raw_year, str) and raw_year.strip() == "":
                    raw_year = "N/A"

                yearly_fin = YearlyFinancials(
                    year=str(raw_year),
                    sales=float(row[1]) if row[1] is not None else 0.0,
                    ebitda=0.0,
                    opm=0.0,
                    pat=float(row[2]) if row[2] is not None else 0.0,
                    eps=float(row[3]) if row[3] is not None else 0.0,
                    roce=0.0,
                    de=0.0,
                    cfo=0.0,
                )
                financials.append(yearly_fin)
            except (ValueError, TypeError, IndexError) as e:
                print(f"[CompanyRepository] skipping bad financials row for {company_id}: {e}")
                continue

        if years and len(financials) > years:
            financials = financials[:years]

        # Return evenly truncated or full financials list.
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
    
    def get_latest_quarterly_data(self, symbol: str) -> Optional[dict]:
        """Get latest quarterly data for a company by symbol"""
        return self.db.get_latest_quarterly_data(symbol)
    
    def get_latest_annual_data(self, symbol: str) -> Optional[dict]:
        """Get latest annual data for a company by symbol"""
        return self.db.get_latest_annual_data(symbol)

