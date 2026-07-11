"""Tests for code_exec and read_document tools."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.tools.code_exec import CodeExecTool
from secretary.agent.tools.documents import ReadDocumentTool


def test_code_exec_runs_snippet(tmp_path: Path) -> None:
    tool = CodeExecTool()
    out = tool.execute({"code": "print(2 + 2)"}, tmp_path)
    assert "4" in out
    assert tool.needs_confirmation is True


def test_code_exec_captures_stderr_and_exit(tmp_path: Path) -> None:
    tool = CodeExecTool()
    out = tool.execute({"code": "import sys\nprint('bad', file=sys.stderr)\nsys.exit(3)"}, tmp_path)
    assert "bad" in out
    assert "exit code: 3" in out


def test_code_exec_rejects_empty(tmp_path: Path) -> None:
    tool = CodeExecTool()
    assert tool.execute({"code": "  "}, tmp_path).startswith("Error:")


def test_code_exec_blocks_open_outside_cwd(tmp_path: Path) -> None:
    tool = CodeExecTool()
    secret = tmp_path / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")
    # Snippet runs in a temp cwd; opening the host path should be denied.
    out = tool.execute(
        {"code": f"print(open({str(secret)!r}).read())"},
        tmp_path,
    )
    assert "top-secret" not in out
    assert "Error" in out or "PermissionError" in out or "sandbox" in out.lower()


def test_code_exec_blocks_network_socket(tmp_path: Path) -> None:
    tool = CodeExecTool()
    out = tool.execute(
        {
            "code": (
                "import socket\n"
                "s = socket.socket()\n"
                "s.connect(('127.0.0.1', 1))\n"
            )
        },
        tmp_path,
    )
    assert "Error" in out or "PermissionError" in out or "sandbox" in out.lower()


def test_read_document_xlsx(tmp_path: Path) -> None:
    from openpyxl import Workbook

    path = tmp_path / "sample.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Data"
    ws.append(["name", "score"])
    ws.append(["Alice", 95])
    wb.save(path)

    tool = ReadDocumentTool()
    out = tool.execute({"path": str(path)}, tmp_path)
    assert "Alice" in out
    assert "95" in out
    assert "Data" in out


def test_read_document_docx(tmp_path: Path) -> None:
    from docx import Document

    path = tmp_path / "note.docx"
    doc = Document()
    doc.add_paragraph("Hello from Word")
    doc.save(path)

    tool = ReadDocumentTool()
    out = tool.execute({"path": str(path)}, tmp_path)
    assert "Hello from Word" in out


def test_read_document_pdf(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    path = tmp_path / "doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(path)

    tool = ReadDocumentTool()
    out = tool.execute({"path": str(path)}, tmp_path)
    assert "Error:" not in out
    assert "PDF" in out or "Page" in out


def test_read_document_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"\x00\x01")
    tool = ReadDocumentTool()
    out = tool.execute({"path": str(path)}, tmp_path)
    assert out.startswith("Error: unsupported")
