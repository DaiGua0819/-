import re
import time
from collections.abc import AsyncIterator, Mapping
from datetime import datetime, timedelta, timezone
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
_SEARCH_RESULTS_PATHS = {"/search_result", "/search_result_ai"}
_NOTE_PATH_PATTERN = re.compile(r"^/(?:search_result|explore)/([^/]+)$")
_PUBLISHED_AT_LINE_PATTERN = re.compile(
    r"^(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}-\d{1,2})(?:\s+[\u4e00-\u9fff]{1,8})?$"
)
_PAGINATION_TEXT_PATTERN = re.compile(r"^\s*(\d{1,3})\s*/\s*(\d{1,3})\s*$")
_ALLOWED_HOSTS = {"www.xiaohongshu.com"}
_SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


FILTER_ELEMENT_GROUPS: dict[str, dict[str, str]] = {
    "sort_by": {
        "general": "综合",
        "latest": "最新",
        "most_liked": "最多点赞",
        "most_commented": "最多评论",
        "most_favorited": "最多收藏",
    },
    "note_type": {"all": "不限", "video": "视频", "image_text": "图文"},
    "publish_time": {
        "all": "不限",
        "one_day": "一天内",
        "one_week": "一周内",
        "half_year": "半年内",
    },
    "search_scope": {
        "all": "不限",
        "seen": "已看过",
        "unseen": "未看过",
        "followed": "已关注",
    },
    "location_distance": {
        "all": "不限",
        "same_city": "同城",
        "nearby": "附近",
    },
}
FILTER_ELEMENT_HEADINGS = {
    "sort_by": "排序依据",
    "note_type": "笔记类型",
    "publish_time": "发布时间",
    "search_scope": "搜索范围",
    "location_distance": "位置距离",
}

