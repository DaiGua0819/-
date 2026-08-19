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
    missing_ids = static_id_selectors.difference(parser.ids)
    assert missing_ids == set()


def test_library_ui_exposes_time_saving_review_controls() -> None:
    static_root = Path(__file__).parents[1] / "apps" / "api" / "static"
    html = (static_root / "index.html").read_text(encoding="utf-8")
    script = (static_root / "library.js").read_text(encoding="utf-8")

    assert "tag-search-input" in html
    assert "sort-select" in html
    assert "mobile-filter-button" in html
    assert "data-batch-review" in script
    assert "data-review-status" in script
    assert "撤销" in script
    assert "IntersectionObserver" in script
