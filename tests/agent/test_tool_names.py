"""Single source of truth for tool aliases / labels."""

from __future__ import annotations

from secretary.agent.tool_names import (
    LEGACY_TO_CANONICAL,
    all_tool_aliases,
    expand_aliases,
    to_canonical,
    tool_label,
)


def test_alias_map_covers_known_pairs() -> None:
    assert LEGACY_TO_CANONICAL["file_read"] == "read"
    assert LEGACY_TO_CANONICAL["file_write"] == "write"
    assert LEGACY_TO_CANONICAL["patch"] == "edit"
    assert LEGACY_TO_CANONICAL["list_dir"] == "ls"
    assert LEGACY_TO_CANONICAL["search_files"] == "grep"
    assert LEGACY_TO_CANONICAL["glob_files"] == "glob"
    assert LEGACY_TO_CANONICAL["find"] == "glob"


def test_to_canonical_and_aliases() -> None:
    assert to_canonical("file_read") == "read"
    assert to_canonical("read") == "read"
    assert to_canonical("web_search") == "web_search"
    assert "file_read" in all_tool_aliases("read")
    assert all_tool_aliases("read")[0] == "read"


def test_expand_aliases_adds_legacy_names() -> None:
    expanded = expand_aliases(frozenset({"read", "ls", "web_search"}))
    assert {"file_read", "list_dir"} <= expanded
    assert "web_search" in expanded
    assert "search_files" not in expanded  # grep not in the input set


def test_tool_label_resolves_aliases() -> None:
    assert tool_label("read") == tool_label("file_read") == "读取文件"
    assert tool_label("list_dir") == tool_label("ls") == "浏览目录"
    assert tool_label("unknown_tool") == ""