# 产品筛选设置仍然只开放原有四组；视频只做 DOM 发现，不允许被程序选择。
FILTER_GROUPS: dict[str, dict[str, str]] = {
    "sort_by": FILTER_ELEMENT_GROUPS["sort_by"],
    "note_type": {"all": "不限", "image_text": "图文"},
    "publish_time": FILTER_ELEMENT_GROUPS["publish_time"],
    "search_scope": FILTER_ELEMENT_GROUPS["search_scope"],
}
FILTER_HEADINGS = {key: FILTER_ELEMENT_HEADINGS[key] for key in FILTER_GROUPS}
FILTER_DEFAULTS = {key: next(iter(options)) for key, options in FILTER_GROUPS.items()}


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
        await self.open_search_results(page, query)
        seen_note_ids: set[str] = set()
        return await self.collect_visible_results(page, query, seen_note_ids, rank_start=1)

    async def open_search_results(self, page: Page, query: SearchQuery) -> None:
        """打开并等待一次默认搜索结果；不读取详情、不写入候选数据。"""

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

    async def collect_original_card_links(self, page: Page) -> list[dict[str, str | None]]:
        """只读取结果卡片的原始 href；禁止进入详情页。"""

        cards = await self.registry.all_visible(page, "result_card")
        links: list[dict[str, str | None]] = []
        seen_note_ids: set[str] = set()
        for card in cards:
            scope = await _card_scope(card)
            href = await _first_note_href(card, scope, page.url)
            if not href:
                continue
            normalized = normalize_source_url(urljoin(page.url, href))
            note_id = extract_search_result_note_id(normalized)
            if note_id is None or note_id in seen_note_ids:
                continue
            seen_note_ids.add(note_id)
            text = (await scope.inner_text()).strip() or None
            links.append({"note_id": note_id, "href": normalized, "text": text})
        return links

    async def apply_search_filters(
        self,
        page: Page,
        settings: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        """在当前搜索结果页选择四组筛选，并逐组校验选中状态。

        所有选项都按“分组标题 -> 选项精确文本”定位，避免多个“不限”互相串组。
        返回值只包含筛选验收信息和卡片原始链接，不打开详情页。
        """

        normalized = normalize_filter_settings(settings)
        before_links = await self.collect_original_card_links(page)
        filter_button = await self._filter_button(page)
        if filter_button is None:
            raise CaptureIncompleteError("FILTER_BUTTON_MISSING: 搜索结果页没有可见的筛选按钮")
        await filter_button.click()
        await page.wait_for_timeout(250)

        applied: dict[str, dict[str, object]] = {}
        for group_key in FILTER_HEADINGS:
            # 个别页面版本在点击选项后会重绘弹层；重绘后重新获取弹层和分组，
            # 不复用旧 Locator，避免元素漂移到下一组。
            panel = await self._filter_panel(page)
            if panel is None:
                await self._reopen_filter_panel(page)
                panel = await self._filter_panel(page)
            if panel is None:
                raise CaptureIncompleteError(
                    f"FILTER_PANEL_MISSING: 无法定位筛选面板（{group_key}）",
                )
            label = FILTER_GROUPS[group_key][normalized[group_key]]
            group = await _find_filter_group(
                panel,
                FILTER_HEADINGS[group_key],
                tuple(FILTER_GROUPS[group_key].values()),
            )
            if group is None:
                raise CaptureIncompleteError(
                    f"FILTER_GROUP_MISSING: 无法定位筛选分组 {FILTER_HEADINGS[group_key]}",
                )
            option = await _find_exact_visible_text(group, label)
            if option is None:
                raise CaptureIncompleteError(
                    f"FILTER_OPTION_MISSING: {FILTER_HEADINGS[group_key]} / {label}",
                )
            await option.click()
            await page.wait_for_timeout(180)
            if not await _is_selected_option(option, label):
                raise CaptureIncompleteError(
                    "FILTER_OPTION_NOT_SELECTED: "
                    f"{FILTER_HEADINGS[group_key]} / {label}（疑似选择漂移）",
                )
            applied[group_key] = {
                "value": normalized[group_key],
                "label": label,
                "selected": True,
            }

        # 点击完最后一组后，面板可能自动关闭，也可能保持打开；两种版本都等待
        # 结果列表重新渲染。筛选命中 0 条是合法结果，不能误报为按钮漂移。
        await page.wait_for_timeout(900)
        result_card = await self.registry.maybe_visible(page, "result_card")
        result_state = "loaded" if result_card is not None else "empty"
        if result_card is None:
            # 给前端最后一次异步重绘机会；没有卡片时保留空结果状态。
            await page.wait_for_timeout(1100)
            result_card = await self.registry.maybe_visible(page, "result_card")
            if result_card is not None:
                result_state = "loaded"
        after_links = await self.collect_original_card_links(page) if result_card else []
        return {
            "filters": normalized,
            "applied": applied,
            "before_count": len(before_links),
            "after_count": len(after_links),
            "result_state": result_state,
            "before_links": before_links,
            "after_links": after_links,
            "details_opened": False,
            "assets_captured": False,
        }

    async def extract_filter_elements(
        self,
        page: Page,
        *,
        include_outer_html: bool = False,
    ) -> dict[str, object]:
        """悬停打开筛选浮层，并按分组提取全部可见筛选 DOM。"""

        filter_button = await self._filter_button(page)
        if filter_button is None:
            raise CaptureIncompleteError("FILTER_BUTTON_MISSING: 搜索结果页没有可见的筛选按钮")

        await filter_button.hover()
        panel = await self._wait_filter_panel(page, tuple(FILTER_ELEMENT_HEADINGS.values()))
        if panel is None:
            raise CaptureIncompleteError(
                "FILTER_PANEL_HOVER_FAILED: 悬停筛选按钮后没有找到包含五个分组的可见浮层",
            )

        groups: list[dict[str, object]] = []
        missing: list[str] = []
        extracted_option_count = 0
        for group_key, heading in FILTER_ELEMENT_HEADINGS.items():
            expected_options = tuple(FILTER_ELEMENT_GROUPS[group_key].values())
            group = await _find_filter_group(panel, heading, expected_options)
            if group is None:
                missing.append(heading)
                groups.append(
                    {
                        "key": group_key,
                        "heading": heading,
                        "found": False,
                        "expected_options": list(expected_options),
                        "options": [],
                    }
                )
                continue

            options: list[dict[str, object]] = []
            for value, label in FILTER_ELEMENT_GROUPS[group_key].items():
                option = await _find_exact_visible_text(group, label)
                if option is None:
                    missing.append(f"{heading}/{label}")
                    options.append(
                        {
                            "value": value,
                            "label": label,
                            "found": False,
                            "product_selectable": value in FILTER_GROUPS.get(group_key, {}),
                        }
                    )
                    continue
                extracted_option_count += 1
                options.append(
                    {
                        "value": value,
                        "label": label,
                        "found": True,
                        "selected": await _is_selected_option(option, label),
                        "product_selectable": value in FILTER_GROUPS.get(group_key, {}),
                        "dom": await _filter_element_dom(
                            option,
                            include_outer_html=include_outer_html,
                        ),
                    }
                )
            groups.append(
                {
                    "key": group_key,
                    "heading": heading,
                    "found": True,
                    "expected_options": list(expected_options),
                    "options": options,
                    "dom": await _filter_element_dom(group, include_outer_html=False),
                }
            )

        expected_option_count = sum(len(options) for options in FILTER_ELEMENT_GROUPS.values())
        return {
            "hover_opened": True,
            "panel_found": True,
            "all_expected_present": not missing,
            "expected_group_count": len(FILTER_ELEMENT_GROUPS),
            "extracted_group_count": sum(bool(group["found"]) for group in groups),
            "expected_option_count": expected_option_count,
            "extracted_option_count": extracted_option_count,
            "missing": missing,
            "groups": groups,
            "panel_dom": await _filter_element_dom(panel, include_outer_html=False),
            "screenshot_ocr_used": False,
            "details_opened": False,
            "cards_collected": False,
        }

    async def _filter_button(self, page: Page) -> Locator | None:
        configured = await self.registry.maybe_visible(page, "filter_button")
        if configured is not None:
            return configured
        candidates = page.get_by_text(re.compile(r"^筛选$|^已筛选$"))
        for index in range(await candidates.count()):
            current = candidates.nth(index)
            if await current.is_visible():
                return current
        return None

    async def _filter_panel(
        self,
        page: Page,
        headings: tuple[str, ...] | None = None,
    ) -> Locator | None:
        # 使用 Playwright 文本过滤器先缩小候选集合，避免遍历页面上数千个 div
        # 并逐个调用 inner_text 导致超时；全部标题同时命中才算筛选面板。
        candidates = page.locator("div")
        for heading in headings or tuple(FILTER_HEADINGS.values()):
            candidates = candidates.filter(has_text=heading)
        matches: list[tuple[int, Locator]] = []
        for index in range(await candidates.count()):
            current = candidates.nth(index)
            if not await current.is_visible():
                continue
            text = (await current.inner_text()).strip()
            if len(text) <= 2400:
                matches.append((len(text), current))
        return min(matches, key=lambda item: item[0])[1] if matches else None

    async def _wait_filter_panel(
        self,
        page: Page,
        headings: tuple[str, ...],
    ) -> Locator | None:
        deadline = time.monotonic() + min(self.timeout_ms / 1000, 5)
        while time.monotonic() < deadline:
            panel = await self._filter_panel(page, headings)
            if panel is not None:
                return panel
            await page.wait_for_timeout(100)
        return None

    async def _reopen_filter_panel(self, page: Page) -> None:
        button = await self._filter_button(page)
        if button is not None:
            await button.click()
            await page.wait_for_timeout(250)

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

            if path in _SEARCH_RESULTS_PATHS and input_matches:
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
            scope = await _card_scope(card)
            href = await _first_note_href(card, scope, page.url)
            if not href:
                continue
            normalized = normalize_source_url(urljoin(page.url, href))
            note_id = extract_search_result_note_id(normalized)
            if note_id is None or note_id in seen_note_ids:
                continue
            seen_note_ids.add(note_id)
            author_id, author_name, publish_hint = await _card_author_meta(scope, page.url)
            title = (await scope.inner_text()).strip() or None
            results.append(
                SearchResult(
                    source_url=normalized,
                    normalized_url=normalized,
                    canonical_url=canonical_note_url(note_id),
                    platform_note_id=note_id,
                    visible_title=title,
                    visible_publish_hint=publish_hint,
                    author_id=author_id,
                    author_name=author_name,
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
        expected_note_id = result.platform_note_id or extract_search_result_note_id(
            result.normalized_url
        )
        if expected_note_id is None:
            raise CaptureIncompleteError("CARD_NOTE_ID_MISSING: 候选链接中没有平台笔记ID")
        if not result.author_id:
            raise CaptureIncompleteError("CARD_AUTHOR_ID_MISSING: 搜索卡片没有作者ID")
        if not result.visible_publish_hint:
            raise CaptureIncompleteError("CARD_PUBLISHED_AT_MISSING: 搜索卡片没有发布时间")

        await page.goto(
            result.normalized_url,
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        await page.wait_for_timeout(800)
        if is_blocked_note_url(page.url):
            raise CaptureIncompleteError(
                f"NOTE_ACCESS_BLOCKED_300031: 原始卡片链接当前无法浏览：{page.url}"
            )
        container = await self.registry.wait_for_visible(
            page,
            "note_container",
            timeout_ms=self.timeout_ms,
        )
        if container is None:
            raise CaptureIncompleteError("DETAIL_OPEN_FAILED: 笔记详情区域不可见")

        final_note_id = extract_note_id_from_detail_url(page.url)
        if final_note_id != expected_note_id:
            raise CaptureIncompleteError(
                f"NOTE_ID_MISMATCH: 期望 {expected_note_id}，实际 {final_note_id or page.url}",
            )

        author_link = await _first_visible(
            container.locator("a.author[href*='/user/profile/'], a[href*='/user/profile/']"),
        )
        author_id = None
        if author_link is not None:
            author_href = await author_link.get_attribute("href")
            author_id = extract_author_id(page.url, author_href)
        if not author_id:
            raise CaptureIncompleteError("DETAIL_AUTHOR_ID_MISSING: 详情页没有作者ID")
        if result.author_id != author_id:
            raise CaptureIncompleteError(
                f"AUTHOR_ID_MISMATCH: 卡片作者 {result.author_id}，详情页作者 {author_id}",
            )

        author_name_element = await _first_visible(container.locator("span.username"))
        author_name = (
            (await author_name_element.inner_text()).strip()
            if author_name_element is not None
            else result.author_name
        ) or None

        title_locator = await self.registry.maybe_visible(page, "note_title")
        title = (await title_locator.inner_text()).strip() if title_locator is not None else None
        if not title:
            raise CaptureIncompleteError("TITLE_MISSING: 详情页标题节点为空")

        body_locator = await self.registry.maybe_visible(page, "note_body")
        body_text = (await body_locator.inner_text()).strip() if body_locator is not None else None
        tag_locators = await self.registry.all_visible(page, "note_tag")
        native_tags = []
        for locator in tag_locators:
            value = (await locator.inner_text()).strip()
            if value and value not in native_tags:
                native_tags.append(value)
        edited_locator = await self.registry.maybe_visible(page, "note_edited_at")
        edited_at_raw = (
            (await edited_locator.inner_text()).strip() if edited_locator is not None else None
        )
        note_text = (await container.inner_text()).strip()
        pagination = await self.registry.maybe_visible(page, "carousel_pagination")
        pagination_text = await pagination.inner_text() if pagination is not None else ""
        published_raw = result.visible_publish_hint
        published_date = normalize_published_at(published_raw)
        return NoteSnapshot(
            source_url=result.source_url,
            canonical_url=result.canonical_url or canonical_note_url(expected_note_id),
            platform_note_id=expected_note_id,
            title=title,
            body_text=body_text,
            native_tags=native_tags,
            search_keyword=result.search_keyword,
            author_id=author_id,
            author_name=author_name,
            published_at=published_date,
            published_at_raw=published_raw,
            published_at_utc=None,
            edited_at_raw=edited_at_raw or extract_edited_at(note_text),
            expected_image_count=extract_expected_image_count(pagination_text),
        )

    async def detect_note_media(self, page: Page) -> str:
        """检测到任意视频元素即跳过整篇笔记。"""

        deadline = time.monotonic() + min(self.timeout_ms / 1000, 5)
        image_seen_at: float | None = None
        while time.monotonic() < deadline:
            video = await self.registry.maybe_visible(page, "note_video")
            if video is not None:
                return NOTE_MEDIA_VIDEO
            if (
                image_seen_at is None
                and await self.registry.maybe_visible(page, "carousel_viewport") is not None
            ):
                image_seen_at = time.monotonic()
            if image_seen_at is not None and time.monotonic() - image_seen_at >= 0.8:
                return NOTE_MEDIA_IMAGE
            await page.wait_for_timeout(250)
        if image_seen_at is not None:
            return NOTE_MEDIA_IMAGE
        raise CaptureIncompleteError("PAGE_STRUCTURE_CHANGED: 无法识别笔记媒体类型")

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


def normalize_filter_settings(settings: Mapping[str, str] | None) -> dict[str, str]:
    """校验并补齐四组选项；拒绝视频，防止调用方绕过前端误选视频。"""

    values = dict(FILTER_DEFAULTS)
    if settings:
        for key, value in settings.items():
            if key not in FILTER_GROUPS:
                raise ValueError(f"FILTER_UNKNOWN_GROUP: {key}")
            if value not in FILTER_GROUPS[key]:
                raise ValueError(f"FILTER_INVALID_OPTION: {key}={value}")
            values[key] = value
    return values


async def _find_filter_group(
    panel: Locator,
    heading: str,
    options: tuple[str, ...],
) -> Locator | None:
    headings = panel.get_by_text(heading, exact=True)
    for index in range(await headings.count()):
        current = headings.nth(index)
        if not await current.is_visible():
            continue
        ancestor = current
        for _ in range(6):
            text = (await ancestor.inner_text()).strip()
            if len(text) <= 900 and all(option in text for option in options):
                return ancestor
            ancestor = ancestor.locator("xpath=..")
    return None


async def _find_exact_visible_text(scope: Locator, text: str) -> Locator | None:
    candidates = scope.get_by_text(text, exact=True)
    found: list[Locator] = []
    for index in range(await candidates.count()):
        current = candidates.nth(index)
        if not await current.is_visible() or (await current.inner_text()).strip() != text:
            continue
        is_real_node = bool(
            await current.evaluate(
                r"""
                el => {
                  let node = el;
                  for (let depth = 0; node && depth < 3; depth += 1, node = node.parentElement) {
                    const opacity = Number(window.getComputedStyle(node).opacity || 1);
                    if (node.getAttribute('aria-hidden') === 'true' ||
                        node.hasAttribute('data-hp-kind') || opacity <= 0.001) {
                      return false;
                    }
                  }
                  return true;
                }
                """
            )
        )
        if is_real_node:
            found.append(current)
    return found[-1] if found else None


async def _is_selected_option(option: Locator, label: str) -> bool:
    return bool(
        await option.evaluate(
            r"""
            (el, expected) => {
              let node = el;
              for (let depth = 0; node && depth < 4; depth += 1, node = node.parentElement) {
                const className = typeof node.className === 'string' ? node.className : '';
                const ariaSelected = node.getAttribute('aria-selected');
                const ariaChecked = node.getAttribute('aria-checked');
                const dataSelected = node.getAttribute('data-selected');
                if (/\b(active|selected|checked|current)\b/i.test(className) ||
                    ariaSelected === 'true' || ariaChecked === 'true' || dataSelected === 'true') {
                  return true;
                }
              }
              return false;
            }
            """,
            label,
        )
    )


async def _filter_element_dom(
    element: Locator,
    *,
    include_outer_html: bool = True,
) -> dict[str, object]:
    result: object = await element.evaluate(
        r"""
        (el, includeOuterHtml) => {
          const attributes = Object.fromEntries(
            Array.from(el.attributes).map(attribute => [attribute.name, attribute.value])
          );
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return {
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || el.textContent || '').trim(),
            attributes,
            child_count: el.children.length,
            visible: rect.width > 0 && rect.height > 0 &&
              style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity || 1) > 0,
            outer_html: includeOuterHtml ? el.outerHTML : null,
          };
        }
        """,
        include_outer_html,
    )
    if not isinstance(result, dict):
        raise CaptureIncompleteError("FILTER_DOM_INVALID: 筛选节点 DOM 序列化结果不是对象")
    return {str(key): value for key, value in result.items()}


async def _card_scope(card: Locator) -> Locator:
    """将结果链接提升到包含作者和时间的同一张卡片作用域。"""

    scope = card
    for _ in range(5):
        if await scope.locator(
            "a.author[href*='/user/profile/'], a[href*='/user/profile/']"
        ).count():
            return scope
        scope = scope.locator("xpath=..")
    return card


async def _first_note_href(card: Locator, scope: Locator, base_url: str) -> str | None:
    hrefs: list[str] = []
    for root in (card, scope):
        direct_href = await root.get_attribute("href")
        if direct_href:
            hrefs.append(direct_href)
        links = root.locator("a[href*='/explore/'], a[href*='/search_result/']")
        for index in range(await links.count()):
            href = await links.nth(index).get_attribute("href")
            if href:
                hrefs.append(href)
    return select_original_note_href(hrefs, base_url)


def select_original_note_href(hrefs: list[str], base_url: str) -> str | None:
    """保留卡片原始 href，并优先选择带完整小红书访问上下文的链接。"""

    best_href: str | None = None
    best_priority = (-1, -1, -1)
    for href in dict.fromkeys(hrefs):
        absolute_url = urljoin(base_url, href)
        if extract_search_result_note_id(absolute_url) is None:
            continue
        query = urlsplit(absolute_url).query
        priority = (
            int("xsec_token=" in query),
            int("xsec_source=" in query),
            int(bool(query)),
        )
        if priority > best_priority:
            best_href = href
            best_priority = priority
    return best_href


async def _card_author_meta(
    scope: Locator,
    base_url: str,
) -> tuple[str | None, str | None, str | None]:
    author_link = await _first_visible(
        scope.locator("a.author[href*='/user/profile/'], a[href*='/user/profile/']")
    )
    if author_link is None:
        return None, None, None
    href = await author_link.get_attribute("href")
    author_id = extract_author_id(base_url, href)
    wrapper = await _first_visible(author_link.locator("div.name-time-wrapper"))
    if wrapper is not None:
        name_element = await _first_visible(wrapper.locator("div.name"))
        time_element = await _first_visible(wrapper.locator("div.time"))
        author_name = (
            (await name_element.inner_text()).strip() if name_element is not None else None
        ) or None
        publish_hint = (
            (await time_element.inner_text()).strip() if time_element is not None else None
        ) or None
        if author_name is not None or publish_hint is not None:
            return author_id, author_name, publish_hint

    # 页面灰度变更时保留宽松回退；回退失败也不会把容器外的其他卡片信息混进来。
    text = (await author_link.inner_text()).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    publish_hint = extract_published_at(text) or _extract_relative_publish_hint(text)
    author_name = lines[0] if lines else None
    return author_id, author_name, publish_hint


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
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS or port not in {None, 443}:
        return None
    path = parsed.path.rstrip("/")
    match = _NOTE_PATH_PATTERN.fullmatch(path)
    return match.group(1) if match else None


def extract_note_id_from_detail_url(url: str) -> str | None:
    return extract_search_result_note_id(url)


def canonical_note_url(note_id: str) -> str:
    return f"https://www.xiaohongshu.com/explore/{note_id}"


def is_blocked_note_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.path.rstrip("/") == "/404" and "error_code=300031" in parsed.query


def normalize_source_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query, ""))


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


def _extract_relative_publish_hint(text: str) -> str | None:
    match = re.search(
        r"(?:今天|昨天|前天)(?:\s+\d{1,2}:\d{2})?|\d+天前|\d+小时前|\d+分钟前|刚刚",
        text,
    )
    return match.group(0) if match else None


def extract_edited_at(note_text: str) -> str | None:
    for raw_line in note_text.splitlines():
        line = raw_line.strip()
        if "编辑于" in line:
            return line
    return None


def normalize_published_at(
    raw: str | None,
    *,
    collected_at: datetime | None = None,
) -> str | None:
    """把卡片时间原文换算为采集当时固定的 Asia/Shanghai 日期。"""

    if not raw:
        return None
    now = collected_at or datetime.now(_SHANGHAI_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_SHANGHAI_TZ)
    else:
        now = now.astimezone(_SHANGHAI_TZ)
    value = raw.strip()
    if value == "刚刚" or re.fullmatch(r"今天(?:\s+\d{1,2}:\d{2})?", value):
        return now.date().isoformat()
    relative = re.fullmatch(r"(\d+)小时前", value)
    if relative:
        return (now - timedelta(hours=int(relative.group(1)))).date().isoformat()
    relative = re.fullmatch(r"(\d+)分钟前", value)
    if relative:
        return (now - timedelta(minutes=int(relative.group(1)))).date().isoformat()
    relative = re.fullmatch(r"(\d+)天前", value)
    if relative:
        return (now - timedelta(days=int(relative.group(1)))).date().isoformat()
    if re.fullmatch(r"昨天(?:\s+\d{1,2}:\d{2})?", value):
        return (now - timedelta(days=1)).date().isoformat()
    if re.fullmatch(r"前天(?:\s+\d{1,2}:\d{2})?", value):
        return (now - timedelta(days=2)).date().isoformat()
    match = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})|(\d{1,2})-(\d{1,2})", value)
    if match is None:
        return None
    if match.group(1):
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    else:
        year, month, day = now.year, int(match.group(4)), int(match.group(5))
        candidate = datetime(year, month, day, tzinfo=_SHANGHAI_TZ)
        if candidate > now + timedelta(days=1):
            year -= 1
    try:
        return datetime(year, month, day, tzinfo=_SHANGHAI_TZ).date().isoformat()
    except ValueError:
        return None


def extract_expected_image_count(pagination_text: str) -> int | None:
    match = _PAGINATION_TEXT_PATTERN.fullmatch(pagination_text)
    if match is None:
        return None
    current = int(match.group(1))
    total = int(match.group(2))
    return total if 1 <= current <= total else None
