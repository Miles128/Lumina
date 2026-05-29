"""Tests for default documents path."""

import sys
from pathlib import Path

from secretary.utils.paths import default_documents_dir


def test_default_documents_dir() -> None:
    path = default_documents_dir()
    assert path.name == "Documents"
    assert path.parent == Path.home()
    if sys.platform == "win32":
        assert "Documents" in str(path)
