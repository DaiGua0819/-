from pathlib import Path

import pytest

from xvi.browser.runner import run_fixture_capture


@pytest.mark.asyncio
async def test_fixture_capture_saves_multiple_assets(tmp_path: Path) -> None:
    result = await run_fixture_capture(
        selector_path=Path("config.yml"),
        asset_root=tmp_path / "assets",
        artifact_root=tmp_path / "artifacts",
        query_text="Fixture 品牌 快闪",
    )
    assert len(result.candidates) == 1
    assert len(result.notes) == 1
    assert result.notes[0].source_url == result.candidates[0].normalized_url
    assert len(result.assets) == 3
    assert result.capture_complete is True
    assert {asset.capture_method.value for asset in result.assets} <= {
        "visible_download",
        "rendered_screenshot",
    }
    assert all(asset.path.exists() for asset in result.assets)
    assert all(asset.is_requirement_met is None for asset in result.assets)
    assert all(asset.requirement_reason is not None for asset in result.assets)
    run_dir = tmp_path / "artifacts" / str(result.run_id)
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "steps.jsonl").exists()
    assert (run_dir / "result.json").exists()
