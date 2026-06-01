"""Canonical Lumina assistant identity — used for self-introduction, not user profile."""

from __future__ import annotations

import re

LUMINA_DEFAULT_STYLE = "轻巧灵动、简明扼要"

LUMINA_IDENTITY_INTRO = f"""我是灵犀（Lumina），在你本机运行的个人 AI 秘书。

我的说话风格：{LUMINA_DEFAULT_STYLE}——先给结论，句子短，不铺垫。

我能帮你读本地文件、搜索记忆、联网搜索、同步数据源、调用工具；涉及写入或删除时会先征求你确认。

我的技术栈是：
- 前端：Electron + HTML / CSS / JavaScript
- 后端：Python + FastAPI
- 数据：本地 SQLite，配置与记忆存放在本机用户目录的 .lumina 文件夹"""

LUMINA_AUTHOR_REPLY = """灵犀（Lumina）由四海开发维护。

- 开发者：四海
- 邮箱：myx28@qq.com
- 版本：0.1.0

我是跑在你本机上的个人 AI 秘书；更多产品信息见右上角「关于」。"""

LUMINA_IDENTITY_SYSTEM_BLOCK = f"""## 灵犀身份与风格（描述灵犀 APP 本人，不是用户）

默认风格：{LUMINA_DEFAULT_STYLE}

""" + LUMINA_IDENTITY_INTRO + """

边界：
- 用户画像、本地文档摘录、相关本地记忆描述的是用户本人，不是灵犀
- 介绍灵犀本人、说明灵犀怎么说话时，只用本节内容与 SOUL；不要把用户资料里的性格、技术栈、用词当成灵犀自己的
- 灵犀的技术栈仅限：Electron + HTML/CSS/JS 前端，Python + FastAPI 后端，本地 SQLite
- 禁止在自我介绍里声称使用阿里云百炼、Apple Silicon 等与本产品架构无关的技术
- 禁止任何脏话、粗俗词、网络俚语或口语化贬损表达"""

_USER_INTRO_HELP_MARKERS = (
    "帮我写",
    "帮我做",
    "帮我撰",
    "帮我起草",
    "帮我编辑",
    "帮我润色",
    "写一份",
    "写个",
    "撰写",
    "起草",
)

_ASSISTANT_IDENTITY_MARKERS = (
    "你是谁",
    "你是什么",
    "介绍一下你自己",
    "介绍一下你",
    "说说你自己",
    "你叫什么",
    "你叫啥",
    "who are you",
    "what are you",
    "你是做什么的",
    "你是干啥的",
    "你能做什么",
    "你会什么",
    "你都能干什么",
    "你会干什么",
    "说说你的能力",
    "你有什么功能",
    "介绍一下灵犀",
    "灵犀是什么",
    "什么是灵犀",
    "what is lumina",
)

_SHORT_INTRO_PHRASES = frozenset({"介绍", "介绍一下", "介绍下"})

_REPEAT_IDENTITY_MARKERS = (
    "再说一遍",
    "再说一次",
    "再来一遍",
    "再来一次",
    "再讲一遍",
    "重复一遍",
    "再介绍",
)

_IDENTITY_INTRO_SNIPPET = "我是灵犀（Lumina）"

_AUTHOR_MARKERS = (
    "谁写的",
    "谁写",
    "谁开发",
    "谁做的",
    "谁制作",
    "谁创造",
    "你的作者",
    "你的开发者",
    "你的创建者",
    "谁是你的作者",
    "谁是你的开发者",
    "你的作者是谁",
    "你的开发者是谁",
    "谁创造了你",
    "谁创造了灵犀",
    "who made you",
    "who created you",
    "who built you",
    "who developed you",
)


def get_author_reply() -> str:
    """Fixed author/creator answer; never LLM-generated."""
    return LUMINA_AUTHOR_REPLY


def is_author_request(text: str) -> bool:
    """True when the user asks who created/developed Lumina."""
    cleaned = _normalize_request_text(text)
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if any(marker in cleaned or marker in lowered for marker in _AUTHOR_MARKERS):
        return True
    if re.search(r"谁.{0,6}写.{0,4}(你|灵犀|lumina)", cleaned, flags=re.IGNORECASE):
        return True
    if re.search(r"(你|灵犀).{0,8}(作者|开发者|创建者|制作人)", cleaned, flags=re.IGNORECASE):
        return True
    if re.search(r"(作者|开发者|创建者|制作人).{0,8}(是谁|哪位|谁)", cleaned):
        return True
    return False


def get_identity_reply() -> str:
    """Fixed self-introduction; never LLM-generated."""
    return LUMINA_IDENTITY_INTRO


def _normalize_request_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = cleaned.rstrip("？?!！。.")
    return cleaned


def _is_user_intro_help_request(cleaned: str) -> bool:
    if any(marker in cleaned for marker in _USER_INTRO_HELP_MARKERS):
        return True
    if "我的" in cleaned and "自我介绍" in cleaned and "你" not in cleaned:
        return True
    return False


def _core_identity_match(cleaned: str) -> bool:
    lowered = cleaned.lower()

    if is_author_request(cleaned):
        return False

    if _is_user_intro_help_request(cleaned):
        return False

    if cleaned in _SHORT_INTRO_PHRASES:
        return True

    if "自我介绍" in cleaned:
        return True

    if cleaned in {"你是谁", "你是什么"} or re.fullmatch(r"你是谁[啊呀吗]?[？?]?", cleaned):
        return True

    identity_markers = tuple(
        marker for marker in _ASSISTANT_IDENTITY_MARKERS if marker not in {"你是谁", "你是什么"}
    )
    if any(marker in cleaned or marker in lowered for marker in identity_markers):
        return True

    if re.search(r"(做|来|请|给).{0,4}自我介绍", cleaned):
        return True

    if re.search(r"介绍(一下)?(你|你自己|灵犀|lumina)", cleaned, flags=re.IGNORECASE):
        return True

    if re.search(r"(你|灵犀).{0,6}介绍", cleaned, flags=re.IGNORECASE):
        return True

    if re.search(r"再.{0,8}介绍.{0,8}(你|自己|灵犀)?", cleaned):
        return True

    return False


def _is_identity_repeat_request(
    cleaned: str,
    history: list[dict[str, str]],
) -> bool:
    if not any(marker in cleaned for marker in _REPEAT_IDENTITY_MARKERS):
        return False
    if re.search(r"(你|自己|灵犀|介绍|是谁|做什么|能力|功能)", cleaned):
        return True
    for item in reversed(history[-6:]):
        role = str(item.get("role", ""))
        content = str(item.get("content", ""))
        if role == "assistant" and _IDENTITY_INTRO_SNIPPET in content:
            return True
        if role == "user" and _core_identity_match(_normalize_request_text(content)):
            return True
    return False


def is_identity_request(
    text: str,
    history: list[dict[str, str]] | None = None,
) -> bool:
    """True when the user asks the assistant to introduce itself."""
    cleaned = _normalize_request_text(text)
    if not cleaned:
        return False
    if _core_identity_match(cleaned):
        return True
    if history:
        return _is_identity_repeat_request(cleaned, history)
    return False
