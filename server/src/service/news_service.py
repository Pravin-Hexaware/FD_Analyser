"""
News fetching service to get recent company news from multiple sources.
Uses feedparser for RSS feeds and simple web scraping.
"""
import json
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import re
from urllib.parse import urlparse

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False
    print("[WARN] feedparser not installed. News fetching will be limited.")



class NewsService:
    """Service to fetch and manage company news."""
    
    # Trusted news sources only
    TRUSTED_SOURCES = {
        "reuters.com",
        "bloomberg.com",
        "moneycontrol.com",
        "livemint.com",
        "economictimes.indiatimes.com",
        "timesofindia.indiatimes.com",
        "msn.com",
        "ndtvprofit.com",
        "manufacturingtodayindia.com",
        "fortuneindia.com",
        "newindianexpress.com",
        "economictimes.com",
        "businesstoday.in",
        "cnbctv18.com",
        "zeebiz.com",
        "marketsmojo.com",
        "indianchemicalnews.com",
        "scanx.trade",
        "whalesbook.com",
        "hdfcsky.com",
        "devdiscourse.com",
        "chinimandi.com",
        "unilever.com",
        "businessworld.in",
        "thehindubusinessline.com",
        "financialexpress.com",
        "business-standard.com"
    }
    
    # Keywords to identify company activities and changes or market-moving events
    ACTIVITY_KEYWORDS = [
        "layoff",
        "hiring",
        "resigns",
        "appointed",
        "acquisition",
        "merger",
        "partnership",
        "expansion",
        "shutdown",
        "lawsuit",
        "probe",
        "investigation",
        "regulatory",
        "protest",
        "launch",
        "facility",
        "office",
        "plant",
        "joint venture",
        "ipo",
        "dividend",
        "bonus",
        "restructure",
        "bankruptcy",
        "fraud",
        "recall",
        "contract",
        "deal",
        "investment",
        "sustainability",
        "esg",
        "earnings",
        "profit",
        "revenue",
        "growth",
        "margin",
        "stock",
        "share",
        "analyst",
        "results",
        "outlook",
        "guidance",
        "rating",
        "downgrade",
        "upgrade",
        "target",
        "price",
        "market",
        "forecast",
        "cashflow",
        "net income",
        "opex",
        "capex",
        "sale",
        "order",
        "contract",
        "acquisition",
        "funding",
        "joint venture"
    ]
    
    MAX_RETRIES = 2
    TIMEOUT = 10
    
    @staticmethod
    def _is_trusted_source(url: str) -> bool:
        """
        Check if a URL belongs to a trusted news source.
        
        Args:
            url: The URL to check
            
        Returns:
            True if the URL is from a trusted source, False otherwise
        """
        if not url:
            return False
        
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower().replace("www.", "")
            
            # Check if domain matches any trusted source
            for trusted in NewsService.TRUSTED_SOURCES:
                if domain == trusted or domain.endswith("." + trusted):
                    return True
            return False
        except Exception as e:
            print(f"[WARN] Error checking trusted source for URL {url}: {str(e)}")
            return False
    
    @staticmethod
    def get_company_news(
        company_name: str,
        max_results: int = 50,
        days_back: int = 30
    ) -> Dict[str, Any]:
        """
        Fetch recent news articles about a company.
        
        Args:
            company_name: Name of the company
            max_results: Maximum number of news articles to fetch
            days_back: Number of days in the past to search for news
            
        Returns:
            Dictionary containing:
            - articles: List of news articles with title, link, published date, summary
            - count: Number of articles found
            - source: Source of the news
            - last_updated: When the news was fetched
        """
        if not FEEDPARSER_AVAILABLE:
            return {
                "articles": [],
                "count": 0,
                "source": "google_news_rss",
                "error": "feedparser not installed. Please install feedparser: pip install feedparser",
                "last_updated": datetime.now().isoformat()
            }
        
        articles = []
        
        # Try Google News RSS first (activity keywords narrow results)
        try:
            google_articles = NewsService._fetch_google_news(company_name, max_results)
            articles.extend(google_articles)
            print(f"[INFO] Successfully fetched {len(google_articles)} articles for {company_name}")
        except Exception as e:
            print(f"[WARN] Failed to fetch Google News for {company_name}: {str(e)}")

        # Broad fallback: quoted company name only (many companies match nothing with the strict OR query)
        if not articles:
            try:
                fallback = NewsService._fetch_google_news(
                    company_name, max_results, simple_query=True
                )
                articles.extend(fallback)
                print(f"[INFO] Fallback RSS fetched {len(fallback)} articles for {company_name}")
            except Exception as e:
                print(f"[WARN] Fallback Google News failed for {company_name}: {str(e)}")
        
        # Remove duplicates by title (keep all sources, no trusted source filtering)
        seen_titles = set()
        unique_articles = []
        
        for article in articles:
            title = article.get("title", "").lower()
            
            # Skip if title is duplicate
            if title and title in seen_titles:
                continue
            
            # Add article without checking trusted source
            if title:
                seen_titles.add(title)
                unique_articles.append(article)
        
        # Limit to max_results
        unique_articles = unique_articles[:max_results]
        
        return {
            "articles": unique_articles,
            "count": len(unique_articles),
            "source": "google_news_rss",
            "company_name": company_name,
            "last_updated": datetime.now().isoformat(),
            "date_range": f"Last {days_back} days"
        }
    
    @staticmethod
    def _fetch_google_news(
        company_name: str,
        max_results: int = 10,
        simple_query: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetch news from Google News RSS feed.
        
        Args:
            company_name: Name of the company
            max_results: Maximum articles to return
            simple_query: If True, search only the quoted company name (broader matches).

        Returns:
            List of article dictionaries with title, link, published, and summary
        """
        articles = []
        
        if not FEEDPARSER_AVAILABLE:
            return articles
        
        if simple_query:
            query = f'"{company_name}"'
        else:
            keywords = " OR ".join(NewsService.ACTIVITY_KEYWORDS)
            query = f'"{company_name}" ({keywords})'
        
        encoded_query = urllib.parse.quote(query)
        
        rss_url = (
            f"https://news.google.com/rss/search?"
            f"q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
        )
        
        print(f"[DEBUG] Fetching news from Google News: {rss_url}")
        
        try:
            feed = feedparser.parse(rss_url)
            
            if not feed.entries:
                print(f"[DEBUG] No entries found in feed for {company_name}")
                return []
            
            print(f"[DEBUG] Found {len(feed.entries)} entries in feed for {company_name}")
            
            # Fetch more articles than max_results to account for filtering by trusted sources
            # We'll aim for 3x the max_results to ensure we have enough trusted sources
            fetch_limit = min(max_results * 3, len(feed.entries))
            
            for idx, entry in enumerate(feed.entries[:fetch_limit]):
                raw_url = None
                for link in entry.get("links", []) or []:
                    if link.get("rel") == "alternate" and link.get("href"):
                        raw_url = link["href"]
                        break
                if not raw_url:
                    raw_url = entry.get("link", "")
                
                # Don't filter by trusted sources here - we'll do it after resolving the actual publisher URL
                # Google News RSS returns redirect URLs, so we need to resolve them first

                article = {
                    "title": entry.get("title", ""),
                    "link": raw_url or "",
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", ""),
                    "source": "Google News",
                    "fetched_at": datetime.now().isoformat()
                }
                
                # Clean HTML from summary
                article["summary"] = NewsService._clean_html(article["summary"])
                
                articles.append(article)
                print(f"[DEBUG] Added article {idx + 1}: {article['title'][:50]}...")
        
        except Exception as e:
            print(f"[ERROR] Error parsing Google News feed: {str(e)}")
            import traceback
            traceback.print_exc()
        
        return articles
    
    @staticmethod
    def _clean_html(text: str) -> str:
        """Remove HTML tags from text."""
        if not text:
            return ""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities
        text = text.replace("&nbsp;", " ")
        text = text.replace("&quot;", '"')
        text = text.replace("&#39;", "'")
        text = text.replace("&amp;", "&")
        return text.strip()
    
    @staticmethod
    def format_news_for_llm(news_data: Dict[str, Any]) -> str:
        """
        Format news data into a readable string for LLM consumption.
        
        Args:
            news_data: Dictionary returned from get_company_news
            
        Returns:
            Formatted string with news articles
        """
        if not news_data.get("articles"):
            return f"No recent news found for {news_data.get('company_name', 'the company')}."
        
        formatted = f"\n## Recent News for {news_data.get('company_name', 'Company')}\n"
        formatted += f"(Last updated: {news_data.get('last_updated', 'N/A')}, {news_data.get('date_range', '')})\n\n"
        
        for idx, article in enumerate(news_data["articles"], 1):
            formatted += f"### Article {idx}\n"
            formatted += f"**Title:** {article.get('title', 'N/A')}\n"
            formatted += f"**Published:** {article.get('published', 'N/A')}\n"
            formatted += f"**Source:** {article.get('source', 'N/A')}\n"
            if article.get("summary"):
                formatted += f"**Summary:** {article['summary'][:200]}...\n" if len(article['summary']) > 200 else f"**Summary:** {article['summary']}\n"
            formatted += f"**Link:** {article.get('link', 'N/A')}\n\n"
        
        return formatted
    
    @staticmethod
    def extract_news_summary(news_data: Dict[str, Any]) -> str:
        """
        Extract a concise summary of news for inclusion in financial analysis.
        
        Args:
            news_data: Dictionary returned from get_company_news
            
        Returns:
            Concise summary of key news points
        """
        if not news_data.get("articles"):
            return f"No recent news available for {news_data.get('company_name')}."
        
        summary_points = []
        
        for article in news_data["articles"]:
            title = article.get("title", "")
            # Extract main keywords from title
            for keyword in NewsService.ACTIVITY_KEYWORDS:
                if keyword.lower() in title.lower():
                    summary_points.append(f"- {title}")
                    break
        
        if not summary_points:
            # If no keywords found, just use all titles
            summary_points = [f"- {article.get('title', '')}" for article in news_data["articles"][:5]]
        
        summary = f"**Recent News and Activities for {news_data.get('company_name')}:**\n"
        summary += "\n".join(summary_points[:5])
        
        return summary
