"""LLM-based rewrite for machine-like third-person phrasing."""

from __future__ import annotations

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError

FORBIDDEN_LABEL = "用户"

_STRONG_REWRITE_MARKERS = (
    "未明确",
    "命令模糊",
    "指令模糊",
    "情绪化",
    "情绪激动",
    "需等待",
    "需要澄清",
    "第三人称",
)

_LITE_REWRITE_SYSTEM = """你是对话润色器。把一句机器腔文本改成自然对话。
要求：
1) 保持原意，不新增事实。
2) 直接对“你”说话。
3) 禁止出现“用户”两个字。
4) 语气平稳、礼貌，不啰嗦。
5) 优先 1 句；必要时最多 2 句。
6) 只输出最终改写，不要解释。"""

_STRONG_REWRITE_SYSTEM = """你是对话修复器。把第三人称分析腔改写成可直接沟通的话。
要求：
1) 保持原意，不新增事实。
2) 去掉审稿口吻、评价口吻、情绪分析。
3) 全部改为对“你”的直接表达。
4) 禁止出现“用户”两个字。
5) 语气平稳、温和、简短，不说套话。
6) 优先 1 句；必要时最多 2 句。
7) 只输出最终改写，不要解释。"""


def rewrite_if_forbidden_label(
    reply: str,
    user_message: str,
    llm_config: LlmConfig | None,
) -> str:
    text = reply.strip()
    if not text or FORBIDDEN_LABEL not in text or llm_config is None:
        return text
    system_prompt = _pick_rewrite_system_prompt(text)
    try:
        rewritten = chat_completion(
            llm_config,
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"原句：{text}\n"
                        f"对话上下文（可参考）：{user_message}\n"
                        "请改写："
                    ),
                },
            ],
            temperature=0.0,
            timeout=20.0,
        ).strip()
        return rewritten or text
    except AgentError:
        return text


def _pick_rewrite_system_prompt(text: str) -> str:
    hits = sum(marker in text for marker in _STRONG_REWRITE_MARKERS)
    if hits >= 1 or text.count(FORBIDDEN_LABEL) >= 2:
        return _STRONG_REWRITE_SYSTEM
    return _LITE_REWRITE_SYSTEM
