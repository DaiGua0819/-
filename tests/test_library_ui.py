import re
from html.parser import HTMLParser
from pathlib import Path


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.script_sources: list[str] = []
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if element_id := values.get("id"):
            self.ids.append(element_id)
        if tag == "script" and (source := values.get("src")):
            self.script_sources.append(source)
        if tag == "link" and values.get("rel") == "stylesheet" and (href := values.get("href")):
            self.stylesheets.append(href)


def test_library_ui_resources_and_selectors_stay_connected() -> None:
    static_root = Path(__file__).parents[1] / "apps" / "api" / "static"
    html = (static_root / "index.html").read_text(encoding="utf-8")
    script = (static_root / "library.js").read_text(encoding="utf-8")
    parser = _IdCollector()
    parser.feed(html)

    assert len(parser.ids) == len(set(parser.ids))
    assert "/static/library.js" in parser.script_sources
    assert "/static/ux.css" in parser.stylesheets

    static_id_selectors = set(re.findall(r'\$\("#([a-z0-9-]+)"\)', script))
    runtime_detail_ids = {"detail-media"}
    missing_ids = static_id_selectors.difference(parser.ids).difference(runtime_detail_ids)
    assert missing_ids == set()


def test_library_ui_exposes_time_saving_review_controls() -> None:
    static_root = Path(__file__).parents[1] / "apps" / "api" / "static"
    html = (static_root / "index.html").read_text(encoding="utf-8")
    script = (static_root / "library.js").read_text(encoding="utf-8")

    assert "tag-search-input" in html
    assert "sort-select" not in html
    assert "mobile-filter-button" not in html
    assert "data-batch-review" in script
    assert "data-review-status" in script
    assert "撤销" in script
    assert "IntersectionObserver" in script
    assert "reviewEvidence" in script
    assert "data-save-reason" in script
    assert "human_review_reason || null" in script
    assert "state.notes.length < state.total" in script
    assert "暂无 AI 判断说明" in script
    assert "reasonSaveTimers" in script
    assert "data-saved-reason" in script
    assert "flushPendingReasonSaves" in script
    assert "beforeunload" in script
    assert "700" in script


def test_library_ui_uses_cached_data_and_independent_detail_image_transitions() -> None:
    static_root = Path(__file__).parents[1] / "apps" / "api" / "static"
    script = (static_root / "library.js").read_text(encoding="utf-8")
    stylesheet = (static_root / "redbeauty.css").read_text(encoding="utf-8")

    assert "function setDetailImage" in script
    assert "preloadAdjacentAssets" in script
    assert "getNoteDetail" in script
    assert "NOTE_LIST_CACHE_LIMIT" in script
    assert "has-note-origin" in script
    assert "focus({ preventScroll: true })" in script
    assert "column-count" not in stylesheet
    assert "masonry-content-reveal" in stylesheet
    assert "note-dialog-fallback-close" in stylesheet
    assert "performance-lite" in stylesheet
