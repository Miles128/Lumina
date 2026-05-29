"""Email connector via IMAP."""

from __future__ import annotations

import email
import imaplib
from email.header import decode_header

from secretary.connectors.base import BaseConnector
from secretary.core.types import MemoryChunk, SourceKind
from secretary.exceptions import ConnectorError, ConnectorNotConfiguredError
from secretary.memory.ingest import chunk_text


class EmailConnector(BaseConnector):
    source = SourceKind.EMAIL

    def is_configured(self) -> bool:
        return bool(
            self._settings.email_imap_host
            and self._settings.email_imap_user
            and self._settings.email_imap_password
        )

    def fetch(self) -> list[MemoryChunk]:
        if not self.is_configured():
            raise ConnectorNotConfiguredError("email IMAP credentials are missing")

        try:
            client = imaplib.IMAP4_SSL(
                self._settings.email_imap_host,
                self._settings.email_imap_port,
            )
            client.login(self._settings.email_imap_user, self._settings.email_imap_password)
            client.select("INBOX")
            _, data = client.search(None, "ALL")
            message_ids = data[0].split()[-20:]
            chunks: list[MemoryChunk] = []
            for message_id in message_ids:
                _, msg_data = client.fetch(message_id, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw_email = msg_data[0][1]
                if not isinstance(raw_email, (bytes, bytearray)):
                    continue
                message = email.message_from_bytes(raw_email)
                subject = _decode_header_value(message.get("Subject"))
                sender = _decode_header_value(message.get("From"))
                date = _decode_header_value(message.get("Date"))
                body = _extract_body(message)
                chunks.extend(
                    chunk_text(
                        source=self.source,
                        key=f"{message_id.decode()}:{subject}",
                        title=f"邮件 · {subject or '无主题'}",
                        body=f"发件人: {sender}\n时间: {date}\n\n{body}",
                        metadata={"sender": sender, "date": date},
                    )
                )
            client.logout()
            return chunks
        except imaplib.IMAP4.error as exc:
            raise ConnectorError(f"IMAP error: {exc}") from exc


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for fragment, encoding in decode_header(value):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts)


def _extract_body(message: email.message.Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, (bytes, bytearray)):
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = message.get_payload(decode=True)
    if isinstance(payload, (bytes, bytearray)):
        return payload.decode(message.get_content_charset() or "utf-8", errors="replace")
    return str(payload or "")
