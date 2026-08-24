import pytest

from xvi.adapters.source.xhs_web.adapter import (
    FILTER_ELEMENT_GROUPS,
    FILTER_ELEMENT_HEADINGS,
    FILTER_GROUPS,
    normalize_filter_settings,
)


def test_filter_settings_are_group_scoped_and_defaulted() -> None:
    settings = normalize_filter_settings({"note_type": "image_text", "publish_time": "one_day"})
    assert settings == {
        "sort_by": "general",
        "note_type": "image_text",
        "publish_time": "one_day",
        "search_scope": "all",
    }
    assert FILTER_GROUPS["note_type"] == {"all": "不限", "image_text": "图文"}


def test_video_is_rejected_before_browser_click() -> None:
    with pytest.raises(ValueError, match="FILTER_INVALID_OPTION"):
        normalize_filter_settings({"note_type": "video"})


def test_unknown_group_is_rejected() -> None:
    with pytest.raises(ValueError, match="FILTER_UNKNOWN_GROUP"):
        normalize_filter_settings({"sort": "latest"})


def test_filter_element_catalog_contains_all_visible_groups_and_options() -> None:
    assert FILTER_ELEMENT_HEADINGS == {
        "sort_by": "排序依据",
        "note_type": "笔记类型",
        "publish_time": "发布时间",
        "search_scope": "搜索范围",
        "location_distance": "位置距离",
    }
    assert FILTER_ELEMENT_GROUPS["note_type"] == {
        "all": "不限",
        "video": "视频",
        "image_text": "图文",
    }
    assert FILTER_ELEMENT_GROUPS["location_distance"] == {
        "all": "不限",
        "same_city": "同城",
        "nearby": "附近",
    }
    assert sum(len(options) for options in FILTER_ELEMENT_GROUPS.values()) == 19
    assert "video" not in FILTER_GROUPS["note_type"]
    assert "location_distance" not in FILTER_GROUPS
