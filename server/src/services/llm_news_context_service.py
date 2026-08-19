"""News context helpers for LLM pipeline."""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import MARKDOWN_DIR
from services.analysis_service import (
    _get_or_fetch_today_news_summary,
    _invoke_llm,
    _normalize_company_folder_name,
    _normalize_llm_response,
)


def news_cache_path(company_name: str, scrip_code: str) -> Path:
    safe_name = _normalize_company_folder_name(company_name)
    today = datetime.now().strftime("%Y%m%d")
    return MARKDOWN_DIR / safe_name / today


def get_latest_cached_news_summary(company_name: str, require_today_only: bool = False) -> Optional[str]:
    if not company_name:
        return None

    safe_name = _normalize_company_folder_name(company_name)
    company_folder = MARKDOWN_DIR / safe_name
    if not company_folder.exists():
        return None

    today = datetime.now().strftime("%Y%m%d")
    date_folders = sorted(
        [p for p in company_folder.iterdir() if p.is_dir() and p.name.isdigit()],
        reverse=True,
    )
    if require_today_only:
        date_folders = [p for p in date_folders if p.name == today]

    for folder in date_folders:
        article_files = [
            path for path in sorted(folder.glob("*.md"))
            if path.name.lower() != "summary.md"
        ]
        if article_files:
            contents = []
            for path in article_files:
                try:
                    contents.append(path.read_text(encoding="utf-8").strip())
                except Exception as e:
                    print(e)
            if contents:
                return "\n\n".join(contents)

        summary_file = folder / "summary.md"
        if summary_file.exists() and summary_file.is_file():
            try:
                return summary_file.read_text(encoding="utf-8").strip()
            except Exception as e:
                print(e)

    return None


async def check_news_exists(company_name: str, scrip_code: str, resolved_name: Optional[str] = None) -> bool:
    try:
        if get_latest_cached_news_summary(company_name, require_today_only=True) is not None:
            return True
        if resolved_name and resolved_name != company_name:
            if get_latest_cached_news_summary(resolved_name, require_today_only=True) is not None:
                return True
        return False
    except Exception:
        return False


async def fetch_news_for_company(
    company_name: str,
    scrip_code: str,
    validated_name: Optional[str] = None,
) -> Optional[str]:
    try:
        resolved_name = validated_name or company_name
        return await _get_or_fetch_today_news_summary(resolved_name, scrip_code)
    except Exception as e:
        print(f"[ERROR] Failed to fetch news for {company_name}: {str(e)}")
        return None


async def generate_news_impact_section(
    original_report: str,
    query: str,
    company_data: Dict[str, Any],
    news_context: str,
    statement_type: str,
    frequency: str,
) -> str:
    system_prompt = """You are a Senior Financial Analyst providing strategic insights.

You will receive an existing report body plus recent news context. Generate one concise, polished section that integrates the news into the analysis without repeating the title or reprinting the entire report.

Requirements:
- Keep the report seamless and professional
- Add a clear section such as '## IX. News-Driven Assessment and Outlook' or similar
- Explain how recent news changes the interpretation of financial performance, risk, and outlook
- Include implications for revenue, margin, cash flow, balance sheet, and strategic positioning
- Must include a dedicated final conclusion or overall assessment section at the end of the response
- The conclusion must clearly summarize the overall report and provide a final recommendation or takeaway

Do not repeat the full title, do not add 'phase 1'/'phase 2' markers, and do not include any separator text like 'END OF REPORT'."""

    user_prompt = f"""Original Query: {query}

Recent News Articles and Market Developments:
{news_context}

Company Financial Data:
{json.dumps(company_data, indent=2)}

Existing Report Body:
---
{original_report}
---

Generate one seamless section that integrates the recent news into the report and improves the final analysis. The output should be only the new section content, ready to be appended to the existing report."""

    try:
        response = _invoke_llm(system_prompt, user_prompt, max_tokens=2000)
        normalized = _normalize_llm_response(response)
        return normalized.get("content", "")
    except Exception as e:
        print(f"[ERROR] Failed to generate news impact section: {str(e)}")
        return ""
