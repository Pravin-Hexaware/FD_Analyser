import asyncio
import re
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional
from urllib.parse import urlparse
 

from bs4 import BeautifulSoup
from markdownify import markdownify as md
import trafilatura
import urllib3
from googlenewsdecoder import gnewsdecoder

from service.analysis_service import _get_llm
from service.news_service import NewsService, get_company_domains, is_trusted_source_url, BLACKLIST
from langchain_core.messages import HumanMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def safe_filename(value: str) -> str:
    """Convert string to safe filename."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value) or "article"


def _get_page_html(url: str) -> str:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": origin,
        "Connection": "keep-alive"
    }

    url = url.replace("m.economictimes.com", "economictimes.indiatimes.com")

    response = requests.get(
        url,
        headers=headers,
        timeout=30,
        verify=False,
        allow_redirects=True
    )

    response.raise_for_status()
    return response.text
 
 
def _extract_markdown_trafilatura(html: str, page_url: str) -> Optional[str]:
    text = trafilatura.extract(
        html,
        url=page_url,
        output_format="markdown",
        favor_precision=True
    )
    return text.strip() if text else None
 
 
def _extract_markdown_from_pruned_soup(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "iframe", "header", "footer"]):
        tag.decompose()

    selectors = [
        "article",
        ".article-body",
        ".story-content",
        ".post-content",
        "main"
    ]

    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return md(str(node))

    paragraphs = soup.find_all("p")
    return "\n".join(p.get_text() for p in paragraphs)
 
 
def _resolve_publisher_url(google_or_any_url: str, decode_interval: Optional[int] = 1) -> str:
    netloc = (urlparse(google_or_any_url).netloc or "").lower()
    if "news.google.com" in netloc:
        if decode_interval:
            time.sleep(decode_interval)
        result = gnewsdecoder(google_or_any_url, interval=0)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
        raise RuntimeError(result.get("message", "gnewsdecoder failed to resolve URL"))
    return google_or_any_url
 
 
def _scrape_url_to_markdown(publisher_url: str, title: str, company: str, published: str) -> str:
    html = _get_page_html(publisher_url)

    content = _extract_markdown_trafilatura(html, publisher_url)

    if not content:
        content = _extract_markdown_from_pruned_soup(html)

    return f"""# {title}

Company: {company}
Published: {published}
Source: {publisher_url}
Fetched: {datetime.now().isoformat()}

---

