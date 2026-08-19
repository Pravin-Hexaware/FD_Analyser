from typing import Any, Dict, List, Optional

from models.company import Company, YearlyFinancials
from repositories.sqlite_repository import SqliteRepository


class CompanyRepository:
    """Repository for accessing company data from the existing database"""

    def __init__(self):
        self.db = SqliteRepository()

    def search_companies(self, query: str) -> List[Company]:
        if not query or len(query) < 1:
            return []

        query_lower = query.lower()
        conn = self.db._conn
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT id, company_name, symbol, scrip_code, sector, industry
            FROM company_table
            WHERE LOWER(company_name) LIKE ?
               OR LOWER(symbol) LIKE ?
               OR LOWER(scrip_code) LIKE ?
            ORDER BY symbol
            ''',
            (f"%{query_lower}%", f"%{query_lower}%", f"%{query_lower}%"),
        )

        return [self._row_to_company(row) for row in cursor.fetchall()]

    def get_all_companies(self) -> List[Company]:
        conn = self.db._conn
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, company_name, symbol, scrip_code, sector, industry
            FROM company_table
            ORDER BY company_name
            '''
        )
        return [self._row_to_company(row) for row in cursor.fetchall()]

    def get_company_by_id(self, company_id: str) -> Optional[Company]:
        conn = self.db._conn
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, company_name, symbol, scrip_code, sector, industry
            FROM company_table
            WHERE id = ? OR LOWER(symbol) = LOWER(?) OR LOWER(scrip_code) = LOWER(?)
            ''',
            (company_id, company_id, company_id),
        )
        row = cursor.fetchone()
        return self._row_to_company(row) if row else None

    def get_company_financials(self, company_id: str, years: Optional[int] = None) -> List[YearlyFinancials]:
        if not company_id:
            return []

        conn = self.db._conn
        cursor = conn.cursor()
        rows = []
        try:
            cursor.execute(
                '''
                SELECT period, sales, net_profit, eps_in_rs
                FROM annual_table
                WHERE LOWER(company_symbol) = LOWER(?) OR LOWER(scrip_code) = LOWER(?)
                ORDER BY datetime(created_at) DESC, id DESC
                ''',
                (company_id, company_id),
            )
            rows = cursor.fetchall()
        except Exception as e:
            print(f"[CompanyRepository] get_company_financials annual lookup failed for {company_id}: {e}")

        if not rows:
            try:
                cursor.execute(
                    '''
                    SELECT period, sales, net_profit, eps_in_rs
                    FROM quarterly_table
                    WHERE LOWER(company_symbol) = LOWER(?) OR LOWER(scrip_code) = LOWER(?)
                    ORDER BY datetime(created_at) DESC, id DESC
                    ''',
                    (company_id, company_id),
                )
                rows = cursor.fetchall()
            except Exception as e:
                print(f"[CompanyRepository] get_company_financials quarterly lookup failed for {company_id}: {e}")

        financials = []
        for row in rows:
            try:
                raw_year = row[0] if row and row[0] is not None else "N/A"
                if isinstance(raw_year, str) and raw_year.strip() == "":
                    raw_year = "N/A"
                financials.append(
                    YearlyFinancials(
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
                )
            except (ValueError, TypeError, IndexError) as e:
                print(f"[CompanyRepository] skipping bad financials row for {company_id}: {e}")

        if years and len(financials) > years:
            financials = financials[:years]
        return financials

    def get_trending_companies(self, limit: int = 4) -> List[Company]:
        conn = self.db._conn
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT DISTINCT c.id, c.company_name, c.symbol, c.scrip_code, c.sector, c.industry
            FROM company_table c
            LEFT JOIN annual_table a ON c.symbol = a.company_symbol
            ORDER BY a.sales DESC, c.company_name
            LIMIT ?
            ''',
            (limit,),
        )
        return [self._row_to_company(row) for row in cursor.fetchall()]

    def get_latest_quarterly_data(self, symbol: str) -> Optional[dict]:
        return self.db.get_latest_quarterly_data(symbol)

    def get_latest_annual_data(self, symbol: str) -> Optional[dict]:
        return self.db.get_latest_annual_data(symbol)

    def get_companies_with_latest_financials(
        self, scrip_codes: List[str], frequency: str = "annual"
    ) -> List[Dict[str, Any]]:
        """Compare multiple companies with their latest financials."""
        companies_data = []
        is_quarterly = frequency.lower() == "quarterly"

        for scrip_code in scrip_codes:
            cur = self.db._conn.cursor()
            cur.execute(
                """
                SELECT company_name, symbol, sector, industry
                FROM company_table
                WHERE scrip_code = ?
                """,
                (scrip_code,),
            )
            company_info = cur.fetchone()
            if not company_info:
                continue

            if is_quarterly:
                cur.execute(
                    """
                    SELECT sales, expenses, operating_profit, opm_percentage,
                           net_profit, eps_in_rs, created_at
                    FROM quarterly_table
                    WHERE scrip_code = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (scrip_code,),
                )
            else:
                cur.execute(
                    """
                    SELECT sales, expenses, operating_profit, opm_percentage,
                           net_profit, eps_in_rs, equity_capital, total_assets,
                           borrowings, cash_from_operating_activity, created_at
                    FROM annual_table
                    WHERE scrip_code = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (scrip_code,),
                )

            fin_data = cur.fetchone()
            if not fin_data:
                continue

            if is_quarterly:
                companies_data.append({
                    "scrip_code": scrip_code,
                    "company_name": company_info[0],
                    "symbol": company_info[1],
                    "sector": company_info[2],
                    "industry": company_info[3],
                    "sales": fin_data[0],
                    "expenses": fin_data[1],
                    "operating_profit": fin_data[2],
                    "opm": fin_data[3],
                    "pat": fin_data[4],
                    "eps": fin_data[5],
                    "equity": None,
                    "total_assets": None,
                    "borrowings": None,
                    "cfo": None,
                    "date": fin_data[6],
                })
            else:
                companies_data.append({
                    "scrip_code": scrip_code,
                    "company_name": company_info[0],
                    "symbol": company_info[1],
                    "sector": company_info[2],
                    "industry": company_info[3],
                    "sales": fin_data[0],
                    "expenses": fin_data[1],
                    "operating_profit": fin_data[2],
                    "opm": fin_data[3],
                    "pat": fin_data[4],
                    "eps": fin_data[5],
                    "equity": fin_data[6],
                    "total_assets": fin_data[7],
                    "borrowings": fin_data[8],
                    "cfo": fin_data[9],
                    "date": fin_data[10],
                })

        return companies_data

    @staticmethod
    def _row_to_company(row) -> Company:
        return Company(
            id=str(row[0]) if row[0] else "",
            name=row[1] if row[1] and row[1].strip() else row[2],
            symbol=row[2] or "",
            bse_code=row[3] or "",
            sector=row[4] or "Unknown Sector",
            industry=row[5] or "Unknown Industry",
            xbrl_link="",
            financials=[],
        )
