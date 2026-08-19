from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from xvi.domain.enums import CaptureMode, SourceAccessMode


class Settings(BaseSettings):
    """应用配置和启动安全门禁。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "dev"
    log_level: str = "INFO"

    source_access_mode: SourceAccessMode = SourceAccessMode.DISABLED
    capture_mode: CaptureMode = CaptureMode.VISIBLE_DOWNLOAD_OR_RENDERED
    allow_visible_download: bool = True
    allow_network_extraction: bool = False
    allow_social_write_actions: bool = False
    allow_stealth: bool = False
    allow_captcha_bypass: bool = False
    allow_cookie_export: bool = False
    allow_raw_image_persistence: bool = False
    authorization_reference: str | None = None

    browser_headless: bool = True
    browser_profile_root: Path = Path("/data/profiles")
    browser_artifact_root: Path = Path("/data/artifacts")
    browser_asset_root: Path = Path("/data/assets")
    browser_max_results: int = Field(default=30, ge=1, le=200)
    browser_max_scrolls: int = Field(default=5, ge=0, le=50)
    browser_max_frames_per_note: int = Field(default=30, ge=1, le=100)
    browser_step_timeout_seconds: int = Field(default=30, ge=1, le=300)
    browser_max_run_seconds: int = Field(default=900, ge=30, le=7200)
    selector_config_path: Path = Path("configs/selectors/xhs_web.yaml")

    query_source_mode: str = "feishu_cli"
    feishu_base_url: str = ""
    feishu_cli_bin: str = "lark-cli"
    feishu_identity: str = "user"
    feishu_query_limit: int = Field(default=200, ge=1, le=200)

    vision_provider_mode: str = "disabled"
    raw_asset_ttl_hours: int = Field(default=24, ge=1, le=168)
    failure_screenshot_ttl_days: int = Field(default=14, ge=1, le=90)
    trace_ttl_days: int = Field(default=7, ge=1, le=30)

    # 素材库索引只读取既有 Artifact；默认与图片资产处于同一持久化根目录。
    library_db_path: Path | None = None
    library_qualification_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    library_default_page_size: int = Field(default=24, ge=1, le=100)
    library_max_page_size: int = Field(default=60, ge=1, le=200)

    @property
    def resolved_library_db_path(self) -> Path:
        return self.library_db_path or self.resolved_browser_asset_root.parent / "library.sqlite3"

    @property
    def resolved_browser_asset_root(self) -> Path:
        return self._workspace_fallback(self.browser_asset_root, Path(".data/assets"))

    @property
    def resolved_browser_artifact_root(self) -> Path:
        return self._workspace_fallback(self.browser_artifact_root, Path(".data/artifacts"))

    @staticmethod
    def _workspace_fallback(configured_path: Path, workspace_path: Path) -> Path:
        """Docker 保留 /data；Windows 本地 .env 若沿用 Docker 路径则回退到 .data。"""
        if configured_path.exists() or not workspace_path.exists():
            return configured_path
        return workspace_path

    @model_validator(mode="after")
    def validate_security(self) -> Self:
        forbidden = {
            "ALLOW_NETWORK_EXTRACTION": self.allow_network_extraction,
            "ALLOW_SOCIAL_WRITE_ACTIONS": self.allow_social_write_actions,
            "ALLOW_STEALTH": self.allow_stealth,
            "ALLOW_CAPTCHA_BYPASS": self.allow_captcha_bypass,
            "ALLOW_COOKIE_EXPORT": self.allow_cookie_export,
        }
        enabled = [name for name, value in forbidden.items() if value]
        if enabled:
            raise ValueError(f"禁止的安全开关不能启用: {', '.join(enabled)}")

        if self.source_access_mode == SourceAccessMode.AUTHORIZED_BROWSER:
            if not self.authorization_reference:
                raise ValueError("authorized_browser 必须配置 authorization_reference")
            if (
                not self.allow_visible_download
                and self.capture_mode == CaptureMode.VISIBLE_DOWNLOAD_OR_RENDERED
            ):
                raise ValueError("visible_download_or_rendered 模式必须允许可见下载或改用截图模式")

        if (
            self.capture_mode == CaptureMode.VISIBLE_DOWNLOAD_OR_RENDERED
            and not self.allow_visible_download
        ):
            raise ValueError("visible_download_or_rendered 模式要求 allow_visible_download=true")

        return self


settings = Settings()
