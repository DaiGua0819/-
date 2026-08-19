from collections.abc import AsyncIterator
from typing import Protocol

from playwright.async_api import Page

from xvi.domain.models import AssetMetadata, NoteSnapshot, SearchQuery, SearchResult, SessionProbe


class SourceAdapter(Protocol):
    async def ensure_session(self, page: Page) -> SessionProbe: ...

    async def search(self, page: Page, query: SearchQuery) -> list[SearchResult]: ...

    async def open_note(self, page: Page, result: SearchResult) -> NoteSnapshot: ...

    async def iter_rendered_frames(
        self,
        page: Page,
        note: NoteSnapshot,
    ) -> AsyncIterator[AssetMetadata]: ...

    async def close_note(self, page: Page) -> None: ...
