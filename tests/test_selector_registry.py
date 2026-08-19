from pathlib import Path

import pytest

from xvi.browser.selector_registry import SelectorRegistry
from xvi.domain.errors import SelectorDriftError


@pytest.mark.asyncio
async def test_selector_registry_detects_missing_required_selector() -> None:
    from playwright.async_api import async_playwright

    registry = SelectorRegistry(Path("config.yml"))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content("<html><body></body></html>")
        with pytest.raises(SelectorDriftError):
            await registry.first_visible(page, "search_input")
        await browser.close()
