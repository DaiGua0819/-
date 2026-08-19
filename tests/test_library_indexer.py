import json
from pathlib import Path

from xvi.library import ArtifactIndexer, LibraryRepository


def test_indexer_persists_source_url_and_legacy_review(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    assets_root = tmp_path / "assets"
    note_id = "a3c11111-1111-1111-1111-111111111111"
    asset_id = "b4c22222-2222-2222-2222-222222222222"
    asset_path = assets_root / note_id / f"000-{asset_id}.jpg"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"fixture-image")
    run_dir = artifact_root / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"started_at": "2026-08-19T08:00:00+00:00", "source_access_mode": "manual_import"}
        ),
        encoding="utf-8",
    )
    source_url = "https://www.xiaohongshu.com/search_result/abc123?xsec_token=kept"
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "query": {"text": "fwee 圣水 快闪"},
                "capture_complete": True,
                "notes": [
                    {
                        "note_id": note_id,
                        "source_url": source_url,
                        "title": "fwee 快闪现场",
                        "search_keyword": "fwee 圣水 快闪",
                    }
                ],
                "assets": [
                    {
                        "asset_id": asset_id,
                        "note_id": note_id,
                        "source_index": 0,
                        "path": str(asset_path),
                        "width": 702,
                        "height": 936,
                        "mime_type": "image/jpeg",
                        "sha256": "sha",
                        "phash": "phash",
                        "capture_method": "rendered_screenshot",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "fwee-results-gallery.html").write_text(
        f"""<article class="card" data-status="yes"><img src="file:///tmp/assets/{note_id}/000-{asset_id}.jpg"><p>活动装置清晰可见。</p></article>""",
        encoding="utf-8",
    )
    repository = LibraryRepository(tmp_path / "library.sqlite3")
    repository.ensure_schema()
    report = ArtifactIndexer(
        repository, artifact_root=artifact_root, gallery_root=tmp_path
    ).index_all()

    assert report.run_count == 1
    assert report.asset_count == 1
    assert report.legacy_review_count == 1
    notes = repository.list_notes(
        query="fwee", tag="圣水", status=None, only_new=True, limit=10, offset=0
    )
    assert notes["total"] == 1
    note = notes["items"][0]
    assert note["source_url"] == source_url
    assert note["accepted_count"] == 1
    assert note["eligibility"] == "eligible"
    detail = repository.get_note(note["note_key"])
    assert detail is not None
    assert detail["assets"][0]["effective_review_status"] == "accepted"
    assert repository.get_asset_path(asset_id, asset_root=assets_root) == asset_path.resolve()

    assert repository.update_asset_review(
        asset_id=asset_id,
        status="rejected",
        reviewer="test-reviewer",
        reason="画面主体与活动无关",
    )
    rejected_detail = repository.get_note(note["note_key"])
    assert rejected_detail is not None
    assert rejected_detail["assets"][0]["effective_review_status"] == "rejected"
    assert rejected_detail["eligibility"] == "below_threshold"

    assert repository.update_delivery(
        note_key=note["note_key"],
        status="delivered",
    )
    assert (
        repository.list_notes(query=None, tag=None, status=None, only_new=True, limit=10, offset=0)[
            "total"
        ]
        == 0
    )
