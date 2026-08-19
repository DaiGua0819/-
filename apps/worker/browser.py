from xvi.browser.runner import run_fixture_sync
from xvi.config import Settings

if __name__ == "__main__":
    settings = Settings()
    # 当前 Worker 仅执行一次本地 Fixture，用于验证浏览器采集链路。
    result = run_fixture_sync(
        selector_path=settings.selector_config_path,
        asset_root=settings.browser_asset_root,
        artifact_root=settings.browser_artifact_root,
        query_text="Fixture 品牌 快闪",
    )
    print(result.model_dump_json(indent=2))
