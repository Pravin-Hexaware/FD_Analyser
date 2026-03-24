import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


class SqliteRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(Path(__file__).resolve().parents[1] / "data" / "financial_data.db")
        self._ensure_db_dir()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _ensure_db_dir(self) -> None:
        p = Path(self.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)

    def _init_tables(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS company_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT,
                symbol TEXT,
                scrip_code TEXT UNIQUE,
                sector TEXT,
                industry TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS xbrl_filing_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scrip_code TEXT,
                symbol TEXT,
                xbrl_link TEXT,
                publication_date TEXT,
                report_type TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS xbrl_extraction_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scrip_code TEXT,
                xbrl_link TEXT,
                company_name TEXT,
                company_symbol TEXT,
                currency TEXT,
                level_of_rounding TEXT,
                reporting_type TEXT,
                nature_of_report TEXT,
                sales REAL,
                expenses REAL,
                operating_profit REAL,
                opm_percentage REAL,
                other_income REAL,
                interest REAL,
                depreciation REAL,
                profit_before_tax REAL,
                tax REAL,
                tax_percent REAL,
                net_profit REAL,
                eps_in_rs REAL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS symbol_extraction_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id INTEGER,
                query TEXT,
                symbol TEXT,
                name TEXT,
                peers TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        self._conn.commit()

    def upsert_company(
        self,
        company_name: Optional[str],
        symbol: Optional[str],
        scrip_code: str,
        sector: Optional[str],
        industry: Optional[str],
    ) -> int:
        """Insert or update a company record. Returns company id."""
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO company_table (company_name, symbol, scrip_code, sector, industry)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(scrip_code) DO UPDATE SET
              company_name=excluded.company_name,
              symbol=excluded.symbol,
              sector=excluded.sector,
              industry=excluded.industry
            ;
            """,
            (company_name, symbol, scrip_code, sector, industry),
        )
        self._conn.commit()
        return cur.lastrowid

    def company_exists(self, scrip_code: str) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT 1 FROM company_table WHERE scrip_code = ? LIMIT 1",
            (scrip_code,),
        )
        return cur.fetchone() is not None

    def xbrl_filing_exists(self, scrip_code: str, xbrl_link: str, report_type: Optional[str] = None) -> bool:
        cur = self._conn.cursor()
        if report_type is None:
            cur.execute(
                "SELECT 1 FROM xbrl_filing_table WHERE scrip_code = ? AND xbrl_link = ? LIMIT 1",
                (scrip_code, xbrl_link),
            )
        else:
            cur.execute(
                "SELECT 1 FROM xbrl_filing_table WHERE scrip_code = ? AND xbrl_link = ? AND report_type = ? LIMIT 1",
                (scrip_code, xbrl_link, report_type),
            )
        return cur.fetchone() is not None

    def get_xbrl_filing_id(self, scrip_code: str, xbrl_link: str, report_type: Optional[str] = None) -> Optional[int]:
        cur = self._conn.cursor()
        if report_type is None:
            cur.execute(
                "SELECT id FROM xbrl_filing_table WHERE scrip_code = ? AND xbrl_link = ? LIMIT 1",
                (scrip_code, xbrl_link),
            )
        else:
            cur.execute(
                "SELECT id FROM xbrl_filing_table WHERE scrip_code = ? AND xbrl_link = ? AND report_type = ? LIMIT 1",
                (scrip_code, xbrl_link, report_type),
            )
        row = cur.fetchone()
        return row[0] if row else None

    def get_xbrl_filings(self, scrip_code: str | None = None) -> list[dict]:
        cur = self._conn.cursor()
        if scrip_code:
            cur.execute(
                "SELECT scrip_code, symbol, xbrl_link FROM xbrl_filing_table WHERE scrip_code = ?",
                (scrip_code,),
            )
        else:
            cur.execute(
                "SELECT scrip_code, symbol, xbrl_link FROM xbrl_filing_table"
            )
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def xbrl_extraction_exists(self, scrip_code: str, xbrl_link: str) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT 1 FROM xbrl_extraction_table WHERE scrip_code = ? AND xbrl_link = ? LIMIT 1",
            (scrip_code, xbrl_link),
        )
        return cur.fetchone() is not None

    def insert_xbrl_extraction(
        self,
        scrip_code: str,
        xbrl_link: str,
        company_name: Optional[str] = None,
        company_symbol: Optional[str] = None,
        currency: Optional[str] = None,
        level_of_rounding: Optional[str] = None,
        reporting_type: Optional[str] = None,
        nature_of_report: Optional[str] = None,
        sales: Optional[float] = None,
        expenses: Optional[float] = None,
        operating_profit: Optional[float] = None,
        opm_percentage: Optional[float] = None,
        other_income: Optional[float] = None,
        interest: Optional[float] = None,
        depreciation: Optional[float] = None,
        profit_before_tax: Optional[float] = None,
        tax: Optional[float] = None,
        tax_percent: Optional[float] = None,
        net_profit: Optional[float] = None,
        eps_in_rs: Optional[float] = None,
    ) -> int:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO xbrl_extraction_table (
                scrip_code,
                xbrl_link,
                company_name,
                company_symbol,
                currency,
                level_of_rounding,
                reporting_type,
                nature_of_report,
                sales,
                expenses,
                operating_profit,
                opm_percentage,
                other_income,
                interest,
                depreciation,
                profit_before_tax,
                tax,
                tax_percent,
                net_profit,
                eps_in_rs
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scrip_code,
                xbrl_link,
                company_name,
                company_symbol,
                currency,
                level_of_rounding,
                reporting_type,
                nature_of_report,
                sales,
                expenses,
                operating_profit,
                opm_percentage,
                other_income,
                interest,
                depreciation,
                profit_before_tax,
                tax,
                tax_percent,
                net_profit,
                eps_in_rs,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def insert_xbrl_filing(
        self,
        scrip_code: str,
        symbol: Optional[str],
        xbrl_link: str,
        publication_date: Optional[str] = None,
        report_type: Optional[str] = None,
    ) -> int:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO xbrl_filing_table (scrip_code, symbol, xbrl_link, publication_date, report_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scrip_code, symbol, xbrl_link, publication_date, report_type),
        )
        self._conn.commit()
        return cur.lastrowid

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def get_next_query_id(self) -> int:
        """Get the next available query_id based on the maximum existing id.
        
        Returns:
            The next query_id to use
        """
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT MAX(query_id) as max_id FROM symbol_extraction_results
            """
        )
        result = cur.fetchone()
        max_id = result[0] if result and result[0] else 0
        return max_id + 1

    def save_symbol_extraction_result(
        self,
        query_id: int,
        query: str,
        symbol: str,
        name: str,
        peers: str,
    ) -> int:
        """Save symbol extraction result to database.
        
        Args:
            query_id: The query ID (group identifier)
            query: The user query
            symbol: Stock symbol
            name: Company name
            peers: JSON string of peer companies
            
        Returns:
            The inserted row ID
        """
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO symbol_extraction_results (query_id, query, symbol, name, peers)
            VALUES (?, ?, ?, ?, ?)
            """,
            (query_id, query, symbol, name, peers),
        )
        self._conn.commit()
        return cur.lastrowid

