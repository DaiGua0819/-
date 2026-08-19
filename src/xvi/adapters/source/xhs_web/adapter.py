import re
import time
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.async_api import Locator, Page

from xvi.browser.carousel import capture_carousel
from xvi.browser.selector_registry import SelectorRegistry
from xvi.capture.frame_store import FrameStore
from xvi.domain.enums import SessionStatus
from xvi.domain.errors import CaptureIncompleteError
from xvi.domain.models import AssetMetadata, NoteSnapshot, SearchQuery, SearchResult, SessionProbe

NOTE_MEDIA_IMAGE = "image"
NOTE_MEDIA_VIDEO = "video"
_SEARCH_RESULTS_PATH = "/search_result"
_SEARCH_RESULT_NOTE_PATTERN = re.compile(r"^/search_result/([^/]+)$")
_PAGINATION_TEXT_PATTERN = re.compile(r"^\s*(\d{1,3})\s*/\s*(\d{1,3})\s*$")
_ALLOWED_HOSTS = {"www.xiaohongshu.com"}


class XhsWebAdapter:
    """仅通过网页可见控件访问来源的适配器。"""

    def __init__(
        self,
        registry: SelectorRegistry,
        frame_store: FrameStore,
        *,
        max_frames: int = 30,
        timeout_ms: int = 30_000,
    ) -> None:
        self.registry = registry
        self.frame_store = frame_store
        self.max_frames = max_frames
        self.timeout_ms = timeout_ms

    async def ensure_session(self, page: Page) -> SessionProbe:
        login_marker = await self.registry.maybe_visible(page, "login_required")
        if login_marker is not None:
            return SessionProbe(
                status=SessionStatus.AUTH_REQUIRED,
                current_url=page.url,
                page_title=await page.title(),
            )
        authenticated_marker = await self.registry.maybe_visible(page, "authenticated_marker")
        status = (
            SessionStatus.AUTHENTICATED
            if authenticated_marker is not None
            else SessionStatus.UNKNOWN
        )
        return SessionProbe(
            status=status,
            current_url=page.url,
            page_title=await page.title(),
        )

    async def search(self, page: Page, query: SearchQuery) -> list[SearchResult]:
        search_input = await self.registry.wait_for_visible(
            page,
            "search_input",
            timeout_ms=self.timeout_ms,
        )
        if search_input is None:
            raise CaptureIncompleteError("搜索输入框不可见，未执行搜索")
        await search_input.fill(query.text)
        await page.keyboard.press("Enter")

        await self.ensure_search_context(page, query)
        result_card = await self.registry.wait_for_visible(
            page,
            "result_card",
            timeout_ms=self.timeout_ms,
        )
        if result_card is None:
            raise CaptureIncompleteError("搜索结果卡片不可见，禁止从推荐主页收集候选")

        # 等待搜索结果完成首轮渲染，避免读取上一次查询的残留卡片。
        await page.wait_for_timeout(800)
        seen_note_ids: set[str] = set()
        return await self.collect_visible_results(page, query, seen_note_ids, rank_start=1)

    async def ensure_search_context(
        self,
        page: Page,
        query: SearchQuery,
        *,
        expected_url: str | None = None,
    ) -> None:
        """确认父页面始终是当前关键词的搜索结果页。"""

        deadline = time.monotonic() + self.timeout_ms / 1000
        while time.monotonic() < deadline:
            current_url = normalize_source_url(page.url)
            path = urlsplit(current_url).path.rstrip("/") or "/"
            search_input = await self.registry.maybe_visible(page, "search_input")
            input_matches = False
            if search_input is not None:
                try:
                    input_matches = (await search_input.input_value()).strip() == query.text.strip()
                except Exception:
                    input_matches = False

            if path == _SEARCH_RESULTS_PATH and input_matches:
                if expected_url is not None and current_url != normalize_source_url(expected_url):
                    raise CaptureIncompleteError("搜索结果页 URL 发生变化，已停止后续采集")
                return
            await page.wait_for_timeout(100)

        raise CaptureIncompleteError(
            f"当前页面不是关键词“{query.text}”的搜索结果页，禁止继续采集",
        )

    async def collect_visible_results(
        self,
        page: Page,
        query: SearchQuery,
        seen_note_ids: set[str],
        *,
        rank_start: int,
    ) -> list[SearchResult]:
        """只收集当前搜索结果页中可见且路径合法的笔记链接。"""

        cards = await self.registry.all_visible(page, "result_card")
        results: list[SearchResult] = []
        for card in cards:
            href = await card.get_attribute("href")
            if not href:
                continue
            normalized = normalize_source_url(urljoin(page.url, href))
            note_id = extract_search_result_note_id(normalized)
            if note_id is None or note_id in seen_note_ids:
                continue
            seen_note_ids.add(note_id)
            title = (await card.inner_text()).strip() or None
            results.append(
                SearchResult(
                    source_url=normalized,
                    normalized_url=normalized,
                    visible_title=title,
                    search_keyword=query.text,
                    result_rank=rank_start + len(results),
                )
            )
        return results

    async def load_more_results(
        self,
        page: Page,
        query: SearchQuery,
        seen_note_ids: set[str],
        *,
        rank_start: int,
        expected_url: str,
    ) -> list[SearchResult]:
        """向下滚动搜索结果页并返回新出现的去重候选。"""

        await self.ensure_search_context(page, query, expected_url=expected_url)
        await page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        await page.mouse.wheel(0, 1600)
        await page.wait_for_timeout(1200)
        await self.ensure_search_context(page, query, expected_url=expected_url)
        return await self.collect_visible_results(
            page,
            query,
            seen_note_ids,
            rank_start=rank_start,
        )

    async def open_note(self, page: Page, result: SearchResult) -> NoteSnapshot:
        expected_note_id = extract_search_result_note_id(result.normalized_url)
        if expected_note_id is None:
            raise CaptureIncompleteError("候选链接不是搜索结果笔记，已拒绝打开")

        await page.goto(
            result.normalized_url,
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        container = await self.registry.wait_for_visible(
            page,
            "note_container",
            timeout_ms=self.timeout_ms,
        )
        if container is None:
            raise CaptureIncompleteError("笔记详情区域不可见")

        final_note_id = extract_note_id_from_detail_url(page.url)
        if final_note_id != expected_note_id:
            raise CaptureIncompleteError(
                f"笔记详情跳转异常：期望 {expected_note_id}，实际 {final_note_id or page.url}",
            )

        note_text = (await container.inner_text()).strip()
        title = note_text[:500] or None
        author_link = await _first_visible(
            container.locator("a.author[href*='/user/profile/'], a[href*='/user/profile/']"),
        )
        author_name_element = await _first_visible(container.locator("span.username"))
        author_id = None
        author_name = None
        if author_link is not None:
            author_href = await author_link.get_attribute("href")
            author_id = extract_author_id(page.url, author_href)
        if author_name_element is not None:
            author_name = (await author_name_element.inner_text()).strip() or None
        pagination = await self.registry.maybe_visible(page, "carousel_pagination")
        pagination_text = await pagination.inner_text() if pagination is not None else ""
        return NoteSnapshot(
            source_url=result.normalized_url,
            title=title,
            search_keyword=result.search_keyword,
            author_id=author_id,
            author_name=author_name,
            published_at=extract_published_at(note_text),
            expected_image_count=extract_expected_image_count(pagination_text),
        )

    async def detect_note_media(self, page: Page) -> str:
        """图片优先；同时存在图片和 video 的 Live 图按图片处理。"""

        deadline = time.monotonic() + self.timeout_ms / 1000
        video_seen = False
        while time.monotonic() < deadline:
            image = await self.registry.maybe_visible(page, "carousel_viewport")
            if image is not None:
                return NOTE_MEDIA_IMAGE
            video = await self.registry.maybe_visible(page, "note_video")
            video_seen = video_seen or video is not None
            await page.wait_for_timeout(250)
        if video_seen:
            return NOTE_MEDIA_VIDEO
        raise CaptureIncompleteError("无法识别笔记为图片或视频类型")

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
            max_frames=self.max_frames,
            timeout_ms=self.timeout_ms,
        ):
            yield asset

    async def close_note(self, page: Page) -> None:
        # 保留给旧 Runner 使用；真实批量采集使用独立子 Page 并直接关闭，不依赖历史返回。
        await page.go_back(wait_until="domcontentloaded")