{content}
"""
 
 
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
 
 
def _get_company_date_folder_path(company_name: str, date_str: Optional[str] = None) -> Path:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    base_dir = Path(__file__).resolve().parents[1]  # server/src
    markdown_dir = base_dir / "markdown"
    return markdown_dir / safe_filename(company_name).upper() / date_str
 
 
def _load_markdown_article_files(company_date_folder: Path, max_articles: int = 5) -> List[Path]:
    if not company_date_folder.exists():
        return []
    article_files = [
        path for path in sorted(company_date_folder.glob("*.md"))
        if path.name.lower() != "summary.md"
    ]
    return article_files[:max_articles]
 
 
def _load_markdown_contents_from_files(article_files: List[Path]) -> Optional[str]:
    if not article_files:
        return None
    contents = []
    for path in article_files:
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                contents.append(f"---\nFile: {path.name}\n---\n{text}")
        except Exception:
            continue
    return "\n\n".join(contents) if contents else None
 
 
def _fetch_and_markdown_one_article(
    company_name: str,
    title: str,
    raw_url: str,
    published: str = "",
    decode_interval: int = 1,
) -> Tuple[str, str]:
    """
    Resolve Google News redirect URLs to the publisher page, then extract markdown.
    Validates that the URL is from a trusted source.
    Returns (publisher_url, markdown_document).
    """
    publisher_url = _resolve_publisher_url(raw_url)

    if any(bad in publisher_url for bad in BLACKLIST):
        raise ValueError(f"Publisher URL {publisher_url} is blacklisted")

    if not is_trusted_source_url(
        publisher_url, get_company_domains(company_name)
    ):
        raise ValueError(f"Publisher URL {publisher_url} is not from a trusted news source")

    body = _scrape_url_to_markdown(
        publisher_url,
        title,
        company_name,
        published,
    )
    return publisher_url, body
 
 
class NewsScraperService:
    """Service to scrape articles and create summaries."""
 
    @staticmethod
    async def scrape_articles_to_markdown(
        company_name: str,
        articles: List[dict],
        max_articles: int = 5,
        date_str: Optional[str] = None,
    ) -> Path:
        """Scrape up to max_articles and save them as markdown in the date folder."""
        company_date_folder = _get_company_date_folder_path(company_name, date_str)
        company_date_folder.mkdir(parents=True, exist_ok=True)
 
        successful_count = 0
        for article_idx, article in enumerate(articles, start=1):
            if successful_count >= max_articles:
                break
 
            title = article.get("title", "Untitled")
            url = article.get("url", "")
            try:
                if not url or not url.strip():
                    raise ValueError("Empty article URL from RSS")
 
                publisher_url, markdown_content = await asyncio.to_thread(
                    _fetch_and_markdown_one_article,
                    company_name,
                    title,
                    url.strip(),
                    article.get("published", ""),
                    1,
                )

                file_path = _article_markdown_path(
                    company_date_folder,
                    successful_count + 1,
                    title,
                    publisher_url,
                )
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
 
                successful_count += 1
            except Exception as e:
                # Ignore individual article failures for runtime scraping.
                print(f"[WARN] Skipping article for {company_name}: {str(e)}")
                continue
 
        return company_date_folder
 
    @staticmethod
    def load_markdown_contents(
        company_name: str,
        date_str: Optional[str] = None,
        max_articles: int = 5,
    ) -> Optional[str]:
        company_date_folder = _get_company_date_folder_path(company_name, date_str)
        article_files = _load_markdown_article_files(company_date_folder, max_articles=max_articles)
        return _load_markdown_contents_from_files(article_files)
 
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
        company_date_folder = markdown_dir / f"{safe_filename(company_name).upper()}" / today
        company_date_folder.mkdir(parents=True, exist_ok=True)
 
        markdown_files = []
        all_content = ""
        
        # Limit to 10 successfully scraped articles (trusted sources only)
        max_successful_articles = 10
        successful_count = 0

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
                    article.get("published", ""),
                    1,
                )

                file_path = _article_markdown_path(
                    company_date_folder, article_idx, title, publisher_url
                )
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)

                markdown_files.append(file_path)
                all_content += markdown_content + "\n\n" + "=" * 80 + "\n\n"
                successful_count += 1

                await websocket.send_json({
                    "idx": idx,
                    "company_name": company_name,
                    "article_idx": article_idx,
                    "publisher_url": publisher_url,
                    "saved_path": str(file_path.name),
                    "status": "saved"
                })

                # Stop after 10 successful scrapes (trusted source articles)
                if successful_count >= max_successful_articles:
                    await websocket.send_json({
                        "idx": idx,
                        "company_name": company_name,
                        "status": "reached_limit",
                        "message": f"Reached limit of {max_successful_articles} trusted source articles"
                    })
                    break
 
            except Exception as e:
                error_msg = str(e)
                # Provide more helpful error messages for common issues
                if "401" in error_msg or "403" in error_msg:
                    error_msg = f"Access denied (401/403) - site may require subscription: {url}"
                elif "503" in error_msg:
                    error_msg = "Service temporarily unavailable - will retry on next run"
                elif "timeout" in error_msg.lower():
                    error_msg = "Request timed out - will try next article"
                
                await websocket.send_json({
                    "idx": idx,
                    "company_name": company_name,
                    "article_idx": article_idx,
                    "rss_url": url,
                    "error": error_msg,
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
 