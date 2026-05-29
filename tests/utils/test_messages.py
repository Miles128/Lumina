"""Tests for connector message formatting."""

from secretary.utils.messages import format_connector_message


def test_format_connector_message_parses_json_hint() -> None:
    raw = (
        '{"ok": false, "error": {"message": "not configured", '
        '"hint": "run `lark-cli config init --new`"}}'
    )
    assert "lark-cli config init" in format_connector_message(raw)


def test_format_connector_message_uses_first_line() -> None:
    raw = "Waking up Chrome extension...\nChrome extension not connected"
    assert format_connector_message(raw) == "Waking up Chrome extension..."
