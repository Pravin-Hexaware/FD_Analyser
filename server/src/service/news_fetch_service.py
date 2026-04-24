"""
Service to orchestrate news fetching for companies.
Delegates scraping and summarization to dedicated services.
"""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from service.news_scraper_service import NewsScraperService
from service.news_service import NewsService


async def fetch_and_save_news_for_company(company_name: str, scrip_code: str, websocket, idx):
    """
    Main orchestrator: fetch news using NewsService, then scrape and summarize.
    """
    try:
        await websocket.send_json({
            "idx": idx,
            "company_name": company_name,
            "scrip_code": scrip_code,
            "status": "fetching_articles"
        })

        # Fetch article URLs using NewsService
        news_data = NewsService.get_company_news(company_name, max_results=10)
        articles = news_data.get("articles", [])

        if not articles:
            await websocket.send_json({
                "idx": idx,
                "company_name": company_name,
                "status": "no_articles_found"
            })
            return

        # Convert news_data format to articles format for scraper
        articles_for_scraping = [
            {"title": article.get("title", ""), "url": article.get("link", "")}
            for article in articles
        ]

        # Scrape and summarize
        await websocket.send_json({
            "idx": idx,
            "company_name": company_name,
            "article_count": len(articles_for_scraping),
            "status": "starting_scrape"
        })

        summary_folder = await NewsScraperService.scrape_and_summarize_articles(
            company_name, articles_for_scraping, websocket, idx
        )

        await websocket.send_json({
            "idx": idx,
            "company_name": company_name,
            "summary_folder": str(summary_folder),
            "status": "completed"
        })

    except Exception as e:
        await websocket.send_json({
            "idx": idx,
            "company_name": company_name,
            "error": str(e),
            "status": "failed"
        })
