#!/usr/bin/env python3
"""Offline fixture tests for landing-grid SiteHealth (no network, no heal)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))


DOWN_HTML = """
<html><body>
<table id="ContentPlaceHolder1_gvData">
  <tbody>
    <tr><td colspan="6">No Record Found</td></tr>
  </tbody>
</table>
</body></html>
"""

UP_HTML = """
<html><body>
<table id="ContentPlaceHolder1_gvData">
  <tbody>
    <tr><th>Code</th><th>Name</th><th>Period</th></tr>
    <tr><td>500325</td><td>RELIANCE</td><td>DQ2025</td></tr>
    <tr><td>500325</td><td>RELIANCE</td><td>SQ2025</td></tr>
  </tbody>
</table>
</body></html>
"""

MISSING_HTML = """
<html><body><div>Financial Results</div><p>Something else</p></body></html>
"""

EMPTY_GRID_HTML = """
<html><body>
<table id="ContentPlaceHolder1_gvData"><tbody></tbody></table>
</body></html>
"""


async def _health_for(html: str):
    from playwright.async_api import async_playwright
    from automation.results_portal import ResultsPortal

    portal = ResultsPortal()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        health = await portal.check_landing_site_health(page)
        await browser.close()
        return health


async def main() -> None:
    from automation.results_portal import SiteHealth, is_site_down, is_site_up

    down = await _health_for(DOWN_HTML)
    up = await _health_for(UP_HTML)
    missing = await _health_for(MISSING_HTML)
    empty_grid = await _health_for(EMPTY_GRID_HTML)

    print(f"NO RECORDS   -> {down.value} is_down={is_site_down(down)}")
    print(f"UP fixture   -> {up.value} is_up={is_site_up(up)}")
    print(f"MISSING      -> {missing.value}")
    print(f"EMPTY GRID   -> {empty_grid.value}")

    assert down == SiteHealth.GRID_MISSING, down
    assert is_site_up(up), up
    assert missing == SiteHealth.GRID_MISSING, missing
    assert empty_grid == SiteHealth.GRID_MISSING, empty_grid
    print("OK: fixture SiteHealth classifications passed")


if __name__ == "__main__":
    asyncio.run(main())
