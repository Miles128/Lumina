"""Lumina overlay for the external Shibei knowledge-base app."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from secretary.exceptions import SecretaryError

_env_root = os.environ.get("SHIBEI_INSTALL_ROOT", "").strip()
_CANDIDATE_INSTALL_ROOTS: tuple[Path, ...] = (
    (Path(_env_root).expanduser(),)
    if _env_root
    else (Path.home() / "Documents" / "My Projects" / "shibei",)
)


class ShibeiConfigDocument(BaseModel):
    enabled: bool = True
    install_path: str = ""
    config_path: str = ""
    auto_import_on_sync: bool = False


@dataclass(frozen=True)
class ShibeiConfigView:
    enabled: bool
    sources: list[str]
    extensions: list[str]
    search_engine: str
    auto_import_on_sync: bool
    collection: str
    install_path: str
    config_path: str
    db_path: str
    status: str
    status_message: str
    source_count: int
    shibei_available: bool


class ShibeiConfigStore:
    """Stores only Lumina-side toggles; Shibei's own config.yaml is the source of truth."""

    def __init__(self, config_path: Path, *, data_dir: Path) -> None:
        self._path = config_path
        self._data_dir = data_dir

    def load(self) -> ShibeiConfigDocument:
        if not self._path.exists():
            return ShibeiConfigDocument()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SecretaryError(f"invalid shibei config: {self._path}") from exc
        allowed = {key for key in ShibeiConfigDocument.model_fields}
        filtered = {key: value for key, value in raw.items() if key in allowed}
        return ShibeiConfigDocument.model_validate(filtered)

    def save(self, document: ShibeiConfigDocument) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            document.model_dump_json(indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def update(self, payload: dict[str, object]) -> ShibeiConfigDocument:
        current = self.load()
        merged = current.model_dump()
        for key, value in payload.items():
            if key not in merged or value is None:
                continue
            merged[key] = value
        document = ShibeiConfigDocument.model_validate(merged)
        self.save(document)
        return document

    def resolve_install_root(self, document: ShibeiConfigDocument | None = None) -> Path | None:
        document = document or self.load()
        candidates: list[Path] = []
        if document.install_path.strip():
            candidates.append(Path(document.install_path.strip()).expanduser())
        for root in _CANDIDATE_INSTALL_ROOTS:
            candidates.append(root)
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if (resolved / "config.yaml").is_file():
                return resolved
            if (resolved / "src" / "shibei" / "__init__.py").is_file():
                return resolved
        return None

    def resolve_config_path(self, document: ShibeiConfigDocument | None = None) -> Path:
        document = document or self.load()
        if document.config_path.strip():
            path = Path(document.config_path.strip()).expanduser()
            if path.is_file():
                return path.resolve()
        install_root = self.resolve_install_root(document)
        if install_root is not None:
            config = install_root / "config.yaml"
            if config.is_file():
                return config.resolve()
        return Path("config.yaml")
