import json
from pathlib import Path
from typing import Annotated

import typer

from xvi.browser.runner import run_fixture_sync
from xvi.config import Settings
from xvi.integrations.feishu_cli import FeishuCliQuerySource

app = typer.Typer(help="XVI 授权浏览器图片采集 CLI")
config_app = typer.Typer(help="配置命令")
query_app = typer.Typer(help="查询规则命令")
fixture_app = typer.Typer(help="本地 Fixture 命令")
app.add_typer(config_app, name="config")
app.add_typer(query_app, name="query")
app.add_typer(fixture_app, name="fixture")


@config_app.command("validate")
def validate_config() -> None:
    """校验安全配置，不启动浏览器。"""
    config = Settings()
    typer.echo(
        json.dumps(
            {
                "ok": True,
                "source_access_mode": config.source_access_mode.value,
                "capture_mode": config.capture_mode.value,
                "allow_visible_download": config.allow_visible_download,
                "vision_provider_mode": config.vision_provider_mode,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@query_app.command("list")
def list_query_rules(limit: int = typer.Option(200, min=1, max=200)) -> None:
    """只读读取飞书 Base 中当前视图的查询规则。"""
    config = Settings()
    source = FeishuCliQuerySource(
        cli_bin=config.feishu_cli_bin,
        base_url=config.feishu_base_url,
        identity=config.feishu_identity,
    )
    rules = source.load_rules(limit=limit)
    typer.echo(json.dumps([rule.model_dump() for rule in rules], ensure_ascii=False, indent=2))


@fixture_app.command("capture")
def fixture_capture(
    query: Annotated[str, typer.Option(help="Fixture 查询词")] = "品牌 快闪",
    selector_path: Annotated[Path, typer.Option(exists=True)] = Path("config.yml"),
    asset_root: Annotated[Path, typer.Option()] = Path("./.data/assets"),
    artifact_root: Annotated[Path, typer.Option()] = Path("./.data/artifacts"),
) -> None:
    """执行本地 Fixture 的搜索、轮播和图片保存链路。"""
    result = run_fixture_sync(
        selector_path=selector_path,
        asset_root=asset_root,
        artifact_root=artifact_root,
        query_text=query,
    )
    typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
