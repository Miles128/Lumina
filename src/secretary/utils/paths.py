"""Default user documents folder per OS."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def default_documents_dir() -> Path:
    """Return the OS default Documents folder (Mac/Linux/Windows)."""
    home = Path.home()
    if sys.platform == "win32":
        return home / "Documents"
    if sys.platform == "linux":
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DOCUMENTS"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            candidate = Path(result.stdout.strip())
            if candidate.is_dir():
                return candidate
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
    return home / "Documents"
