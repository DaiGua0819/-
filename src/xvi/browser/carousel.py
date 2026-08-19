from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from xvi.browser.selector_registry import SelectorRegistry
from xvi.capture.frame_store import FrameStore
from xvi.capture.hashes import phash_bytes, sha256_bytes
from xvi.capture.requirement import assess_requirement
from xvi.domain.enums import CaptureMethod
from xvi.domain.errors import CaptureIncompleteError
from xvi.domain.models import AssetMetadata, NoteSnapshot


async def _stable_screenshot(viewport: Locator) -> bytes:
    first = await viewport.screenshot(type="jpeg", quality=92)
    second = await viewport.screenshot(type="jpeg", quality=92)
    if phash_bytes(first) != phash_bytes(second):
        second = await viewport.screenshot(type="jpeg", quality=92)
    return second


async def _visible_download(
    page: Page,
    registry: SelectorRegistry,
    viewport: Locator,
    timeout_ms: int,
) -> bytes | None:
    download_button = await registry.maybe_visible(page, "carousel_download")
    if download_button is None:
        return None
    try:
        async with page.expect_download(timeout=timeout_ms) as download_info:
            await download_button.click()
        download = await download_info.value
        path = await download.path()
        if path is None:
            return None
        return Path(path).read_bytes()
    except PlaywrightTimeoutError:
        return None


async def capture_carousel(
    page: Page,
    note: NoteSnapshot,
    registry: SelectorRegistry,
    frame_store: FrameStore,
    *,
    max_frames: int,
    timeout_ms: int,
) -> AsyncIterator[AssetMetadata]:
    """优先通过可见下载按钮获取文件，否则保存渲染区域截图。"""

    viewport = await registry.first_visible(page, "carousel_viewport")
    expected_count = note.expected_image_count
    if expected_count is not None and expected_count > max_frames:
        raise CaptureIncompleteError(
            f"笔记包含 {expected_count} 张图片，超过单篇上限 {max_frames}",
        )

    frame_limit = expected_count if expected_count is not None else max_frames
    seen_assets: dict[str, AssetMetadata] = {}
    is_requirement_met, requirement_reason = assess_requirement()

    for source_index in range(frame_limit):
        if not await viewport.is_visible():
            raise CaptureIncompleteError("轮播区域不再可见")

        downloaded = await _visible_download(page, registry, viewport, timeout_ms)
        data = downloaded if downloaded is not None else await _stable_screenshot(viewport)
        method = (
            CaptureMethod.VISIBLE_DOWNLOAD
            if downloaded is not None
            else CaptureMethod.RENDERED_SCREENSHOT
        )
        current_phash = phash_bytes(data)

        original_asset = seen_assets.get(current_phash)
        if original_asset is not None:
            yield original_asset.model_copy(
                update={
                    "asset_id": uuid4(),
                    "source_index": source_index,
                    "is_duplicate": True,
                    "duplicate_of_asset_id": original_asset.asset_id,
                }
            )
        else:
            asset = frame_store.save(
                asset_id=uuid4(),
                note_id=note.note_id,
                source_index=source_index,
                data=data,
                capture_method=method,
            ).model_copy(
                update={
                    "search_keyword": note.search_keyword,
                    "author_id": note.author_id,
                    "author_name": note.author_name,
                    "published_at": note.published_at,
                    "is_requirement_met": is_requirement_met,
                    "requirement_reason": requirement_reason,
                }
            )
            seen_assets[current_phash] = asset
            yield asset

        if expected_count is not None and source_index + 1 >= expected_count:
            return

        next_button = await registry.maybe_visible(page, "carousel_next")
        if next_button is None or await next_button.is_disabled():
            if expected_count is not None:
                raise CaptureIncompleteError(
                    f"笔记预计 {expected_count} 张图片，实际只采集 {source_index + 1} 张",
                )
            return

        previous_viewport_hash = sha256_bytes(
            await viewport.screenshot(type="jpeg", quality=70),
        )
        await next_button.click()
        try:
            await viewport.wait_for(state="visible", timeout=timeout_ms)
            changed = False
            for _ in range(20):
                candidate = await viewport.screenshot(type="jpeg", quality=70)
                if sha256_bytes(candidate) != previous_viewport_hash:
                    changed = True
                    break
                await page.wait_for_timeout(100)
            if not changed:
                raise CaptureIncompleteError("点击下一张后图片未发生变化")
        except PlaywrightTimeoutError as exc:
            raise CaptureIncompleteError("轮播下一张等待超时") from exc

    raise CaptureIncompleteError("达到轮播最大图片数，无法确认完整闭环")
