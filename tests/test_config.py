import pytest
from pydantic import ValidationError

from xvi.config import Settings


def test_default_source_access_is_disabled() -> None:
    config = Settings(_env_file=None)
    assert config.source_access_mode.value == "disabled"
    assert config.allow_network_extraction is False
    assert config.allow_visible_download is True


def test_forbidden_security_switch_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, allow_stealth=True)


def test_authorized_browser_requires_reference() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, source_access_mode="authorized_browser")
