"""Persistent platform connector configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from secretary.core.types import SourceKind
from secretary.exceptions import SecretaryError
from secretary.utils.paths import default_documents_dir


class EmailPlatformConfig(BaseModel):
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""


class WeixinOAPlatformConfig(BaseModel):
    urls: str = ""


class CloudDrivePlatformConfig(BaseModel):
    paths: str = ""


class LocalDocumentsPlatformConfig(BaseModel):
    enabled: bool = False
    path: str = ""
    max_files: int = 1000


class PlatformConfigDocument(BaseModel):
    email: EmailPlatformConfig = Field(default_factory=EmailPlatformConfig)
    weixin_oa: WeixinOAPlatformConfig = Field(default_factory=WeixinOAPlatformConfig)
    cloud_drive: CloudDrivePlatformConfig = Field(default_factory=CloudDrivePlatformConfig)
    local_documents: LocalDocumentsPlatformConfig = Field(
        default_factory=LocalDocumentsPlatformConfig,
    )


@dataclass(frozen=True)
class PlatformField:
    key: str
    label: str
    field_type: str = "text"
    placeholder: str = ""


@dataclass(frozen=True)
class PlatformDefinition:
    source: SourceKind
    name: str
    description: str
    kind: str
    setup_hint: str
    fields: tuple[PlatformField, ...]


PLATFORM_DEFINITIONS: tuple[PlatformDefinition, ...] = (
    PlatformDefinition(
        source=SourceKind.FEISHU,
        name="飞书",
        description="同步日程、任务与飞书办公数据",
        kind="cli",
        setup_hint="终端执行 `lark-cli auth login` 完成用户授权",
        fields=(),
    ),
    PlatformDefinition(
        source=SourceKind.EMAIL,
        name="邮箱",
        description="通过 IMAP 同步邮件内容",
        kind="form",
        setup_hint="QQ/163/Gmail 等邮箱需开启 IMAP 并使用授权码",
        fields=(
            PlatformField("imap_host", "IMAP 服务器", placeholder="imap.qq.com"),
            PlatformField("imap_port", "端口", field_type="number", placeholder="993"),
            PlatformField("imap_user", "邮箱账号", placeholder="you@example.com"),
            PlatformField("imap_password", "密码 / 授权码", field_type="password"),
        ),
    ),
    PlatformDefinition(
        source=SourceKind.WEREAD,
        name="微信读书",
        description="同步书架、划线与笔记",
        kind="cli",
        setup_hint="Chrome 登录微信读书，终端执行 `autocli doctor` 确认可用",
        fields=(),
    ),
    PlatformDefinition(
        source=SourceKind.XIAOHONGSHU,
        name="小红书",
        description="同步创作者数据与推荐 Feed",
        kind="cli",
        setup_hint="Chrome 登录小红书，终端执行 `autocli doctor` 确认可用",
        fields=(),
    ),
    PlatformDefinition(
        source=SourceKind.WEIXIN_OA,
        name="微信公众号",
        description="下载并归档公众号文章",
        kind="form",
        setup_hint="每行填写一篇公众号文章链接",
        fields=(PlatformField("urls", "文章链接", field_type="textarea", placeholder="https://mp.weixin.qq.com/s/..."),),
    ),
    PlatformDefinition(
        source=SourceKind.CLOUD_DRIVE,
        name="本地网盘目录",
        description="扫描百度网盘/阿里云盘等本地同步文件夹",
        kind="form",
        setup_hint="每行填写一个本地文件夹路径",
        fields=(
            PlatformField(
                "paths",
                "文件夹路径",
                field_type="textarea",
                placeholder="/Users/you/BaiduNetdisk",
            ),
        ),
    ),
    PlatformDefinition(
        source=SourceKind.LOCAL_DOCUMENTS,
        name="本地文档",
        description="读取 README、简历与个人文章，仅更新人物侧写，不写入记忆索引",
        kind="form",
        setup_hint=(
            f"默认扫描 {default_documents_dir()}。"
            " 自动跳过代码与技术文档，只分析与人相关的文本。"
        ),
        fields=(
            PlatformField("enabled", "启用分析", field_type="checkbox"),
            PlatformField(
                "path",
                "自定义路径（留空用系统默认）",
                placeholder=str(default_documents_dir()),
            ),
            PlatformField(
                "max_files",
                "最多分析文档数",
                field_type="number",
                placeholder="25",
            ),
        ),
    ),
)


class PlatformConfigStore:
    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> PlatformConfigDocument:
        if not self._path.exists():
            return PlatformConfigDocument()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SecretaryError(f"invalid platform config: {self._path}") from exc
        return PlatformConfigDocument.model_validate(raw)

    def save(self, document: PlatformConfigDocument) -> None:
        self._path.write_text(
            document.model_dump_json(indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def get_section(self, source: SourceKind) -> dict[str, str | int]:
        document = self.load()
        if source is SourceKind.EMAIL:
            return document.email.model_dump()
        if source is SourceKind.WEIXIN_OA:
            return document.weixin_oa.model_dump()
        if source is SourceKind.CLOUD_DRIVE:
            return document.cloud_drive.model_dump()
        if source is SourceKind.LOCAL_DOCUMENTS:
            return document.local_documents.model_dump()
        return {}

    def update_section(
        self,
        source: SourceKind,
        payload: dict[str, object],
    ) -> PlatformConfigDocument:
        document = self.load()
        if source is SourceKind.EMAIL:
            current = document.email.model_dump()
            merged = _merge_section(current, payload, secret_keys={"imap_password"})
            document.email = EmailPlatformConfig.model_validate(merged)
        elif source is SourceKind.WEIXIN_OA:
            current = document.weixin_oa.model_dump()
            merged = _merge_section(current, payload, secret_keys=set())
            document.weixin_oa = WeixinOAPlatformConfig.model_validate(merged)
        elif source is SourceKind.CLOUD_DRIVE:
            current = document.cloud_drive.model_dump()
            merged = _merge_section(current, payload, secret_keys=set())
            document.cloud_drive = CloudDrivePlatformConfig.model_validate(merged)
        elif source is SourceKind.LOCAL_DOCUMENTS:
            current = document.local_documents.model_dump()
            merged = _merge_section(current, payload, secret_keys=set())
            document.local_documents = LocalDocumentsPlatformConfig.model_validate(merged)
        else:
            return document
        self.save(document)
        return document

    def apply_to_settings(self, settings: Any) -> None:
        document = self.load()
        settings.email_imap_host = document.email.imap_host
        settings.email_imap_port = document.email.imap_port
        settings.email_imap_user = document.email.imap_user
        settings.email_imap_password = document.email.imap_password
        settings.weixin_oa_urls = _lines_to_csv(document.weixin_oa.urls)
        settings.cloud_drive_paths = _lines_to_csv(document.cloud_drive.paths)
        settings.local_documents_enabled = document.local_documents.enabled
        settings.local_documents_path = document.local_documents.path.strip()
        settings.local_documents_max_files = document.local_documents.max_files


def _merge_section(
    current: dict[str, object],
    payload: dict[str, object],
    secret_keys: set[str],
) -> dict[str, object]:
    merged = dict(current)
    for key, value in payload.items():
        if key not in current:
            continue
        if key in secret_keys and (value == "" or value == "********"):
            continue
        merged[key] = value
    return merged


def _lines_to_csv(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return ",".join(lines)


def mask_secrets(values: dict[str, object]) -> dict[str, object]:
    masked = dict(values)
    if masked.get("imap_password"):
        masked["imap_password"] = "********"
    return masked
