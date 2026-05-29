"""Tests for local documents profiler."""

from pathlib import Path

from secretary.config import Settings
from secretary.services.local_documents_profiler import LocalDocumentsProfiler


def test_profiler_keeps_excerpts_not_guesses(tmp_path: Path) -> None:
    docs = tmp_path / "Documents"
    project = docs / "my-blog"
    project.mkdir(parents=True)
    (project / "README.md").write_text(
        "关于我：产品与设计背景，关注用户体验和内容创作。",
        encoding="utf-8",
    )
    (project / "resume.md").write_text(
        "工作经历：负责产品运营与团队管理，擅长品牌策略。",
        encoding="utf-8",
    )
    (project / "main.py").write_text("import os\ndef main(): pass", encoding="utf-8")

    settings = Settings(
        local_documents_enabled=True,
        local_documents_path=str(docs),
        local_documents_max_files=10,
    )
    profile = LocalDocumentsProfiler(settings).analyze_and_save()

    assert profile.analyzed_files >= 2
    assert profile.excerpts
    joined = profile.to_section_text()
    assert "已从" in joined
    assert "可能从事" not in joined
    assert "表达风格" not in joined
    assert any("产品" in item.preview for item in profile.excerpts)


def test_profiler_skips_open_source_project_readme(tmp_path: Path) -> None:
    docs = tmp_path / "Documents"
    project = docs / "open-design"
    project.mkdir(parents=True)
    (project / "package.json").write_text("{}", encoding="utf-8")
    (project / "README.md").write_text(
        "## Installation\n\nnpm install\n\n## Contributing\n\nPull request welcome.",
        encoding="utf-8",
    )
    (project / "resume.md").write_text("个人简介：专注产品设计与内容创作。", encoding="utf-8")

    settings = Settings(
        local_documents_enabled=True,
        local_documents_path=str(docs),
        local_documents_max_files=10,
    )
    profile = LocalDocumentsProfiler(settings).analyze_and_save()

    files = {item.file for item in profile.excerpts}
    assert "open-design/resume.md" in files
    assert "open-design/README.md" not in files


def test_profiler_keeps_personal_writing_not_tutorial_repo(tmp_path: Path) -> None:
    docs = tmp_path / "Documents"
    writing = docs / "随笔"
    writing.mkdir(parents=True)
    (writing / "2025-年度总结.md").write_text(
        "今年我主要在做产品规划，也在探索 AI 工具如何帮助写作。",
        encoding="utf-8",
    )
    tutorial = docs / "react-starter-demo"
    tutorial.mkdir(parents=True)
    (tutorial / "package.json").write_text("{}", encoding="utf-8")
    (tutorial / "README.md").write_text(
        "Getting started\n\n```bash\nnpm install\n```",
        encoding="utf-8",
    )

    settings = Settings(
        local_documents_enabled=True,
        local_documents_path=str(docs),
        local_documents_max_files=10,
    )
    profile = LocalDocumentsProfiler(settings).analyze_and_save()

    files = {item.file for item in profile.excerpts}
    assert "随笔/2025-年度总结.md" in files
    assert "react-starter-demo/README.md" not in files
