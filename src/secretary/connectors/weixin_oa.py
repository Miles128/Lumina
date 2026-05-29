"""WeChat Official Account connector via autocli download."""

from __future__ import annotations

from urllib.parse import urlparse

from secretary.connectors.base import BaseConnector
from secretary.core.types import MemoryChunk, SourceKind
from secretary.exceptions import ConnectorError, ConnectorNotConfiguredError
from secretary.memory.ingest import chunk_text

_ALLOWED_WEIXIN_HOSTS = {"mp.weixin.qq.com"}


class WeixinOAConnector(BaseConnector):
    source = SourceKind.WEIXIN_OA

    def is_configured(self) -> bool:
        return bool(self._settings.parsed_weixin_urls())

    def fetch(self) -> list[MemoryChunk]:
        urls = self._settings.parsed_weixin_urls()
        if not urls:
            raise ConnectorNotConfiguredError("WEIXIN_OA_URLS is empty")

        export_dir = self._settings.resolved_data_dir() / "weixin_articles"
        export_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[MemoryChunk] = []
        for index, url in enumerate(urls):
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or parsed.hostname not in _ALLOWED_WEIXIN_HOSTS:
                raise ConnectorError(f"invalid weixin URL: {url}")
            output_path = export_dir / f"article_{index}.md"
            self.run_command(
                [
                    "autocli",
                    "weixin",
                    "download",
                    url,
                    "--output",
                    str(output_path),
                ],
                timeout=120,
            )
            if not output_path.exists():
                continue
            content = output_path.read_text(encoding="utf-8", errors="replace")
            title = _extract_title(content, fallback=f"公众号文章 {index + 1}")
            chunks.extend(
                chunk_text(
                    source=self.source,
                    key=url,
                    title=f"公众号 · {title}",
                    body=content,
                    metadata={"url": url, "path": str(output_path)},
                )
            )
        return chunks


def _extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback
