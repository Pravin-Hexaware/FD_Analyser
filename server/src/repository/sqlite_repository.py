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

    def _ensure_column(self, table: str, column: str, col_type: str) -> None:
        cur = self._conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cur.fetchall()]
        if column not in columns:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            self._conn.commit()

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

        # New tables for quarterly and annual extractions
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quarterly_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scrip_code TEXT,
                xbrl_link TEXT,
                period TEXT,
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
                cost_of_materials_consumed REAL,
                employee_benefit_expense REAL,
                other_expenses REAL,
                interest REAL,
                depreciation REAL,
                profit_before_tax REAL,
                current_tax REAL,
                deferred_tax REAL,
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
            CREATE TABLE IF NOT EXISTS annual_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scrip_code TEXT,
                xbrl_link TEXT,
                period TEXT,
                company_name TEXT,
                company_symbol TEXT,
                currency TEXT,
                level_of_rounding TEXT,
                reporting_type TEXT,
                nature_of_report TEXT,

                -- Profit and Loss / annual P&L section
                sales REAL,
                expenses REAL,
                operating_profit REAL,
                opm_percentage REAL,
                other_income REAL,
                interest REAL,
                depreciation REAL,
                profit_before_tax REAL,
                tax_percent REAL,
                net_profit REAL,
                eps_in_rs REAL,

                -- Balance Sheet section
                equity_capital REAL,
                reserves REAL,
                trade_payables_current REAL,
                borrowings REAL,
                other_liabilities REAL,
                total_liabilities REAL,
                total_equity REAL,
                fixed_assets REAL,
                cwip REAL,
                investments REAL,
                total_assets REAL,

                -- Cashflow section
                cash_from_operating_activity REAL,
                cash_from_investing_activity REAL,
                cash_from_financing_activity REAL,

                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        
        # Create chat history table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                chat_id TEXT PRIMARY KEY,
                user_query TEXT NOT NULL,
                response TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        
        self._conn.commit()

        # If annual_table existed from earlier version, ensure new columns exist
        for col_name, col_type in [
            ("period", "TEXT"),
            ("trade_payables_current", "REAL"),
            ("total_equity", "REAL"),
        ]:
            self._ensure_column("annual_table", col_name, col_type)
        
        # Ensure period column in quarterly_table
        self._ensure_column("quarterly_table", "period", "TEXT")

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
                "SELECT scrip_code, symbol, xbrl_link, report_type FROM xbrl_filing_table WHERE scrip_code = ?",
                (scrip_code,),
            )
        else:
            cur.execute(
                "SELECT scrip_code, symbol, xbrl_link, report_type FROM xbrl_filing_table"
            )
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_period_by_xbrl_link(self, xbrl_link: str) -> Optional[str]:
        """Retrieve the publication_date (period) from xbrl_filing_table by xbrl_link."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT publication_date FROM xbrl_filing_table WHERE xbrl_link = ? LIMIT 1",
            (xbrl_link,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def get_latest_annual_data(self, scrip_code: str) -> Optional[dict]:
        """Get the latest annual data for a scrip_code."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM annual_table WHERE scrip_code = ? ORDER BY datetime(created_at) DESC, id DESC LIMIT 1",
            (scrip_code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_latest_quarterly_data(self, scrip_code: str) -> Optional[dict]:
        """Get the latest quarterly data for a scrip_code."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM quarterly_table WHERE scrip_code = ? ORDER BY datetime(created_at) DESC, id DESC LIMIT 1",
            (scrip_code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def find_peers(self, symbol: str) -> dict:
        """Find peers for the given company symbol based on annual sales +/-20% in same sector."""
        cur = self._conn.cursor()

        # Step 1: find sector for input symbol
        cur.execute(
            "SELECT sector FROM company_table WHERE symbol = ? LIMIT 1",
            (symbol,),
        )
        row = cur.fetchone()
        if not row or not row["sector"]:
            return {"sector": None, "target_sales": None, "target_level_of_rounding": None, "peers": []}

        sector = row["sector"]

        # Step 2: find latest annual record for input symbol
        cur.execute(
            "SELECT sales, level_of_rounding FROM annual_table WHERE company_symbol = ? ORDER BY datetime(created_at) DESC, id DESC LIMIT 1",
            (symbol,),
        )
        annual_row = cur.fetchone()
        if not annual_row or annual_row["sales"] is None:
            return {"sector": sector, "target_sales": None, "target_level_of_rounding": None, "peers": []}

        target_sales = float(annual_row["sales"])
        target_level = annual_row["level_of_rounding"]

        low = target_sales * 0.8
        high = target_sales * 1.2

        # Step 3: find peers in same sector and within +/-20% sales, using latest annual record per candidate
        cur.execute(
            """
            SELECT c.company_name, c.symbol, a.sales, a.level_of_rounding
            FROM annual_table a
            JOIN company_table c ON c.symbol = a.company_symbol
            WHERE c.sector = ?
              AND c.symbol != ?
              AND a.sales BETWEEN ? AND ?
              AND a.created_at = (
                  SELECT MAX(a2.created_at)
                  FROM annual_table a2
                  WHERE a2.company_symbol = a.company_symbol
              )
            """,
            (sector, symbol, low, high),
        )

        peer_rows = cur.fetchall()
        peers = [
            {
                "company_name": pr["company_name"],
                "symbol": pr["symbol"],
                "sales": float(pr["sales"]),
                "level_of_rounding": pr["level_of_rounding"],
            }
            for pr in peer_rows
            if pr["symbol"] != symbol
        ]

        return {
            "sector": sector,
            "target_sales": target_sales,
            "target_level_of_rounding": target_level,
            "peers": peers,
        }

    def xbrl_filing_recent(self, scrip_code: str, days: int = 10) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT 1 FROM xbrl_filing_table WHERE scrip_code = ? AND datetime(created_at) >= datetime('now', ? ) LIMIT 1",
            (scrip_code, f'-{days} days'),
        )
        return cur.fetchone() is not None

    def xbrl_extraction_exists(self, scrip_code: str, xbrl_link: str, report_type: str = "quarterly") -> bool:
        cur = self._conn.cursor()
        table = "quarterly_table" if report_type == "quarterly" else "annual_table"
        cur.execute(
            f"SELECT 1 FROM {table} WHERE scrip_code = ? AND xbrl_link = ? LIMIT 1",
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

    def insert_quarterly_extraction(
        self,
        scrip_code: str,
        xbrl_link: str,
        period: Optional[str] = None,
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
        cost_of_materials_consumed: Optional[float] = None,
        employee_benefit_expense: Optional[float] = None,
        other_expenses: Optional[float] = None,
        interest: Optional[float] = None,
        depreciation: Optional[float] = None,
        profit_before_tax: Optional[float] = None,
        current_tax: Optional[float] = None,
        deferred_tax: Optional[float] = None,
        tax: Optional[float] = None,
        tax_percent: Optional[float] = None,
        net_profit: Optional[float] = None,
        eps_in_rs: Optional[float] = None,
    ) -> int:
        cur = self._conn.cursor()
        columns = [
            "scrip_code",
            "xbrl_link",
            "period",
            "company_name",
            "company_symbol",
            "currency",
            "level_of_rounding",
            "reporting_type",
            "nature_of_report",
            "sales",
            "expenses",
            "operating_profit",
            "opm_percentage",
            "other_income",
            "cost_of_materials_consumed",
            "employee_benefit_expense",
            "other_expenses",
            "interest",
            "depreciation",
            "profit_before_tax",
            "current_tax",
            "deferred_tax",
            "tax",
            "tax_percent",
            "net_profit",
            "eps_in_rs",
        ]
        values = [
            scrip_code,
            xbrl_link,
            period,
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
            cost_of_materials_consumed,
            employee_benefit_expense,
            other_expenses,
            interest,
            depreciation,
            profit_before_tax,
            current_tax,
            deferred_tax,
            tax,
            tax_percent,
            net_profit,
            eps_in_rs,
        ]
        placeholder = ", ".join(["?"] * len(columns))
        cur.execute(
            f"INSERT INTO quarterly_table ({', '.join(columns)}) VALUES ({placeholder})",
            values,
        )
        self._conn.commit()
        return cur.lastrowid

    def insert_annual_extraction(
        self,
        scrip_code: str,
        xbrl_link: str,
        period: Optional[str] = None,
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
        tax_percent: Optional[float] = None,
        net_profit: Optional[float] = None,
        eps_in_rs: Optional[float] = None,
        equity_capital: Optional[float] = None,
        reserves: Optional[float] = None,
        trade_payables_current: Optional[float] = None,
        borrowings: Optional[float] = None,
        other_liabilities: Optional[float] = None,
        total_liabilities: Optional[float] = None,
        total_equity: Optional[float] = None,
        fixed_assets: Optional[float] = None,
        cwip: Optional[float] = None,
        investments: Optional[float] = None,
        total_assets: Optional[float] = None,
        cash_from_operating_activity: Optional[float] = None,
        cash_from_investing_activity: Optional[float] = None,
        cash_from_financing_activity: Optional[float] = None,
    ) -> int:
        cur = self._conn.cursor()
        columns = [
            "scrip_code",
            "xbrl_link",
            "period",
            "company_name",
            "company_symbol",
            "currency",
            "level_of_rounding",
            "reporting_type",
            "nature_of_report",
            "sales",
            "expenses",
            "operating_profit",
            "opm_percentage",
            "other_income",
            "interest",
            "depreciation",
            "profit_before_tax",
            "tax_percent",
            "net_profit",
            "eps_in_rs",
            "equity_capital",
            "reserves",
            "trade_payables_current",
            "borrowings",
            "other_liabilities",
            "total_liabilities",
            "total_equity",
            "fixed_assets",
            "cwip",
            "investments",
            "total_assets",
            "cash_from_operating_activity",
            "cash_from_investing_activity",
            "cash_from_financing_activity",
        ]

        values = [
            scrip_code,
            xbrl_link,
            period,
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
            tax_percent,
            net_profit,
            eps_in_rs,
            equity_capital,
            reserves,
            trade_payables_current,
            borrowings,
            other_liabilities,
            total_liabilities,
            total_equity,
            fixed_assets,
            cwip,
            investments,
            total_assets,
            cash_from_operating_activity,
            cash_from_investing_activity,
            cash_from_financing_activity,
        ]

        placeholders = ", ".join(["?"] * len(columns))
        cur.execute(
            f"INSERT INTO annual_table ({', '.join(columns)}) VALUES ({placeholders})",
            values,
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

    def save_chat(self, chat_id: str, user_query: str, response: str) -> None:
        """Save a chat message to history."""
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO chat_history (chat_id, user_query, response)
            VALUES (?, ?, ?)
            """,
            (chat_id, user_query, response)
        )
        self._conn.commit()

    def get_chat_history(self) -> list:
        """Get all chat history sorted by most recent first."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT chat_id, user_query, response, created_at
            FROM chat_history
            ORDER BY created_at DESC
            """
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_chat_by_id(self, chat_id: str) -> Optional[dict]:
        """Get a specific chat by ID."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT chat_id, user_query, response, created_at
            FROM chat_history
            WHERE chat_id = ?
            """,
            (chat_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

