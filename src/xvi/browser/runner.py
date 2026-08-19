import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from playwright.async_api import async_playwright

from xvi.adapters.source.fixture.adapter import FixtureSourceAdapter
from xvi.adapters.source.fixture.html import FIXTURE_HTML
from xvi.browser.selector_registry import SelectorRegistry
from xvi.capture.frame_store import FrameStore
from xvi.capture.manifest import ArtifactWriter
from xvi.domain.models import AssetMetadata, NoteSnapshot, RunResult, SearchQuery


async def run_fixture_capture(
    *,
    selector_path: Path,
    asset_root: Path,
    artifact_root: Path,
    query_text: str,
) -> RunResult:
    run_id = uuid4()
    registry = SelectorRegistry(selector_path)
    frame_store = FrameStore(asset_root)
    artifact = ArtifactWriter(artifact_root, run_id)
    adapter = FixtureSourceAdapter(registry, frame_store)
    query = SearchQuery(text=query_text)
    artifact.write_manifest(
        {
            "run_id": str(run_id),
            "operation": "fixture_capture",
            "selector_version": registry.version,
            "started_at": datetime.now(UTC).isoformat(),
            "source_access_mode": "disabled",
        }
    )
    artifact.append_step("launch_fixture_browser", "started")

    assets: list[AssetMetadata] = []
    notes: list[NoteSnapshot] = []
    candidates = []
    capture_complete = False
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(accept_downloads=True)
        await page.set_content(FIXTURE_HTML)
        artifact.append_step("launch_fixture_browser", "done")
        session = await adapter.ensure_session(page)
        artifact.append_step("ensure_session", "done", session_status=session.status.value)
        candidates = await adapter.search(page, query)
        artifact.append_step("collect_results", "done", count=len(candidates))
        if candidates:
            note = await adapter.open_note(page, candidates[0])
            notes.append(note)
            artifact.append_step("open_note", "done", title=note.title)
            async for asset in adapter.iter_rendered_frames(page, note):
                assets.append(asset)
                artifact.append_step(
                    "capture_frame",
                    "done",
                    asset_id=str(asset.asset_id),
                    source_index=asset.source_index,
                    capture_method=asset.capture_method.value,
                    sha256=asset.sha256,
                    search_keyword=asset.search_keyword,
                    author_id=asset.author_id,
                    published_at=asset.published_at,
                    is_requirement_met=asset.is_requirement_met,
                    requirement_reason=asset.requirement_reason,
                    is_duplicate=asset.is_duplicate,
                    duplicate_of_asset_id=asset.duplicate_of_asset_id,
                )
            capture_complete = True
            await adapter.close_note(page)
        await browser.close()

    result = RunResult(
        run_id=run_id,
        query=query,
        candidates=candidates,
        notes=notes,
        assets=assets,
        capture_complete=capture_complete,
    )
    artifact.write_result(result.model_dump(mode="json"))
    artifact.append_step("complete", "done", asset_count=len(assets))
    return result


def run_fixture_sync(
    *,
    selector_path: Path,
    asset_root: Path,
    artifact_root: Path,
    query_text: str,
) -> RunResult:
    return asyncio.run(
        run_fixture_capture(
            selector_path=selector_path,
            asset_root=asset_root,
            artifact_root=artifact_root,
            query_text=query_text,
        )
    )
