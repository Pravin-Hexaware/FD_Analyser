"""
Compatibility facade over Tortoise repositories.

Keeps the historical SqliteRepository method names so routes/services can migrate
incrementally. All methods are async; there is no raw SQL.
"""
from __future__ import annotations

from typing import Any, List, Optional

from repositories import chat_repository as chat_repo
from repositories import company_repository as company_repo
from repositories import index_repository as index_repo
from repositories import metrics_repository as metrics_repo
from repositories import xbrl_repository as xbrl_repo


class SqliteRepository:
    """Async facade — name retained for call-site compatibility during Phase 1."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path  # unused; Tortoise uses global config

    def close(self) -> None:
        return None

    # ---- company ----
    async def upsert_company(self, **kwargs):
        return await company_repo.upsert_company(**kwargs)

    async def company_exists(self, scrip_code: str) -> bool:
        return await company_repo.company_exists(scrip_code)

    async def get_all_companies(self) -> list[dict]:
        return await company_repo.get_all_companies()

    async def delete_companies_by_sector(self, sector: str) -> int:
        return await company_repo.delete_companies_by_sector(sector)

    async def find_peers(self, symbol: str) -> dict:
        return await company_repo.find_peers(symbol)

    # ---- xbrl ----
    async def insert_xbrl_filing(self, **kwargs) -> int:
        return await xbrl_repo.insert_xbrl_filing(**kwargs)

    async def xbrl_filing_exists(self, *args, **kwargs) -> bool:
        return await xbrl_repo.xbrl_filing_exists(*args, **kwargs)

    async def get_xbrl_filing_id(self, *args, **kwargs):
        return await xbrl_repo.get_xbrl_filing_id(*args, **kwargs)

    async def get_xbrl_filings(self, scrip_code: str | None = None) -> list[dict]:
        return await xbrl_repo.get_xbrl_filings(scrip_code)

    async def get_xbrl_filings_with_company_and_content(self) -> list[dict]:
        return await xbrl_repo.get_xbrl_filings_with_company_and_content()

    async def get_xbrl_filings_by_scrip_codes(self, scrip_codes: List[str]) -> list[dict]:
        return await xbrl_repo.get_xbrl_filings_by_scrip_codes(scrip_codes)

    async def get_xbrl_filings_count(self, scrip_code: str) -> int:
        return await xbrl_repo.get_xbrl_filings_count(scrip_code)

    async def get_period_by_xbrl_link(self, xbrl_link: str):
        return await xbrl_repo.get_period_by_xbrl_link(xbrl_link)

    async def xbrl_filing_recent(self, scrip_code: str, days: int = 10) -> bool:
        return await xbrl_repo.xbrl_filing_recent(scrip_code, days)

    # ---- metrics / extractions ----
    async def insert_quarterly_extraction(self, **kwargs) -> int:
        return await metrics_repo.insert_quarterly_extraction(**kwargs)

    async def insert_annual_extraction(self, **kwargs) -> int:
        return await metrics_repo.insert_annual_extraction(**kwargs)

    async def xbrl_extraction_exists(self, *args, **kwargs) -> bool:
        return await metrics_repo.xbrl_extraction_exists(*args, **kwargs)

    async def get_latest_extraction(self, scrip_code: str, extraction_type: str):
        return await metrics_repo.get_latest_extraction(scrip_code, extraction_type)

    async def get_historical_extractions(self, scrip_code: str, extraction_type: str, limit: int = 5):
        return await metrics_repo.get_historical_extractions(scrip_code, extraction_type, limit)

    async def get_extraction_records(self, *args, **kwargs):
        return await metrics_repo.get_extraction_records(*args, **kwargs)

    async def get_latest_annual_data(self, scrip_code: str):
        return await metrics_repo.get_latest_annual_data(scrip_code)

    async def get_latest_quarterly_data(self, scrip_code: str):
        return await metrics_repo.get_latest_quarterly_data(scrip_code)

    async def get_historical_annual_data(self, scrip_code: str, limit: int = 5):
        return await metrics_repo.get_historical_annual_data(scrip_code, limit)

    async def get_historical_quarterly_data(self, scrip_code: str, limit: int = 5):
        return await metrics_repo.get_historical_quarterly_data(scrip_code, limit)

    async def insert_xbrl_extraction(self, **kwargs) -> int:
        # Legacy flat extraction → quarterly upsert
        return await metrics_repo.upsert_quarterly_metrics(
            scrip_code=kwargs.get("scrip_code", ""),
            period=kwargs.get("publication_date") or kwargs.get("period") or "",
            category="std",
            flat=kwargs,
            metrics_json=kwargs,
        )

    # ---- chat ----
    async def create_conversation(self) -> int:
        return await chat_repo.create_conversation()

    async def conversation_exists(self, conversation_id: int) -> bool:
        return await chat_repo.conversation_exists(conversation_id)

    async def get_conversation(self, conversation_id: int):
        return await chat_repo.get_conversation(conversation_id)

    async def get_next_sequence_number(self, conversation_id: int) -> int:
        return await chat_repo.get_next_sequence_number(conversation_id)

    async def save_message(self, conversation_id: int, role: str, content: str) -> int:
        return await chat_repo.save_message(conversation_id, role, content)

    async def get_conversation_messages(self, conversation_id: int) -> list[dict]:
        return await chat_repo.get_conversation_messages(conversation_id)

    async def get_conversation_list(self) -> list[dict]:
        return await chat_repo.get_conversation_list()

    async def save_chat(self, chat_id: str, user_query: str, response: str) -> None:
        await chat_repo.save_chat(chat_id, user_query, response)

    async def save_detailed_log(self, chat_id: str, step_name: str, input_data: str, output_data: str) -> None:
        await chat_repo.save_detailed_log(chat_id, step_name, input_data, output_data)

    async def get_chat_history(self) -> list:
        return await chat_repo.get_chat_history()

    async def get_chat_by_id(self, chat_id: str):
        return await chat_repo.get_chat_by_id(chat_id)

    # ---- indexes / nifty ----
    async def get_nifty500_last_updated(self):
        return await index_repo.get_nifty500_last_updated()

    async def replace_nifty500_rows(self, rows: list[dict], updated_at: str) -> int:
        return await index_repo.replace_nifty500_rows(rows, updated_at)

    async def get_all_nifty500(self) -> list[dict]:
        return await index_repo.get_all_nifty500()

    async def get_scrip_codes_missing_fiscal_year(self, *args, **kwargs):
        return await index_repo.get_scrip_codes_missing_fiscal_year(*args, **kwargs)

    # ---- news stubs (no schema table) ----
    async def save_company_news(self, **kwargs) -> int:
        return 0

    async def get_company_news(self, **kwargs) -> list:
        return []

    async def clear_old_news(self, days_old: int = 90) -> int:
        return 0
