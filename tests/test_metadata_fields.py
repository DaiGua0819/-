from datetime import datetime, timedelta, timezone
from pathlib import Path

from xvi.adapters.source.xhs_web.adapter import (
    canonical_note_url,
    extract_author_id,
    extract_note_id_from_detail_url,
    extract_published_at,
    extract_search_result_note_id,
    normalize_published_at,
    select_original_note_href,
)
from xvi.library import LibraryRepository


def test_note_id_and_author_id_are_platform_specific() -> None:
    assert (
        extract_search_result_note_id(
            "https://www.xiaohongshu.com/search_result/abc123?xsec_token=kept"
        )
        == "abc123"
    )
    assert (
        extract_note_id_from_detail_url(
            "https://www.xiaohongshu.com/explore/abc123?xsec_token=kept"
        )
        == "abc123"
    )
    assert (
        extract_search_result_note_id("https://www.xiaohongshu.com/search_result_ai?keyword=brand")
        is None
    )
    assert canonical_note_url("abc123") == "https://www.xiaohongshu.com/explore/abc123"
    assert (
        extract_author_id(
            "https://www.xiaohongshu.com/explore/abc123",
            "/user/profile/author-789?xsec_token=kept",
        )
        == "author-789"
    )


def test_original_card_href_prefers_complete_xsec_context() -> None:
    base_url = "https://www.xiaohongshu.com/search_result_ai?keyword=test"
    secure_href = "/explore/note-1?xsec_token=token-value&xsec_source=pc_search"

    assert (
        select_original_note_href(
            ["/explore/note-1", secure_href],
            base_url,
        )
        == secure_href
    )


def test_publish_date_helpers_keep_card_date_and_normalize_absolute_date() -> None:
    assert extract_published_at("Echo\n07-22") == "07-22"
    assert extract_published_at("作者\n2026-08-07 上海") == "2026-08-07 上海"
    assert normalize_published_at("2026-08-07 上海") == "2026-08-07"


def test_relative_publish_dates_use_collection_time_and_shanghai_timezone() -> None:
    collected_at = datetime(2026, 8, 21, 0, 5, tzinfo=timezone(timedelta(hours=8)))

    assert normalize_published_at("13分钟前", collected_at=collected_at) == "2026-08-20"
    assert normalize_published_at("15小时前", collected_at=collected_at) == "2026-08-20"
    assert normalize_published_at("昨天", collected_at=collected_at) == "2026-08-20"
    assert normalize_published_at("昨天 16:58", collected_at=collected_at) == "2026-08-20"
    assert normalize_published_at("前天", collected_at=collected_at) == "2026-08-19"
    assert normalize_published_at("2天前", collected_at=collected_at) == "2026-08-19"
    assert normalize_published_at("刚刚", collected_at=collected_at) == "2026-08-21"


def test_repository_records_candidates_and_failures_without_touching_assets(tmp_path: Path) -> None:
    repository = LibraryRepository(tmp_path / "library.sqlite3")
    repository.ensure_schema()
    repository.upsert_candidate(
        {
            "observation_id": "run-1:note-1:1",
            "run_id": "run-1",
            "platform_note_id": "note-1",
            "source_url": "https://www.xiaohongshu.com/explore/note-1",
            "canonical_url": "https://www.xiaohongshu.com/explore/note-1",
            "query_text": "brand 快闪",
            "author_id": "author-1",
            "published_at_raw": "07-22",
            "result_rank": 1,
        }
    )
    repository.record_capture_failure(
        {
            "run_id": "run-1",
            "platform_note_id": "note-1",
            "stage": "capture_note",
            "error_code": "AUTHOR_ID_MISMATCH",
            "error_message": "卡片作者与详情页作者不一致",
            "retryable": 1,
        }
    )
    with repository.connection() as connection:
        candidate = connection.execute(
            "SELECT platform_note_id, author_id, published_at_raw FROM candidate_observations"
        ).fetchone()
        failure = connection.execute(
            "SELECT error_code, retryable FROM capture_failures"
        ).fetchone()
    assert dict(candidate) == {
        "platform_note_id": "note-1",
        "author_id": "author-1",
        "published_at_raw": "07-22",
    }
    assert dict(failure) == {"error_code": "AUTHOR_ID_MISMATCH", "retryable": 1}
    assert (
        repository.list_capture_failures(
            run_id="run-1", error_code="AUTHOR_ID_MISMATCH", limit=10, offset=0
        )["total"]
        == 1
    )
