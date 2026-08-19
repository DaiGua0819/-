from collections.abc import AsyncIterator

from playwright.async_api import Page

from xvi.browser.carousel import capture_carousel
from xvi.browser.selector_registry import SelectorRegistry
from xvi.capture.frame_store import FrameStore
from xvi.domain.enums import SessionStatus
from xvi.domain.models import AssetMetadata, NoteSnapshot, SearchQuery, SearchResult, SessionProbe


class FixtureSourceAdapter:
    """本地静态页面适配器，用于 Contract Test，不访问真实平台。"""

    def __init__(self, registry: SelectorRegistry, frame_store: FrameStore) -> None:
        self.registry = registry
        self.frame_store = frame_store

    async def ensure_session(self, page: Page) -> SessionProbe:
        marker = await self.registry.maybe_visible(page, "authenticated_marker")
        status = SessionStatus.AUTHENTICATED if marker is not None else SessionStatus.AUTH_REQUIRED
        return SessionProbe(status=status, current_url=page.url, page_title=await page.title())

    async def search(self, page: Page, query: SearchQuery) -> list[SearchResult]:
        search_input = await self.registry.first_visible(page, "search_input")
        await search_input.fill(query.text)
        cards = await self.registry.all_visible(page, "result_card")
        results: list[SearchResult] = []
        for rank, card in enumerate(cards, start=1):
            href = await card.get_attribute("href")
            if href is None:
                continue
            results.append(
                SearchResult(
                    source_url=href,
                    normalized_url=href,
                    visible_title=(await card.inner_text()).strip() or None,
                    search_keyword=query.text,
                    result_rank=rank,
                )
            )
        return results

    async def open_note(self, page: Page, result: SearchResult) -> NoteSnapshot:
        card = page.locator(f"[data-xvi-note-url='{result.normalized_url}']")
        await card.click()
        await self.registry.first_visible(page, "note_container")
        return NoteSnapshot(
            source_url=result.normalized_url,
            title=result.visible_title,
            search_keyword=result.search_keyword,
            expected_image_count=3,
        )

    async def iter_rendered_frames(
        self,
        page: Page,
        note: NoteSnapshot,
    ) -> AsyncIterator[AssetMetadata]:
        async for asset in capture_carousel(
            page,
            note,
            self.registry,
            self.frame_store,
            max_frames=10,
            timeout_ms=3_000,
        ):
            yield asset

    async def close_note(self, page: Page) -> None:
        close = await self.registry.maybe_visible(page, "note_close")
        if close is not None:
            await close.click()
