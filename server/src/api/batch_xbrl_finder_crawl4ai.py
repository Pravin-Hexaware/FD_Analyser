#!/usr/bin/env python3
"""
Simplified XBRL link fetcher using Crawl4AI instead of complex Playwright logic.

Replaces the extensive Playwright-based batch_xbrl_finder.py with a cleaner,
more efficient implementation using Crawl4AI for web scraping.
"""

import asyncio
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator

from api.crawl4ai_wrapper import (
    GetXBRLRequest,
    GetXBRLResponse,
    BatchGetXBRLRequest,
    BatchItemResult,
    BatchGetXBRLResponse,
    fetch_xbrl_with_crawl4ai,
    fetch_multiple_xbrl_links,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/get-xbrl-link", response_model=GetXBRLResponse)
async def get_xbrl_link(request: GetXBRLRequest) -> GetXBRLResponse:
    """
    Fetch the first XBRL link for a company from BSE Corporate Results page.

    Args:
        request: GetXBRLRequest with company name or scrip code and preference

    Returns:
        GetXBRLResponse with XBRL URL, period, report type, and error info
    """
    start_time = datetime.now()

    try:
        url, period, report_type, attempts, error = await fetch_xbrl_with_crawl4ai(
            company=request.company.strip(),
            prefer=request.prefer.strip().lower(),
        )

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        return GetXBRLResponse(
            xbrl_url=url,
            period=period,
            error=error,
            attempts=attempts,
            duration_ms=duration_ms,
        )

    except Exception as e:
        logger.error(f"Error fetching XBRL link for '{request.company}': {e}", exc_info=True)
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        return GetXBRLResponse(
            xbrl_url=None,
            period=None,
            error=f"Internal error: {str(e)}",
            attempts=0,
            duration_ms=duration_ms,
        )


@router.post("/get-xbrl-links", response_model=BatchGetXBRLResponse)
async def get_xbrl_links(request: BatchGetXBRLRequest) -> BatchGetXBRLResponse:
    """
    Fetch XBRL links for multiple companies in parallel.

    Args:
        request: BatchGetXBRLRequest with list of companies and optional parallel setting

    Returns:
        BatchGetXBRLResponse with list of results
    """
    try:
        # Validate inputs
        if not request.companies or len(request.companies) == 0:
            raise HTTPException(
                status_code=400,
                detail="companies list cannot be empty",
            )

        if len(request.companies) > 100:
            raise HTTPException(
                status_code=400,
                detail="Maximum 100 companies per batch request",
            )

        max_parallel = min(request.parallel or 2, 6)
        prefer = request.prefer.strip().lower()

        logger.info(
            f"Fetching XBRL links for {len(request.companies)} companies "
            f"(parallel: {max_parallel}, prefer: {prefer})"
        )

        # Fetch all companies
        results = await fetch_multiple_xbrl_links(
            request.companies,
            prefer=prefer,
            max_parallel=max_parallel,
        )

        # Convert to response items
        items = []
        for company, url, period, report_type, attempts, error in results:
            items.append(
                BatchItemResult(
                    company=company,
                    xbrl_url=url,
                    period=period,
                    error=error,
                    attempts=attempts,
                    duration_ms=0,  # Individual timing not tracked in batch
                )
            )

        return BatchGetXBRLResponse(results=items)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching batch XBRL links: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}",
        )
