from __future__ import annotations

from typing import Iterable, Optional


async def first_unique_visible_locator(page, candidates: Iterable[str]) -> Optional[str]:
    for selector in candidates:
        if not selector:
            continue
        locator = page.locator(selector)
        try:
            count = await locator.count()
        except Exception:
            continue
        visible_matches = 0
        for index in range(count):
            try:
                if await locator.nth(index).is_visible():
                    visible_matches += 1
            except Exception:
                continue
        if visible_matches == 1:
            return selector
    return None
