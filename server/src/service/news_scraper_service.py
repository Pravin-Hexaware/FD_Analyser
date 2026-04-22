"""
Dedicated service for scraping, processing, and summarizing news articles.
Handles the workflow: fetch URLs -> scrape content -> save markdowns -> summarize.
"""
import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import List, Tuple
from urllib.parse import urlparse

from referenceNews import resolve_publisher_url, scrape_url_to_markdown

from service.analysis_service import _get_llm
from langchain_core.messages import HumanMessage


def safe_filename(value: str) -> str:
    """Convert string to safe filename."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value) or "article"


def _article_markdown_path(company_folder: Path, article_idx: int, title: str, publisher_url: str) -> Path:
    """Stable unique path per RSS item (avoids collisions from truncated titles)."""
    domain = (urlparse(publisher_url).netloc or "unknown").replace("www.", "")
    domain_part = safe_filename(domain)[:50]
    title_part = safe_filename(title)[:45]
    stem = f"{article_idx:02d}_{domain_part}_{title_part}".strip("_")
    # Windows MAX_PATH safety
    if len(stem) > 140:
        stem = stem[:140]
    return company_folder / f"{stem}.md"


def _fetch_and_markdown_one_article(
    company_name: str, title: str, raw_url: str, decode_interval: int = 1
) -> Tuple[str, str]:
    """
    Resolve Google News redirect URLs to the publisher page, then extract markdown.
    Returns (publisher_url, markdown_document).
    """
    publisher_url = resolve_publisher_url(raw_url, decode_interval=decode_interval)
    body = scrape_url_to_markdown(publisher_url, title, company_name)
    return publisher_url, body


class NewsScraperService:
    """Service to scrape articles and create summaries."""

    @staticmethod
    async def scrape_and_summarize_articles(
        company_name: str,
        articles: List[dict],
        websocket,
        idx: int
    ) -> Path:
        """
        Scrape articles, save as individual markdowns, and generate a summary.
        
        Args:
            company_name: Name of the company
            articles: List of article dicts with 'title' and 'url' keys
            websocket: WebSocket connection for status updates
            idx: Company index for logging
        
        Returns:
            Path to the summary folder
        """
        today = datetime.now().strftime("%Y%m%d")
        base_dir = Path(__file__).resolve().parents[1]  # server/src
        markdown_dir = base_dir / "markdown"
        company_date_folder = markdown_dir / f"{safe_filename(company_name)}_{today}"
        company_date_folder.mkdir(parents=True, exist_ok=True)

        markdown_files = []
        all_content = ""

        for article_idx, article in enumerate(articles, start=1):
            title = article.get("title", "Untitled")
            url = article.get("url", "")

            try:
                if not url or not url.strip():
                    raise ValueError("Empty article URL from RSS")

                await websocket.send_json({
                    "idx": idx,
                    "company_name": company_name,
                    "article_idx": article_idx,
                    "title": title,
                    "status": "scraping"
                })

                # Google News RSS links must be decoded to the publisher URL before HTTP fetch.
                publisher_url, markdown_content = await asyncio.to_thread(
                    _fetch_and_markdown_one_article,
                    company_name,
                    title,
                    url.strip(),
                    1,
                )

                file_path = _article_markdown_path(
                    company_date_folder, article_idx, title, publisher_url
                )
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)

                markdown_files.append(file_path)
                all_content += markdown_content + "\n\n" + "=" * 80 + "\n\n"

                await websocket.send_json({
                    "idx": idx,
                    "company_name": company_name,
                    "article_idx": article_idx,
                    "publisher_url": publisher_url,
                    "saved_path": str(file_path.name),
                    "status": "saved"
                })

                await asyncio.sleep(1)  # Rate limiting (decoder + politeness)

            except Exception as e:
                await websocket.send_json({
                    "idx": idx,
                    "company_name": company_name,
                    "article_idx": article_idx,
                    "rss_url": url,
                    "error": str(e),
                    "status": "scrape_failed"
                })

        # Generate summary
        summary_folder = company_date_folder / today
        summary_folder.mkdir(parents=True, exist_ok=True)

        await websocket.send_json({
            "idx": idx,
            "company_name": company_name,
            "saved_articles": len(markdown_files),
            "status": "summarizing"
        })

        if not markdown_files:
            summary = (
                "No article pages could be scraped for this company run. "
                "Check WebSocket messages with status scrape_failed for per-URL errors "
                "(decoding Google News links, paywalls, or JavaScript-only pages are common causes)."
            )
        else:
            summary = NewsScraperService._generate_summary(all_content, company_name)

        summary_file = summary_folder / "summary.md"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(f"# News Summary for {company_name} - {today}\n\n{summary}")

        await websocket.send_json({
            "idx": idx,
            "company_name": company_name,
            "status": "summarized"
        })

        return summary_folder

    @staticmethod
    def _generate_summary(content: str, company_name: str) -> str:
        """
        Summarize the aggregated news content using LLM.
        """
        stripped = (content or "").strip()
        if len(stripped) < 200:
            return (
                "Not enough extracted article text to summarize (minimum length not met). "
                "If scrape_failed events occurred for every URL, fix decoding/network or try again later."
            )

        llm = _get_llm()
        # Bound prompt size so very large pages do not blow context limits.
        max_chars = 120_000
        body = stripped if len(stripped) <= max_chars else stripped[:max_chars] + "\n\n[...truncated for model context...]"
        prompt = f"""Summarize the following news articles about {company_name} into a professional concise report.
Highlight key financial and business activities, organized by theme or chronologically:
- Earnings, revenue, and financial results
- Acquisitions, mergers, partnerships
- Layoffs, hiring, management changes
- Expansions, new facilities, market entry
- Regulatory actions, investigations
- Contracts and deals
- Other significant business developments

Keep it professional and factual. Base the summary only on the provided article excerpts below.

Content:
{body}
"""
        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            return f"Error generating summary: {str(e)}"
