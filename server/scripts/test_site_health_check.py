#!/usr/bin/env python3
"""
Live BSE landing-grid health check only (no heal agent, no XBRL collection).

Uses project automation helpers against the real BSE results page.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FINBOT_HEAL_DISABLED", "1")
os.environ.setdefault("FINBOT_HEADLESS", "1")


async def main() -> None:
    from playwright.async_api import async_playwright
    from automation.results_portal import SiteHealth, WEBSITE_DOWN_DETAIL
    from services.batch_xbrl_finder import (
        check_bse_landing_site_health,
        create_browser_and_context,
    )

    async with async_playwright() as p:
        browser, ctx = await create_browser_and_context(p)
        try:
            health = await check_bse_landing_site_health(ctx)
        finally:
            try:
                await ctx.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass

    print(f"SiteHealth = {health.value}")
    if health == SiteHealth.UP:
        print("OK: BSE landing grid has records — collection/heal may proceed when needed.")
        return
    if health == SiteHealth.DOWN:
        print(f"DOWNTIME: {WEBSITE_DOWN_DETAIL}")
        print("OK: health check would halt Fetch Filings without starting heal.")
        return
    print("GRID_MISSING: default landing grid has no usable rows — continue to search/heal.")
    print("OK: health check would NOT treat this as downtime.")


if __name__ == "__main__":
    asyncio.run(main())
