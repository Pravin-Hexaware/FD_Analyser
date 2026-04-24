import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple


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
        """Add a column to a table if it doesn't exist. Safely handles non-existent tables."""
        cur = self._conn.cursor()
        try:
            cur.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cur.fetchall()]
            if column not in columns:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                self._conn.commit()
        except sqlite3.OperationalError:
            # Table doesn't exist, skip silently
            pass

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
                raw_content TEXT,
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

        # Redesigned tables for quarterly and annual extractions using parsed JSON
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quarterly_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scrip_code TEXT,
                company_name TEXT,
                xbrl_link TEXT,
                publication_date TEXT,
                report_type TEXT,
                parsed_json TEXT,  -- Store the complete parsed JSON from html_parser_service
                extraction_type TEXT,  -- 'quarterly'
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS annual_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scrip_code TEXT,
                company_name TEXT,
                xbrl_link TEXT,
                publication_date TEXT,
                report_type TEXT,
                parsed_json TEXT,  -- Store the complete parsed JSON from html_parser_service
                extraction_type TEXT,  -- 'annual'
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )

        # Conversation tables for chat history
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS roles (
                role TEXT PRIMARY KEY
            );
            """
        )
        cur.execute(
            """
            INSERT OR IGNORE INTO roles (role) VALUES ('user'), ('llm');
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                sequence_number INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                FOREIGN KEY (role) REFERENCES roles(role),
                UNIQUE(conversation_id, sequence_number)
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
        
        # Detailed LLM logging table - stores complete input/output data
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_detailed_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                step_name TEXT,
                input_data TEXT,
                output_data TEXT,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (chat_id) REFERENCES chat_history(chat_id)
            );
            """
        )
        
        # News feed storage table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS company_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scrip_code TEXT NOT NULL,
                company_name TEXT NOT NULL,
                news_title TEXT NOT NULL,
                news_link TEXT,
                news_summary TEXT,
                published_date TEXT,
                source TEXT,
                keywords TEXT,
                fetched_at TEXT DEFAULT (datetime('now')),
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(scrip_code, news_title, published_date)
            );
            """
        )

        # Create index for faster lookups
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_company_news_scrip_code 
            ON company_news(scrip_code);
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_company_news_fetched_at 
            ON company_news(fetched_at);
            """
        )

        self._conn.commit()

        # Ensure parsed_json column in quarterly_extractions
        self._ensure_column("quarterly_extractions", "parsed_json", "TEXT")
        
        # Ensure parsed_json column in annual_extractions
        self._ensure_column("annual_extractions", "parsed_json", "TEXT")
        
        # Ensure raw_content column in xbrl_filing_table
        self._ensure_column("xbrl_filing_table", "raw_content", "TEXT")

    def create_conversation(self) -> int:
        cur = self._conn.cursor()
        cur.execute("INSERT INTO conversations DEFAULT VALUES")
        self._conn.commit()
        return cur.lastrowid

    def conversation_exists(self, conversation_id: int) -> bool:
        cur = self._conn.cursor()
        cur.execute("SELECT 1 FROM conversations WHERE id = ? LIMIT 1", (conversation_id,))
        return cur.fetchone() is not None

    def get_conversation(self, conversation_id: int) -> Optional[dict]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id AS chat_id, created_at FROM conversations WHERE id = ? LIMIT 1",
            (conversation_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_next_sequence_number(self, conversation_id: int) -> int:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 1

    def save_message(self, conversation_id: int, role: str, content: str) -> int:
        if role not in ("user", "llm"):
            raise ValueError("Invalid role. Must be 'user' or 'llm'.")

        if not self.conversation_exists(conversation_id):
            raise ValueError(f"Conversation {conversation_id} does not exist")

        sequence_number = self.get_next_sequence_number(conversation_id)
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO messages (conversation_id, sequence_number, role, content)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, sequence_number, role, content),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_conversation_messages(self, conversation_id: int) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, conversation_id, sequence_number, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY sequence_number ASC
            """,
            (conversation_id,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_conversation_list(self) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT c.id AS chat_id,
                   c.created_at,
                   first_m.content AS first_message,
                   last_m.content AS last_message,
                   last_m.role AS last_role,
                   last_m.sequence_number AS last_sequence,
                   last_m.created_at AS last_updated
            FROM conversations c
            LEFT JOIN messages first_m ON first_m.conversation_id = c.id
              AND first_m.sequence_number = (
                  SELECT MIN(sequence_number) FROM messages WHERE conversation_id = c.id
              )
            LEFT JOIN messages last_m ON last_m.conversation_id = c.id
              AND last_m.sequence_number = (
                  SELECT MAX(sequence_number) FROM messages WHERE conversation_id = c.id
              )
            ORDER BY COALESCE(last_m.created_at, c.created_at) DESC
            """
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]

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

    def get_all_companies(self) -> list[dict]:
        """Get all companies from company_table."""
        cur = self._conn.cursor()
        cur.execute("SELECT company_name, symbol, scrip_code, sector, industry FROM company_table")
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def xbrl_filing_exists(self, scrip_code: str, xbrl_link: str, report_type: Optional[str] = None,publication_date: Optional[str] = None) -> bool:
        cur = self._conn.cursor()
        if publication_date is not None:
            # Check full tuple: scrip_code + xbrl_link + publication_date
            cur.execute(
                "SELECT 1 FROM xbrl_filing_table WHERE scrip_code = ? AND xbrl_link = ? AND publication_date = ? LIMIT 1",
                (scrip_code, xbrl_link, publication_date),
            )
        elif report_type is None:
            # Check just scrip_code + xbrl_link
            cur.execute(
                "SELECT 1 FROM xbrl_filing_table WHERE scrip_code = ? AND xbrl_link = ? LIMIT 1",
                (scrip_code, xbrl_link),
            )
        else:
            # Check scrip_code + xbrl_link + report_type
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
                "SELECT scrip_code, symbol, xbrl_link, publication_date, report_type FROM xbrl_filing_table WHERE scrip_code = ?",
                (scrip_code,),
            )
        else:
            cur.execute(
                "SELECT scrip_code, symbol, xbrl_link, publication_date, report_type FROM xbrl_filing_table"
            )
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_xbrl_filings_with_company_and_content(self) -> list[dict]:
        """Get XBRL filings with company name from company_table and raw_content."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT 
                f.scrip_code, 
                f.symbol, 
                f.xbrl_link, 
                f.publication_date, 
                f.report_type, 
                f.raw_content,
                c.company_name
            FROM xbrl_filing_table f
            LEFT JOIN company_table c ON f.scrip_code = c.scrip_code
            """
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_xbrl_filings_by_scrip_codes(
        self,
        scrip_codes: list[str],
        report_type: str = "std",
        limit: int = 10,
    ) -> dict[str, list[dict]]:
        """
        Get XBRL filings with raw_content for multiple scrip_codes.
        Returns a dict mapping scrip_code to list of filing records.
        Only includes records with:
        - report_type == report_type (default "std")
        - raw_content is not NULL
        """
        result = {code: [] for code in scrip_codes}
        cur = self._conn.cursor()
        
        for scrip_code in scrip_codes:
            cur.execute(
                """
                SELECT 
                    f.scrip_code, 
                    f.symbol, 
                    f.xbrl_link, 
                    f.publication_date, 
                    f.report_type, 
                    f.raw_content,
                    c.company_name
                FROM xbrl_filing_table f
                LEFT JOIN company_table c ON f.scrip_code = c.scrip_code
                WHERE f.scrip_code = ? AND f.report_type = ? AND f.raw_content IS NOT NULL
                ORDER BY f.publication_date DESC
                LIMIT ?
                """,
                (scrip_code, report_type, limit),
            )
            rows = cur.fetchall()
            result[scrip_code] = [dict(row) for row in rows]
        
        return result

    def get_xbrl_filings_count(self, scrip_code: str) -> int:
        """Get count of XBRL filings for a specific company."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT COUNT(*) as count FROM xbrl_filing_table WHERE scrip_code = ?",
            (scrip_code,),
        )
        row = cur.fetchone()
        return row["count"] if row else 0
    def get_period_by_xbrl_link(self, xbrl_link: str) -> Optional[str]:
        """Retrieve the publication_date (period) from xbrl_filing_table by xbrl_link."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT publication_date FROM xbrl_filing_table WHERE xbrl_link = ? LIMIT 1",
            (xbrl_link,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def get_extraction_records(
        self,
        scrip_code: str,
        extraction_type: str = "annual",
        limit: int = 10
    ) -> list[dict]:
        """
        Get extraction records (annual or quarterly) for a company.
        Returns list of records with company_name and publication_date.
        extraction_type: "annual" or "quarterly"
        """
        if extraction_type.lower() not in {"annual", "quarterly"}:
            extraction_type = "annual"
        
        table_name = f"{extraction_type.lower()}_extractions"
        cur = self._conn.cursor()
        
        # Query extraction records ordered by publication_date (newest first)
        cur.execute(
            f"""
            SELECT 
                id,
                scrip_code,
                company_name,
                xbrl_link,
                publication_date,
                report_type,
                parsed_json
            FROM {table_name}
            WHERE scrip_code = ?
            ORDER BY publication_date DESC
            LIMIT ?
            """,
            (scrip_code, limit),
        )
        
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def _load_parsed_json_row(self, row: sqlite3.Row) -> dict:
        if not row:
            return {}
        row_dict = dict(row)
        parsed = row_dict.get("parsed_json")
        if isinstance(parsed, str):
            try:
                row_dict["parsed_json"] = json.loads(parsed)
            except json.JSONDecodeError:
                # Keep original string if it is not valid JSON
                pass
        return row_dict

    def _extract_years_from_period_label(self, label: Optional[str]) -> list[int]:
        if not label:
            return []
        return [int(year) for year in re.findall(r"\d{4}", str(label))]

    def _matches_time_filter(
        self,
        publication_date: Optional[str],
        period_filter: Optional[str],
        last_n_years: Optional[int],
    ) -> bool:
        if last_n_years is not None:
            return self._matches_recent_years(publication_date, last_n_years)

        if not period_filter:
            return True

        period_text = period_filter.strip().lower()
        if period_text in ["latest", "current", "recent"]:
            return True
        if period_text in ["latest quarter"]:
            return True
        if period_text in ["latest year", "latest financial year", "last year", "last financial year", "previous year", "previous financial year"]:
            return self._matches_latest_fiscal_year(publication_date)

        quarter_map = {
            "march": "mq",
            "mq": "mq",
            "june": "jq",
            "jq": "jq",
            "september": "sq",
            "sep": "sq",
            "sq": "sq",
            "december": "dq",
            "dec": "dq",
            "dq": "dq",
        }
        if period_text in quarter_map:
            normalized = quarter_map[period_text]
            return normalized in str(publication_date or "").lower()

        last_years_match = re.search(r"last\s+(\d+)\s*years?", period_text)
        if last_years_match:
            return self._matches_time_filter(publication_date, None, int(last_years_match.group(1)))

        years = self._extract_years_from_period_label(period_text)
        if years:
            return any(str(year) in str(publication_date or "") for year in years)

        return period_text in str(publication_date or "").lower()

    def _matches_latest_fiscal_year(self, publication_date: Optional[str]) -> bool:
        if not publication_date:
            return False

        current_date = datetime.utcnow()
        if current_date.month >= 4:
            start_year = current_date.year - 1
            end_year = current_date.year
        else:
            start_year = current_date.year - 2
            end_year = current_date.year - 1

        years = self._extract_years_from_period_label(publication_date)
        return bool(years and start_year in years and end_year in years)

    def _matches_recent_years(self, publication_date: Optional[str], last_n_years: int) -> bool:
        years = self._extract_years_from_period_label(publication_date)
        if not years:
            return False

        current_year = datetime.utcnow().year
        start_year = current_year - last_n_years
        end_year = current_year - 1
        return any(start_year <= year <= end_year for year in years)

    def get_latest_extraction(self, scrip_code: str, extraction_type: str) -> Optional[dict]:
        table = "quarterly_extractions" if extraction_type == "quarterly" else "annual_extractions"
        cur = self._conn.cursor()
        cur.execute(
            f"SELECT * FROM {table} WHERE scrip_code = ?",
            (scrip_code,),
        )
        rows = [self._load_parsed_json_row(row) for row in cur.fetchall()]
        
        if not rows:
            return None
        
        # Sort by reporting end date (most recent first), fallback to created_at and id
        def sort_key(row):
            end_date = self._extract_reporting_end_date(row.get("parsed_json"), row.get("publication_date"))
            if end_date:
                return (0, end_date)  # 0 to prioritize rows with dates
            created_at = row.get("created_at", "")
            row_id = row.get("id", 0)
            return (1, created_at, row_id)  # Fallback sorting
        
        rows.sort(key=sort_key, reverse=True)
        
        return rows[0]

    def get_historical_extractions(
        self,
        scrip_code: str,
        extraction_type: str,
        limit: int = 5,
    ) -> list[dict]:
        table = "quarterly_extractions" if extraction_type == "quarterly" else "annual_extractions"
        cur = self._conn.cursor()
        cur.execute(
            f"SELECT * FROM {table} WHERE scrip_code = ?",
            (scrip_code,),
        )
        rows = [self._load_parsed_json_row(row) for row in cur.fetchall()]
        
        # Sort by reporting end date (most recent first), fallback to created_at and id
        def sort_key(row):
            end_date = self._extract_reporting_end_date(row.get("parsed_json"))
            if end_date:
                return (0, end_date)  # 0 to prioritize rows with dates
            created_at = row.get("created_at", "")
            row_id = row.get("id", 0)
            return (1, created_at, row_id)  # Fallback sorting
        
        rows.sort(key=sort_key, reverse=True)
        
        return rows[:limit]

    def _extract_reporting_end_date(self, parsed_json: Any, publication_date: str = None) -> Optional[datetime]:
        """Extract the DateOfEndOfReportingPeriod from parsed_json or infer from publication_date."""
        if not isinstance(parsed_json, dict):
            return None
        
        date_of_end = parsed_json.get("DateOfEndOfReportingPeriod")
        if date_of_end and isinstance(date_of_end, list) and date_of_end:
            date_str = date_of_end[0].get("value")
            if date_str:
                try:
                    return datetime.fromisoformat(date_str)
                except (ValueError, TypeError):
                    pass
        
        # Fallback: parse from publication_date for quarterly/annual
        if publication_date:
            return self._parse_end_date_from_publication(publication_date)
        
        return None

    def _parse_end_date_from_publication(self, publication_date: str) -> Optional[datetime]:
        """Parse end date from publication_date like 'DQ2025-2026'."""
        import re
        match = re.match(r'([A-Z]+)(\d{4})-(\d{4})', publication_date)
        if not match:
            return None
        
        quarter, start_year, end_year = match.groups()
        start_year = int(start_year)
        end_year = int(end_year)
        
        if quarter == 'MQ':  # March Quarter
            return datetime(end_year, 3, 31)
        elif quarter == 'JQ':  # June Quarter
            return datetime(start_year, 6, 30)
        elif quarter == 'SQ':  # September Quarter
            return datetime(start_year, 9, 30)
        elif quarter == 'DQ':  # December Quarter
            return datetime(start_year, 12, 31)
        elif publication_date.startswith('FY'):  # Annual
            return datetime(end_year, 3, 31)
        
        return None

    def _get_periods_priority(self, current_date: datetime) -> dict[str, int]:
        """Get priority mapping for quarterly periods based on current date."""
        year = current_date.year
        month = current_date.month
        periods = []
        if month >= 4:
            periods.append(f"MQ{year}-{year}")
            periods.append(f"DQ{year-1}-{year}")
            periods.append(f"SQ{year-1}-{year}")
            periods.append(f"JQ{year-1}-{year}")
            periods.append(f"MQ{year-1}-{year}")
        else:
            periods.append(f"MQ{year-1}-{year}")
            periods.append(f"DQ{year-2}-{year-1}")
            periods.append(f"SQ{year-2}-{year-1}")
            periods.append(f"JQ{year-2}-{year-1}")
            periods.append(f"MQ{year-2}-{year-1}")
        return {p: i for i, p in enumerate(periods)}

    def _get_annual_periods_priority(self, current_date: datetime) -> dict[str, int]:
        """Get priority mapping for annual periods based on current date."""
        year = current_date.year
        month = current_date.month
        periods = []
        if month >= 4:
            periods.append(f"FY{year-1}-{year}")
            periods.append(f"FY{year-2}-{year-1}")
            periods.append(f"FY{year-3}-{year-2}")
        else:
            periods.append(f"FY{year-2}-{year-1}")
            periods.append(f"FY{year-3}-{year-2}")
            periods.append(f"FY{year-4}-{year-3}")
        return {p: i for i, p in enumerate(periods)}

    def get_extraction_records(
        self,
        scrip_code: str,
        extraction_type: str,
        period: Optional[str] = None,
        last_n_years: Optional[int] = None,
        latest_only: bool = False,
        limit: int = 5,
    ) -> list[dict]:
        table = "quarterly_extractions" if extraction_type == "quarterly" else "annual_extractions"
        cur = self._conn.cursor()
        cur.execute(
            f"SELECT * FROM {table} WHERE scrip_code = ?",
            (scrip_code,),
        )
        rows = [self._load_parsed_json_row(row) for row in cur.fetchall()]
        
        if period == "latest quarter":
            # Special sorting for latest quarter based on current date
            current_date = datetime.now()
            periods_priority = self._get_periods_priority(current_date)
            def priority_sort_key(row):
                pub_date = row.get("publication_date", "")
                priority = periods_priority.get(pub_date, 999)
                # Secondary sort by reporting end date (most recent first)
                end_date = self._extract_reporting_end_date(row.get("parsed_json"), pub_date)
                if end_date:
                    return (priority, -end_date.timestamp())  # Negative for descending
                created_at = row.get("created_at", "")
                row_id = row.get("id", 0)
                return (priority, float('-inf'), created_at, row_id)  # Old records last
            rows.sort(key=priority_sort_key)
        elif period == "latest year":
            # Special sorting for latest year based on current date
            current_date = datetime.now()
            periods_priority = self._get_annual_periods_priority(current_date)
            def priority_sort_key(row):
                pub_date = row.get("publication_date", "")
                priority = periods_priority.get(pub_date, 999)
                # Secondary sort by reporting end date (most recent first)
                end_date = self._extract_reporting_end_date(row.get("parsed_json"), pub_date)
                if end_date:
                    return (priority, -end_date.timestamp())  # Negative for descending
                created_at = row.get("created_at", "")
                row_id = row.get("id", 0)
                return (priority, float('-inf'), created_at, row_id)  # Old records last
            rows.sort(key=priority_sort_key)
        else:
            # Sort by reporting end date (most recent first), fallback to created_at and id
            def sort_key(row):
                end_date = self._extract_reporting_end_date(row.get("parsed_json"), row.get("publication_date"))
                if end_date:
                    return (0, end_date)  # 0 to prioritize rows with dates
                created_at = row.get("created_at", "")
                row_id = row.get("id", 0)
                return (1, created_at, row_id)  # Fallback sorting
            
            rows.sort(key=sort_key, reverse=True)
        
        filtered = [
            row for row in rows
            if self._matches_time_filter(row.get("publication_date"), period, last_n_years)
        ]
        if latest_only and filtered:
            return [filtered[0]]
        return filtered[:limit]

    def get_latest_annual_data(self, scrip_code: str) -> Optional[dict]:
        """Get the latest annual data for a scrip_code."""
        return self.get_latest_extraction(scrip_code, "annual")

    def get_latest_quarterly_data(self, scrip_code: str) -> Optional[dict]:
        """Get the latest quarterly data for a scrip_code."""
        return self.get_latest_extraction(scrip_code, "quarterly")

    def get_historical_annual_data(self, scrip_code: str, limit: int = 5) -> list[dict]:
        """Get historical annual data for a scrip_code, most recent first."""
        return self.get_historical_extractions(scrip_code, "annual", limit)

    def get_historical_quarterly_data(self, scrip_code: str, limit: int = 5) -> list[dict]:
        """Get historical quarterly data for a scrip_code, most recent first."""
        return self.get_historical_extractions(scrip_code, "quarterly", limit)

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

    def xbrl_extraction_exists(self, scrip_code: str, xbrl_link: str, extraction_type: str = "quarterly") -> bool:
        """Check if extraction already exists in the appropriate table."""
        cur = self._conn.cursor()
        table = "quarterly_extractions" if extraction_type == "quarterly" else "annual_extractions"
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
        company_name: str,
        xbrl_link: str,
        publication_date: str,
        report_type: str,
        parsed_json: str,
    ) -> int:
        """Insert quarterly extraction with parsed JSON data."""
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO quarterly_extractions 
            (scrip_code, company_name, xbrl_link, publication_date, report_type, parsed_json, extraction_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (scrip_code, company_name, xbrl_link, publication_date, report_type, parsed_json, "quarterly"),
        )
        self._conn.commit()
        return cur.lastrowid

    def insert_annual_extraction(
        self,
        scrip_code: str,
        company_name: str,
        xbrl_link: str,
        publication_date: str,
        report_type: str,
        parsed_json: str,
    ) -> int:
        """Insert annual extraction with parsed JSON data."""
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO annual_extractions 
            (scrip_code, company_name, xbrl_link, publication_date, report_type, parsed_json, extraction_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (scrip_code, company_name, xbrl_link, publication_date, report_type, parsed_json, "annual"),
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
        raw_content: Optional[str] = None,
    ) -> int:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO xbrl_filing_table (scrip_code, symbol, xbrl_link, publication_date, report_type, raw_content)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (scrip_code, symbol, xbrl_link, publication_date, report_type, raw_content),
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

    def save_detailed_log(self, chat_id: str, step_name: str, input_data: str, output_data: str) -> None:
        """Save detailed LLM processing log with input and output data."""
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO llm_detailed_log (chat_id, step_name, input_data, output_data)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, step_name, input_data, output_data)
        )
        self._conn.commit()

    def get_detailed_logs(self, chat_id: str) -> list:
        """Get all detailed logs for a specific chat."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, chat_id, step_name, input_data, output_data, timestamp
            FROM llm_detailed_log
            WHERE chat_id = ?
            ORDER BY timestamp ASC
            """,
            (chat_id,)
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            result.append({
                'id': row[0],
                'chat_id': row[1],
                'step_name': row[2],
                'input_data': row[3],
                'output_data': row[4],
                'timestamp': row[5]
            })
        return result

    # News management methods
    def save_company_news(
        self,
        scrip_code: str,
        company_name: str,
        articles: list
    ) -> None:
        """Save fetched company news articles to the database."""
        cur = self._conn.cursor()

        for article in articles:
            try:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO company_news 
                    (scrip_code, company_name, news_title, news_link, news_summary, 
                     published_date, source, keywords)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scrip_code,
                        company_name,
                        article.get("title", ""),
                        article.get("link", ""),
                        article.get("summary", ""),
                        article.get("published", ""),
                        article.get("source", ""),
                        json.dumps(article.get("keywords", []))
                    )
                )
            except sqlite3.IntegrityError:
                # Article already exists, skip
                pass

        self._conn.commit()

    def get_company_news(
        self,
        scrip_code: str,
        days_back: int = 30,
        limit: int = 10
    ) -> list:
        """Retrieve recent news articles for a company."""
        cur = self._conn.cursor()

        # Calculate date threshold
        from datetime import datetime, timedelta
        threshold_date = (datetime.now() - timedelta(days=days_back)).isoformat()

        cur.execute(
            """
            SELECT id, company_name, news_title, news_link, news_summary, 
                   published_date, source, keywords, fetched_at
            FROM company_news
            WHERE scrip_code = ? AND fetched_at >= ?
            ORDER BY fetched_at DESC, published_date DESC
            LIMIT ?
            """,
            (scrip_code, threshold_date, limit)
        )

        rows = cur.fetchall()
        result = []

        for row in rows:
            result.append({
                'id': row[0],
                'company_name': row[1],
                'title': row[2],
                'link': row[3],
                'summary': row[4],
                'published': row[5],
                'source': row[6],
                'keywords': json.loads(row[7]) if row[7] else [],
                'fetched_at': row[8]
            })

        return result

    def clear_old_news(self, days_old: int = 90) -> int:
        """Delete news articles older than specified days."""
        cur = self._conn.cursor()

        from datetime import datetime, timedelta
        threshold_date = (datetime.now() - timedelta(days=days_old)).isoformat()

        cur.execute(
            """
            DELETE FROM company_news
            WHERE fetched_at < ?
            """,
            (threshold_date,)
        )

        self._conn.commit()
        return cur.rowcount


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

