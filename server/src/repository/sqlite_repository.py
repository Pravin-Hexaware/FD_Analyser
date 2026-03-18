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

    def xbrl_filing_exists(self, scrip_code: str, xbrl_link: str) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT 1 FROM xbrl_filing_table WHERE scrip_code = ? AND xbrl_link = ? LIMIT 1",
            (scrip_code, xbrl_link),
        )
        return cur.fetchone() is not None

    def insert_xbrl_filing(
        self,
        scrip_code: str,
        symbol: Optional[str],
        xbrl_link: str,
        publication_date: Optional[str] = None,
    ) -> int:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO xbrl_filing_table (scrip_code, symbol, xbrl_link, publication_date)
            VALUES (?, ?, ?, ?)
            """,
            (scrip_code, symbol, xbrl_link, publication_date),
        )
        self._conn.commit()
        return cur.lastrowid

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
