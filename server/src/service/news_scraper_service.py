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
from service.news_service import NewsService
from langchain_core.messages import HumanMessage
 
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
 
 
def safe_filename(value: str) -> str:
    """Convert string to safe filename."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value) or "article"
 
 
def _get_page_html(url: str) -> str:
    """Fetch HTML from URL with proper headers and SSL fallback."""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "Accept-Encoding": "gzip, deflate",
        "Referer": origin
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.SSLError:
        response = requests.get(url, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        return response.text
 
 
def _extract_markdown_trafilatura(html: str, page_url: str) -> Optional[str]:
    """Extract markdown using trafilatura (primary extraction method)."""
    text = trafilatura.extract(
        html,
        url=page_url,
        output_format="markdown",
        favor_precision=True,
        include_comments=False,
        include_tables=True,
        include_images=True,
        include_formatting=True,
        include_links=True,
        deduplicate=True,
    )
    if text:
        text = text.strip()
    if text and len(text) >= 80:
        return text
    return None
 
 
def _pick_content_root(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    """Find the main article content root element."""
    candidates = []
    selectors = (
        '[itemprop="articleBody"]',
        "article",
        ".article-content",
        ".article__content",
        ".article-body",
        ".article__body",
        ".story-content",
        ".post-content",
        ".story-body",
        "#article-body",
        '[role="main"]',
        "main",
    )
    for sel in selectors:
        if sel in ("article", "main"):
            found = soup.find(sel)
            nodes = [found] if found else []
        else:
            nodes = soup.select(sel)
        for node in nodes:
            text_len = len(node.get_text(strip=True))
            if text_len > 200:
                candidates.append((text_len, node))
    if candidates:
        return max(candidates, key=lambda x: x[0])[1]
    return (
        soup.find("article")
        or soup.body
        or soup.find("main")
        or (soup.html if soup.html else None)
    )
 
 
def _extract_markdown_from_pruned_soup(soup: BeautifulSoup) -> str:
    """Fallback extraction: use BeautifulSoup and markdownify."""
    content_root = _pick_content_root(soup)
    if not content_root:
        raise ValueError("No readable content found")
   
    # Remove noise tags
    for tag in content_root(["script", "style", "noscript", "iframe", "header", "footer", "nav"]):
        tag.decompose()
   
    markdown_body = md(str(content_root), heading_style="ATX")
    return markdown_body.strip()
 
 
def _resolve_publisher_url(google_or_any_url: str, decode_interval: Optional[int] = 1) -> str:
    """Resolve Google News redirect URLs to actual publisher URLs."""
    netloc = (urlparse(google_or_any_url).netloc or "").lower()
    if "news.google.com" in netloc:
        if decode_interval:
            time.sleep(decode_interval)
        result = gnewsdecoder(google_or_any_url, interval=0)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
        raise RuntimeError(result.get("message", "gnewsdecoder failed to resolve URL"))
    return google_or_any_url
 
 
def _scrape_url_to_markdown(publisher_url: str, title: str, company: str) -> str:
    """Scrape article from URL and convert to markdown."""
    html = _get_page_html(publisher_url)
   
    # Try trafilatura first
    markdown_body = _extract_markdown_trafilatura(html, publisher_url)
    if not markdown_body:
        # Fallback to BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        markdown_body = _extract_markdown_from_pruned_soup(soup)
   
    if len(markdown_body) < 80:
        raise ValueError("Extracted content too short; page may require JavaScript")
   
    header = f"""# {title}
 
**Company:** {company}  
**Source URL:** {publisher_url}  
**Fetched At:** {datetime.now().isoformat()}
 
---
 
"""
   
    return header + markdown_body
 
 
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
    Validates that the URL is from a trusted source.
    Returns (publisher_url, markdown_document).
    """
    publisher_url = _resolve_publisher_url(raw_url, decode_interval=decode_interval)
    
    # Validate the publisher URL is from a trusted source
    if not NewsService._is_trusted_source(publisher_url):
        raise ValueError(f"Publisher URL is not from a trusted source: {publisher_url}")
    
    body = _scrape_url_to_markdown(publisher_url, title, company_name)
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
                    separates_folder, article_idx, title, publisher_url
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
 