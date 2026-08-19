import re
import time
from pathlib import Path
from typing import Any

import yaml
from playwright.async_api import Locator, Page

from xvi.domain.errors import SelectorDriftError


class SelectorRegistry:
    """从版本化 YAML 中解析可见页面控件。"""

    def __init__(self, config_path: Path) -> None:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.version = str(payload["version"])
        self.selectors: dict[str, dict[str, Any]] = payload["selectors"]

    def _candidate_locator(self, page: Page, candidate: dict[str, Any]) -> Locator:
        if "role" in candidate:
            name_regex = candidate.get("name_regex")
            name = re.compile(name_regex, re.IGNORECASE) if name_regex else None
            return page.get_by_role(candidate["role"], name=name)
        if "placeholder_regex" in candidate:
            return page.get_by_placeholder(
                re.compile(candidate["placeholder_regex"], re.IGNORECASE),
            )
        if "text_regex" in candidate:
            return page.get_by_text(
                re.compile(candidate["text_regex"], re.IGNORECASE),
            )
        if "css" in candidate:
            return page.locator(candidate["css"])
        raise ValueError(f"不支持的选择器候选: {candidate}")

    async def maybe_visible(self, page: Page, key: str) -> Locator | None:
        config = self.selectors[key]
        for candidate in config["candidates"]:
            locator = self._candidate_locator(page, candidate)
            count = await locator.count()
            for index in range(count):
                current = locator.nth(index)
                if await current.is_visible():
                    return current
        return None

    async def wait_for_visible(
        self,
        page: Page,
        key: str,
        *,
        timeout_ms: int,
    ) -> Locator | None:
        """等待指定控件在页面上可见，超时后返回 None。"""
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            visible = await self.maybe_visible(page, key)
            if visible is not None:
                return visible

            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return None
            await page.wait_for_timeout(min(100, remaining_ms))

    async def first_visible(self, page: Page, key: str) -> Locator:
        locator = await self.maybe_visible(page, key)
        if locator is None:
            raise SelectorDriftError(key)
        return locator

    async def all_visible(self, page: Page, key: str) -> list[Locator]:
        config = self.selectors[key]
        visible: list[Locator] = []
        for candidate in config["candidates"]:
            locator = self._candidate_locator(page, candidate)
            count = await locator.count()
            for index in range(count):
                current = locator.nth(index)
                if await current.is_visible():
                    visible.append(current)
        if not visible and config.get("required", True):
            raise SelectorDriftError(key)
        return visible
