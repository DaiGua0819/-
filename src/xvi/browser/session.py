from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import BrowserContext, async_playwright


@asynccontextmanager
async def persistent_context(
    profile_dir: Path,
    *,
    headless: bool,
    timeout_ms: int,
) -> AsyncIterator[BrowserContext]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            accept_downloads=True,
        )
        context.set_default_timeout(timeout_ms)
        try:
            yield context
        finally:
            await context.close()
