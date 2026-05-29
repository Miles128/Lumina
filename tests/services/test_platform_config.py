"""Tests for platform configuration store."""

from pathlib import Path

from secretary.core.types import SourceKind
from secretary.services.platform_config import PlatformConfigStore


def test_platform_config_save_and_mask_password(tmp_path: Path) -> None:
    store = PlatformConfigStore(tmp_path / "platforms.json")
    store.update_section(
        SourceKind.EMAIL,
        {
            "imap_host": "imap.qq.com",
            "imap_port": 993,
            "imap_user": "me@qq.com",
            "imap_password": "secret",
        },
    )

    section = store.get_section(SourceKind.EMAIL)
    assert section["imap_user"] == "me@qq.com"

    masked = store.get_section(SourceKind.EMAIL)
    from secretary.services.platform_config import mask_secrets

    assert mask_secrets(masked)["imap_password"] == "********"

    store.update_section(
        SourceKind.EMAIL,
        {
            "imap_host": "imap.qq.com",
            "imap_port": 993,
            "imap_user": "me@qq.com",
            "imap_password": "********",
        },
    )
    section_after = store.get_section(SourceKind.EMAIL)
    assert section_after["imap_password"] == "secret"