async def _first_visible(locator: Locator) -> Locator | None:
    for index in range(await locator.count()):
        current = locator.nth(index)
        if await current.is_visible():
            return current
    return None


def extract_search_result_note_id(url: str) -> str | None:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_HOSTS
        or port not in {None, 443}
    ):
        return None
    path = parsed.path.rstrip("/")
    match = _SEARCH_RESULT_NOTE_PATTERN.fullmatch(path)
    return match.group(1) if match else None


def extract_note_id_from_detail_url(url: str) -> str | None:
    return extract_search_result_note_id(url)


def normalize_source_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query, ""))


_PUBLISHED_AT_LINE_PATTERN = re.compile(
    r"^(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}-\d{1,2})"
    r"(?:\s+[\u4e00-\u9fff]{1,8})?$"
)


def extract_author_id(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    path_parts = [part for part in urlsplit(urljoin(base_url, href)).path.split("/") if part]
    try:
        profile_index = path_parts.index("profile")
    except ValueError:
        return None
    if profile_index + 1 >= len(path_parts):
        return None
    return path_parts[profile_index + 1] or None


def extract_published_at(note_text: str) -> str | None:
    for raw_line in note_text.splitlines():
        line = raw_line.strip()
        if _PUBLISHED_AT_LINE_PATTERN.fullmatch(line):
            return line
    return None


def extract_expected_image_count(pagination_text: str) -> int | None:
    match = _PAGINATION_TEXT_PATTERN.fullmatch(pagination_text)
    if match is None:
        return None
    current = int(match.group(1))
    total = int(match.group(2))
    return total if 1 <= current <= total else None
