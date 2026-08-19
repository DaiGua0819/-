import argparse
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from playwright.async_api import Page

from scripts.local_xhs_browser import execute_query
from xvi.adapters.source.xhs_web.adapter import XhsWebAdapter
from xvi.browser.selector_registry import SelectorRegistry
from xvi.domain.enums import CaptureMethod, SessionStatus
from xvi.domain.models import (
    AssetMetadata,
    NoteSnapshot,
    SearchQuery,
    SearchResult,
    SessionProbe,
)


class FakeAdapter:
    def __init__(self, candidates: list[SearchResult]) -> None:
        self.candidates = candidates
        self.opened_urls: list[str] = []
        self.closed_urls: list[str] = []

    async def ensure_session(self, page: Page) -> SessionProbe:
        return SessionProbe(status=SessionStatus.AUTHENTICATED, current_url=page.url)

    async def search(self, page: Page, query: SearchQuery) -> list[SearchResult]:
        return self.candidates

    async def open_note(self, page: Page, result: SearchResult) -> NoteSnapshot:
        self.opened_urls.append(result.normalized_url)
        return NoteSnapshot(
            source_url=result.normalized_url,
            title=result.visible_title,
            search_keyword=result.search_keyword,
            author_id=f"author-{result.result_rank}",
            author_name=f"作者-{result.result_rank}",
            published_at="07-24 上海",
        )

    async def iter_rendered_frames(
        self,
        page: Page,
        note: NoteSnapshot,
    ) -> AsyncIterator[AssetMetadata]:
        yield AssetMetadata(
            asset_id=uuid4(),
            note_id=note.note_id,
            source_index=0,
            capture_method=CaptureMethod.RENDERED_SCREENSHOT,
            path=Path(f"{note.note_id}.jpg"),
            width=640,
            height=480,
            mime_type="image/jpeg",
            sha256=f"sha-{note.source_url}",
            phash=f"phash-{note.source_url}",
            search_keyword=note.search_keyword,
            author_id=note.author_id,
            author_name=note.author_name,
            published_at=note.published_at,
        )

    async def close_note(self, page: Page) -> None:
        self.closed_urls.append(self.opened_urls[-1])


@pytest.mark.asyncio
async def test_execute_query_captures_all_candidates(tmp_path: Path) -> None:
    candidates = [
        SearchResult(
            source_url="https://example.test/note-1",
            normalized_url="https://example.test/note-1",
            visible_title="第一篇笔记",
            search_keyword="品牌 快闪",
            result_rank=1,
        ),
        SearchResult(
            source_url="https://example.test/note-2",
            normalized_url="https://example.test/note-2",
            visible_title="第二篇笔记",
            search_keyword="品牌 快闪",
            result_rank=2,
        ),
    ]
    adapter = FakeAdapter(candidates)
    page = cast(Page, SimpleNamespace(url="https://www.xiaohongshu.com/explore"))
    args = argparse.Namespace(
        artifact_root=tmp_path / "artifacts",
        profile_dir=tmp_path / "profile",
    )
    registry = SelectorRegistry(Path("config.yml"))

    exit_code, result = await execute_query(
        args=args,
        page=page,
        adapter=cast(XhsWebAdapter, adapter),
        registry=registry,
        query_text="品牌 快闪",
        authorization_reference="test-authorization",
        browser_backend="test",
    )

    assert exit_code == 0
    assert result.capture_complete is True
    assert result.error_code is None
    assert [note.source_url for note in result.notes] == [
        "https://example.test/note-1",
        "https://example.test/note-2",
    ]
    assert [asset.search_keyword for asset in result.assets] == ["品牌 快闪", "品牌 快闪"]
    assert [asset.author_id for asset in result.assets] == ["author-1", "author-2"]
    assert adapter.opened_urls == [
        "https://example.test/note-1",
        "https://example.test/note-2",
    ]
    assert adapter.closed_urls == adapter.opened_urls

    result_path = tmp_path / "artifacts" / str(result.run_id) / "result.json"
    result_data = result_path.read_text(encoding="utf-8")
    payload = json.loads(result_data)
    assert len(payload["assets"]) == 2
    assert len(payload["notes"]) == 2
    assert [note["source_url"] for note in payload["notes"]] == [
        "https://example.test/note-1",
        "https://example.test/note-2",
    ]
