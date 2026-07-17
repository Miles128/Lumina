# 退役 USER.md：用户事实统一归 ProfileService 管理

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `memories/USER.md` 从 Lumina 退役，让 `ProfileService` 成为唯一"用户事实"存储；`LuminaMemory` 只保留 `MEMORY.md`（任务/环境/项目事实 + 会话摘要）。消除 BackgroundReviewService 双写、系统提示词双段、前端双编辑框的重叠。

**Architecture:** `LuminaMemory` 的 `target="user"` 路径全部移除（`user_md_path` / `read_user_md` / `write_user_md` / `mutate_memory` 拒绝 user / `prompt_snapshot` 只返回 MEMORY.md / `import_from_hermes` 不再导入 USER.md）。`BackgroundReviewService` 只剩 `target="memory"`，用户事实改由 `_sync_profile_fact` 单写。`MemoryCompressionService` 只压缩 MEMORY.md。`ScheduledThinkService` 的 `target` 白名单去掉 `user`。`MemoryTool` 的 `target` 枚举只剩 `memory`。`/api/memory/durable` GET/PUT 只处理 `memory_md`。系统提示词第 1651 行去掉 "durable memory（USER.md）"，保留 "用户画像"。前端记忆面板去掉 USER.md 编辑框。

**Tech Stack:** Python 3.12, FastAPI, pytest, vanilla JS（前端）

**Backwards compatibility:**
- `~/.lumina/memories/USER.md` 文件若已存在，**不主动删除**，只是不再读写、不再注入。用户可手动迁移内容到 `profile_chat_facts.md` 或 `user_profile.md`。
- `mutate_memory(action, target="user", ...)` 改为抛 `ValueError("target=user is retired; use ProfileService")`，调用方（Agent 工具 / 后台任务）会捕获并降级。
- 旧前端缓存里若有 `user_md` 字段，新后端响应不再返回该字段，前端 JS 已同步删除读取代码。

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/secretary/memory/lumina_memory.py` | Modify | 删除 USER.md 相关：`USER_MD_MAX_CHARS`、`user_md_path`、`read_user_md`、`write_user_md`；`mutate_memory` 拒绝 `target=user`；`prompt_snapshot` 只返回 `## Durable Memory`；`import_from_hermes` 不再导入 USER.md |
| `src/secretary/agent/tools/memory_tools.py` | Modify | `MemoryTool` 的 `target` 枚举从 `["memory","user"]` 改为 `["memory"]`；description 删去 USER.md 说明 |
| `src/secretary/services/background_review.py` | Modify | `_REVIEW_SYSTEM` 提示词删去 `target=user` 分支规则；`_run_review` 删去 `mutate_memory` 调用中 `target=user` 的可能性——LLM 仍可能返回 `target=user`，遇到时改走 `_sync_profile_fact`（不再调 `mutate_memory`）；`apply_decision_for_tests` 同步 |
| `src/secretary/services/memory_compress.py` | Modify | 删除 USER.md 压缩分支；`compress_if_needed` 只调一次 `_compress_target`（MEMORY.md） |
| `src/secretary/services/scheduled_think.py` | Modify | `_apply_result` 中 `target` 白名单从 `{"memory","user"}` 改为 `{"memory"}`；遇到 `target=user` 直接跳过（不报错） |
| `src/secretary/api/app.py` | Modify | `/api/memory/durable` GET 响应只返 `{"memory_md": ...}`；PUT 只接受 `memory_md`；`/api/memory/import-hermes` 响应去掉 `user_md` |
| `src/secretary/agent/chat_service.py` | Modify | 第 1651 行规则改为 "用户在本轮明确提供的个人信息，应在回复后写入用户画像（profile）"；删去 "durable memory（USER.md）与"；保留第 1652 行 "完成复杂任务后，总结关键事实到 durable memory" |
| `desktop/ui/settings.js` | Modify | 删去 `durableUserMd` 变量；`loadSettings` 不再读 `durable.user_md`；`renderAgentMemoryPane` 删去 USER.md 编辑框；`saveDurableMemory` 只提交 `memory_md` |
| `tests/memory/test_lumina_memory.py` | Modify | 删除/重写 3 个用 USER.md 的测试；新增 `target=user` 抛 ValueError 的测试 |
| `tests/agent/test_loop_tools.py` | Modify | `test_memory_tool_add` 改用 `target=memory` |
| `tests/api/test_app.py` | Modify | `test_durable_memory_endpoint` 去掉 `user_md` 断言 |
| `tests/services/test_memory_compress.py` | Modify | 若有用 `write_user_md` 的 fixture，改掉 |

执行顺序：Task 1（LuminaMemory 核心）→ Task 2（MemoryTool）→ Task 3（BackgroundReview）→ Task 4（MemoryCompress）→ Task 5（ScheduledThink）→ Task 6（API 端点）→ Task 7（chat_service 系统提示词）→ Task 8（前端）→ Task 9（全量回归）。

每个 Task 都能独立 commit，保持绿色。

---

## Task 1: LuminaMemory 退役 USER.md

**Files:**
- Modify: `src/secretary/memory/lumina_memory.py:1-163`
- Test: `tests/memory/test_lumina_memory.py`

- [ ] **Step 1: 写失败测试 — target=user 抛 ValueError**

替换 `tests/memory/test_lumina_memory.py:26-33` 的 `test_mutate_memory_remove_substring` 为：

```python
def test_mutate_memory_rejects_retired_user_target(tmp_path: Path) -> None:
    """USER.md 已退役：target=user 应抛 ValueError，引导调用方改用 ProfileService。"""
    memory = LuminaMemory(tmp_path)
    try:
        memory.mutate_memory("add", "user", text="Name: Alex")
        raised = False
    except ValueError as exc:
        raised = True
        assert "user" in str(exc).lower()
    assert raised


def test_mutate_memory_remove_substring(tmp_path: Path) -> None:
    """replace/remove 仍对 memory target 正常工作。"""
    memory = LuminaMemory(tmp_path)
    memory.write_memory_md("Name: Alex\nDislikes: emoji")
    result = memory.mutate_memory(
        "remove", "memory", old_text="Dislikes: emoji"
    )
    content = memory.read_memory_md()
    assert "Dislikes" not in content
    assert "Alex" in content
    assert result
```

- [ ] **Step 2: 写失败测试 — prompt_snapshot 不再含 User Profile 段**

在 `tests/memory/test_lumina_memory.py` 追加：

```python
def test_prompt_snapshot_only_returns_memory_md(tmp_path: Path) -> None:
    """USER.md 退役后，prompt_snapshot 只返回 ## Durable Memory 段。"""
    memory = LuminaMemory(tmp_path)
    memory.write_memory_md("- env fact: macOS")
    # 即便旧 USER.md 文件残留，也不应被读取
    (tmp_path / "memories" / "USER.md").write_text("- stale user fact\n", encoding="utf-8")
    snapshot = memory.prompt_snapshot()
    assert "## Durable Memory" in snapshot
    assert "env fact: macOS" in snapshot
    assert "## User Profile" not in snapshot
    assert "stale user fact" not in snapshot


def test_import_from_hermes_skips_user_md(tmp_path: Path, monkeypatch) -> None:
    """import_from_hermes 不再导入 USER.md，只导入 MEMORY.md。"""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "MEMORY.md").write_text("# Env\n- macOS\n", encoding="utf-8")
    (hermes_home / "USER.md").write_text("# User\n- prefers concise\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    memory = LuminaMemory(tmp_path / "lumina")
    imported = memory.import_from_hermes()

    assert imported == {"memory_md": str(hermes_home / "MEMORY.md")}
    assert "- macOS" in memory.read_memory_md()
    # USER.md 不应被导入到 Lumina 的 memories/USER.md
    assert not (tmp_path / "lumina" / "memories" / "USER.md").exists()
```

- [ ] **Step 3: 运行测试验证失败**

Run: `uv run pytest tests/memory/test_lumina_memory.py::test_mutate_memory_rejects_retired_user_target tests/memory/test_lumina_memory.py::test_prompt_snapshot_only_returns_memory_md tests/memory/test_lumina_memory.py::test_import_from_hermes_skips_user_md -v`
Expected: FAIL（`mutate_memory("add","user")` 当前会成功写 USER.md；`prompt_snapshot` 当前会返回 `## User Profile`；`import_from_hermes` 当前会导入 USER.md）

- [ ] **Step 4: 修改 lumina_memory.py — 删除 USER.md 常量与属性**

`src/secretary/memory/lumina_memory.py:17-18`，删除 `USER_MD_MAX_CHARS = 1375` 这一行。

`src/secretary/memory/lumina_memory.py:35-37`，删除整个 `user_md_path` property：

```python
    @property
    def user_md_path(self) -> Path:
        return self._memories_dir / "USER.md"
```

- [ ] **Step 5: 修改 mutate_memory — 拒绝 target=user**

`src/secretary/memory/lumina_memory.py:60-113`，把 `mutate_memory` 改为只支持 `target="memory"`：

```python
    def mutate_memory(
        self,
        action: str,
        target: str,
        *,
        text: str = "",
        old_text: str = "",
    ) -> str:
        """Apply add/replace/remove to MEMORY.md.

        USER.md 已退役；target=user 会抛 ValueError，请改用 ProfileService。
        """
        normalized_action = action.strip().lower()
        normalized_target = target.strip().lower()
        if normalized_action not in {"add", "replace", "remove"}:
            raise ValueError(f"unknown memory action: {action}")
        if normalized_target == "user":
            raise ValueError(
                "target=user is retired; use ProfileService for user facts"
            )
        if normalized_target != "memory":
            raise ValueError(f"unknown memory target: {target}")

        content = self.read_memory_md()
        label = "MEMORY.md"

        if normalized_action == "add":
            line = text.strip()
            if not line:
                return f"Error: empty text for add to {label}"
            if line in content:
                return f"Already present in {label}"
            if content:
                updated = f"{content}\n{line}".strip()
            else:
                updated = line
            self.write_memory_md(updated)
            return f"Added to {label}"

        if normalized_action == "replace":
            needle = old_text.strip()
            replacement = text.strip()
            if not needle:
                return f"Error: old_text required for replace in {label}"
            if needle not in content:
                return f"Error: old_text not found in {label}"
            self.write_memory_md(content.replace(needle, replacement, 1))
            return f"Replaced in {label}"

        needle = old_text.strip()
        if not needle:
            return f"Error: old_text required for remove from {label}"
        if needle not in content:
            return f"Error: old_text not found in {label}"
        updated = content.replace(needle, "", 1)
        while "\n\n\n" in updated:
            updated = updated.replace("\n\n\n", "\n\n")
        self.write_memory_md(updated.strip())
        return f"Removed from {label}"
```

- [ ] **Step 6: 删除 read_user_md / write_user_md**

`src/secretary/memory/lumina_memory.py:115-125`，删除整个 `read_user_md` 和 `write_user_md` 两个方法。

- [ ] **Step 7: 修改 import_from_hermes — 不再导入 USER.md**

`src/secretary/memory/lumina_memory.py:127-153`，替换为：

```python
    def import_from_hermes(self) -> dict[str, str]:
        """One-shot import of MEMORY.md from ~/.hermes/ into Lumina.

        USER.md 已退役，不再导入；用户事实请通过 /api/profile 编辑。
        只查找 MEMORY.md（顶层或 memories/ 嵌套）。返回 {"memory_md": src_path}。
        """
        hermes_root = Path.home() / ".hermes"
        candidates: list[tuple[Path, Path]] = [
            (hermes_root / "MEMORY.md", self.memory_md_path),
            (hermes_root / "memories" / "MEMORY.md", self.memory_md_path),
        ]
        imported: dict[str, str] = {}
        for src, dst in candidates:
            if "memory_md" in imported:
                continue
            if not src.exists():
                continue
            text = src.read_text(encoding="utf-8").strip()
            if not text:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text + "\n", encoding="utf-8")
            imported["memory_md"] = str(src)
        return imported
```

- [ ] **Step 8: 修改 prompt_snapshot — 只返回 MEMORY.md**

`src/secretary/memory/lumina_memory.py:155-163`，替换为：

```python
    def prompt_snapshot(self) -> str:
        """Return MEMORY.md content for system prompt injection.

        USER.md 已退役，不再注入；用户事实由 ProfileService 单独注入。
        """
        memory = self.read_memory_md()
        if not memory:
            return ""
        return f"## Durable Memory\n{memory}"
```

- [ ] **Step 9: 修改顶部模块 docstring**

`src/secretary/memory/lumina_memory.py:1-6`，把第一行注释从 "Layer 1: MEMORY.md + USER.md" 改为 "Layer 1: MEMORY.md (durable facts, frozen snapshot in system prompt)"：

```python
"""Lumina three-layer memory system.

Layer 1: MEMORY.md (durable facts, frozen snapshot in system prompt)
Layer 2: Session archive (all conversations in SQLite with FTS5)
Layer 3: Episodic memory (task execution records with success/failure)
"""
```

- [ ] **Step 10: 修改旧测试 — test_import_from_hermes_top_level**

`tests/memory/test_lumina_memory.py:46-59`，把断言从 `{"memory_md","user_md"}` 改为只 `{"memory_md"}`：

```python
def test_import_from_hermes_top_level(tmp_path: Path, monkeypatch) -> None:
    """Import MEMORY.md from ~/.hermes/ top-level into Lumina. USER.md 不再导入。"""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "MEMORY.md").write_text("# Env\n- macOS\n", encoding="utf-8")
    (hermes_home / "USER.md").write_text("# User\n- prefers concise\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    memory = LuminaMemory(tmp_path / "lumina")
    imported = memory.import_from_hermes()

    assert imported == {"memory_md": str(hermes_home / "MEMORY.md")}
    assert "- macOS" in memory.read_memory_md()
    # USER.md 不应被导入
    assert not (tmp_path / "lumina" / "memories" / "USER.md").exists()
```

- [ ] **Step 11: 运行测试验证通过**

Run: `uv run pytest tests/memory/test_lumina_memory.py -v`
Expected: PASS（所有测试，包括新写的 3 个和改写的 1 个）

- [ ] **Step 12: Commit**

```bash
git add src/secretary/memory/lumina_memory.py tests/memory/test_lumina_memory.py
git commit -m "refactor(memory): retire USER.md from LuminaMemory (统一归 ProfileService)"
```

---

## Task 2: MemoryTool 只保留 target=memory

**Files:**
- Modify: `src/secretary/agent/tools/memory_tools.py:45-96`
- Test: `tests/agent/test_loop_tools.py:9-17`

- [ ] **Step 1: 写失败测试 — MemoryTool 拒绝 target=user**

替换 `tests/agent/test_loop_tools.py:9-17` 的 `test_memory_tool_add`：

```python
def test_memory_tool_add_to_memory_target(tmp_path: Path) -> None:
    """MemoryTool 只支持 target=memory；target=user 应返回 failure。"""
    memory = LuminaMemory(tmp_path)
    tool = MemoryTool(memory)
    output = tool.execute(
        {"action": "add", "target": "memory", "text": "Timezone: Asia/Shanghai"},
        tmp_path,
    )
    assert "Asia/Shanghai" in memory.read_memory_md()
    assert output


def test_memory_tool_rejects_user_target(tmp_path: Path) -> None:
    """target=user 已退役，MemoryTool 应返回 ToolResult.failure。"""
    memory = LuminaMemory(tmp_path)
    tool = MemoryTool(memory)
    output = tool.execute(
        {"action": "add", "target": "user", "text": "Name: Alex"},
        tmp_path,
    )
    # mutate_memory 抛 ValueError → MemoryTool.execute 捕获并返回 ToolResult.failure
    assert isinstance(output, ToolResult) or "error" in str(output).lower()
    # 不应有任何 USER.md 被写入
    assert not (tmp_path / "memories" / "USER.md").exists()
```

在 `tests/agent/test_loop_tools.py:5` 的 import 追加 `ToolResult`：

```python
from secretary.agent.tools.base import Tool, ToolResult
from secretary.agent.tools.memory_tools import MemoryTool, SessionSearchTool
from secretary.memory.lumina_memory import LuminaMemory
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/agent/test_loop_tools.py -v`
Expected: `test_memory_tool_rejects_user_target` FAIL（当前 `target=user` 仍会写入 USER.md，返回成功字符串而非 ToolResult.failure）

- [ ] **Step 3: 修改 MemoryTool — target 枚举只留 memory，description 更新**

`src/secretary/agent/tools/memory_tools.py:45-96`，替换 MemoryTool 类整体：

```python
class MemoryTool(Tool):
    name = "memory"
    description = (
        "Manage durable cross-session MEMORY.md (environment/project facts). "
        "target=memory only; USER.md 已退役，用户个人事实请由对话推断自动写入用户画像。"
        "Actions: add, replace (requires old_text), remove (requires old_text)."
    )
    needs_confirmation = False
    risk_level = "low"
    read_only = False

    def __init__(self, memory: LuminaMemory) -> None:
        self._memory = memory

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "replace", "remove"],
                    "description": "Memory operation",
                },
                "target": {
                    "type": "string",
                    "enum": ["memory"],
                    "description": "memory=MEMORY.md (用户事实已改由画像自动记录，不再支持 user)",
                },
                "text": {"type": "string", "description": "Text to add or replacement text"},
                "old_text": {
                    "type": "string",
                    "description": "Substring to replace or remove (required for replace/remove)",
                },
            },
            "required": ["action", "target"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        try:
            return self._memory.mutate_memory(
                str(arguments.get("action", "")),
                str(arguments.get("target", "")),
                text=str(arguments.get("text", "")),
                old_text=str(arguments.get("old_text", "")),
            )
        except ValueError as exc:
            return ToolResult.failure(
                f"Error: {exc}",
                error_type="validation",
                retryable=False,
            )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/agent/test_loop_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/secretary/agent/tools/memory_tools.py tests/agent/test_loop_tools.py
git commit -m "refactor(tools): MemoryTool target enum drops user (退役 USER.md)"
```

---

## Task 3: BackgroundReviewService 不再 mutate_memory(target=user)

**Files:**
- Modify: `src/secretary/services/background_review.py:21-161`
- Test: 新建 `tests/services/test_background_review.py`

- [ ] **Step 1: 写失败测试 — target=user 时不调 mutate_memory，只调 _sync_profile_fact**

新建 `tests/services/test_background_review.py`：

```python
"""BackgroundReviewService 在 USER.md 退役后的行为。"""

from pathlib import Path
from unittest.mock import MagicMock

from secretary.services.background_review import BackgroundReviewService, ReviewDecision


def test_target_user_skips_mutate_memory_and_calls_profile_fact(tmp_path: Path) -> None:
    """target=user 时：不调 mutate_memory（会抛错），只调 _sync_profile_fact。"""
    memory = MagicMock()
    profile = MagicMock()
    svc = BackgroundReviewService(memory, profile_service=profile)

    decision = ReviewDecision(
        action="add", target="user", text="Name: Alex", old_text="", reason="user said name"
    )
    svc.apply_decision_for_tests(decision)

    # mutate_memory 不应被以 target=user 调用
    memory.mutate_memory.assert_not_called()
    # profile_service.append_chat_fact 应被调用一次，文本是 decision.text
    profile.append_chat_fact.assert_called_once_with("Name: Alex")


def test_target_memory_calls_mutate_memory_only(tmp_path: Path) -> None:
    """target=memory 时：只调 mutate_memory，不调 profile。"""
    memory = MagicMock()
    profile = MagicMock()
    svc = BackgroundReviewService(memory, profile_service=profile)

    decision = ReviewDecision(
        action="add", target="memory", text="Uses macOS", old_text="", reason="env fact"
    )
    svc.apply_decision_for_tests(decision)

    memory.mutate_memory.assert_called_once_with(
        "add", "memory", text="Uses macOS", old_text=""
    )
    profile.append_chat_fact.assert_not_called()


def test_target_user_replace_action_also_syncs_profile(tmp_path: Path) -> None:
    """target=user + action=replace 也应走 _sync_profile_fact。"""
    memory = MagicMock()
    profile = MagicMock()
    svc = BackgroundReviewService(memory, profile_service=profile)

    decision = ReviewDecision(
        action="replace", target="user", text="Name: Bob", old_text="Name: Alex", reason="rename"
    )
    svc.apply_decision_for_tests(decision)

    memory.mutate_memory.assert_not_called()
    profile.append_chat_fact.assert_called_once_with("Name: Bob")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/services/test_background_review.py -v`
Expected: FAIL（当前 `apply_decision_for_tests` 会调 `mutate_memory("add","user",...)`，但 mutate_memory 现在抛 ValueError——其实测试期望它根本不被调用，所以会因 mock.mutate_memory 被调用而失败）

- [ ] **Step 3: 修改 _REVIEW_SYSTEM 提示词 — 删去 target=user 分支**

`src/secretary/services/background_review.py:21-34`，替换为：

```python
_REVIEW_SYSTEM = """你是记忆整理器。根据本轮对话，判断是否应更新持久记忆 MEMORY.md。
只输出 JSON：
{"action":"none"|"add"|"replace","target":"memory","text":"","old_text":"","reason":""}

规则：
- target 只能是 "memory"；用户个人信息（姓名/职业/偏好/习惯/目标等）由系统自动写入用户画像，不要写入 MEMORY.md
- 只从 User 消息提取事实；禁止从 Assistant 回复中提取或固化（助手可能幻觉）
- 任务/项目/环境类稳定事实 → action=add, target=memory
- 只记录稳定、可复用的事实，不要记临时闲聊、单次问答
- 阅读书目、项目作者、文件列表等须由用户亲口说出；助手推断的 action=none
- 不确定时 action=none
- replace/remove 需要 old_text 精确匹配现有内容片段
- text 用简洁中文陈述句，不要引号套话
"""
```

- [ ] **Step 4: 修改 _run_review — target=user 时不调 mutate_memory**

`src/secretary/services/background_review.py:72-92`，替换 `_run_review` 方法：

```python
    def _run_review(self, user_message: str, assistant_reply: str, llm_config: LlmConfig) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            decision = self._classify(user_message, assistant_reply, llm_config)
            if decision.action == "none":
                return
            self._apply_decision(decision)
            logger.info("background review updated %s: %s", decision.target, decision.reason)
            self._compress.compress_if_needed(llm_config)
        except (AgentError, ValueError) as exc:
            logger.warning("background review skipped: %s", exc)
        finally:
            self._lock.release()

    def _apply_decision(self, decision: ReviewDecision) -> None:
        """USER.md 退役：target=user 只走 profile；target=memory 走 mutate_memory。"""
        if decision.target == "user":
            if decision.action in {"add", "replace"}:
                self._sync_profile_fact(decision.text)
            return
        self._memory.mutate_memory(
            decision.action,
            decision.target,
            text=decision.text,
            old_text=decision.old_text,
        )
```

- [ ] **Step 5: 修改 apply_decision_for_tests — 复用 _apply_decision**

`src/secretary/services/background_review.py:126-136`，替换为：

```python
    def apply_decision_for_tests(self, decision: ReviewDecision) -> None:
        if decision.action == "none":
            return
        self._apply_decision(decision)
```

- [ ] **Step 6: 修改 _parse_review_json — target=user 不再强制改 memory，保留原值**

`src/secretary/services/background_review.py:139-161`，把第 153-154 行的：

```python
    if target not in {"memory", "user"}:
        target = "memory"
```

保持不变（仍允许 LLM 返回 `target=user`，由 `_apply_decision` 路由到 profile）。

- [ ] **Step 7: 运行测试验证通过**

Run: `uv run pytest tests/services/test_background_review.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/secretary/services/background_review.py tests/services/test_background_review.py
git commit -m "refactor(review): target=user routes to ProfileService only (退役 USER.md 双写)"
```

---

## Task 4: MemoryCompressionService 只压缩 MEMORY.md

**Files:**
- Modify: `src/secretary/services/memory_compress.py:1-51`
- Test: `tests/services/test_memory_compress.py`

- [ ] **Step 1: 先看现有测试**

Run: `cat tests/services/test_memory_compress.py`

如果测试里有 `write_user_md` / `read_user_md` 调用，需要改。

- [ ] **Step 2: 写失败测试 — USER.md 不再被压缩**

追加到 `tests/services/test_memory_compress.py`（若文件不存在则创建）：

```python
"""MemoryCompressionService 只压缩 MEMORY.md；USER.md 已退役。"""

from pathlib import Path
from unittest.mock import MagicMock

from secretary.services.memory_compress import MemoryCompressionService


def test_compress_if_needed_skips_user_md(tmp_path: Path) -> None:
    """compress_if_needed 只压缩 MEMORY.md，不再读 USER.md。"""
    memory = MagicMock()
    memory.read_memory_md.return_value = ""
    memory.read_user_md = MagicMock()  # 不应被调用
    svc = MemoryCompressionService(memory)

    changed = svc.compress_if_needed(llm_config=None)

    assert changed is False
    memory.read_memory_md.assert_called_once()
    memory.read_user_md.assert_not_called()
```

- [ ] **Step 3: 运行测试验证失败**

Run: `uv run pytest tests/services/test_memory_compress.py::test_compress_if_needed_skips_user_md -v`
Expected: FAIL（`MemoryCompressionService` 没有 `read_user_md` 属性时会 AttributeError；或当前实现调用了 `read_user_md`）

- [ ] **Step 4: 修改 memory_compress.py — 删除 USER.md 分支**

`src/secretary/services/memory_compress.py:1-51`，替换整个文件：

```python
"""Semantic compression for durable MEMORY.md when near size limits.

USER.md 已退役；用户事实由 ProfileService 管理，不在本服务范围内。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError
from secretary.memory.lumina_memory import MEMORY_MD_MAX_CHARS, LuminaMemory

logger = logging.getLogger(__name__)

_COMPRESS_THRESHOLD = 0.88

_COMPRESS_SYSTEM = """你是持久记忆压缩器。将下面的记忆文本压缩到更短，但必须保留所有稳定、可复用的事实。
要求：
- 删除重复、近义冗余、过时临时信息
- 保留任务、项目、环境类稳定事实与重要结论
- 输出长度不超过 {max_chars} 个字符（中文按字计）
- 直接输出压缩后的全文，不要解释、不要 JSON"""


class MemoryCompressionService:
    def __init__(self, memory: LuminaMemory) -> None:
        self._memory = memory

    def compress_if_needed(self, llm_config: LlmConfig | None) -> bool:
        if llm_config is None:
            return False
        return self._compress_target(
            llm_config,
            read=self._memory.read_memory_md,
            write=self._memory.write_memory_md,
            max_chars=MEMORY_MD_MAX_CHARS,
            label="MEMORY.md",
        )

    def _compress_target(
        self,
        llm_config: LlmConfig,
        *,
        read: Callable[[], str],
        write: Callable[[str], None],
        max_chars: int,
        label: str,
    ) -> bool:
        content = read().strip()
        if not content:
            return False
        threshold = int(max_chars * _COMPRESS_THRESHOLD)
        if len(content) <= threshold:
            return False
        try:
            compressed = chat_completion(
                llm_config,
                [
                    {
                        "role": "system",
                        "content": _COMPRESS_SYSTEM.format(max_chars=max_chars),
                    },
                    {"role": "user", "content": content},
                ],
                temperature=0.0,
                timeout=60.0,
            ).strip()
        except AgentError as exc:
            logger.warning("memory compress skipped for %s: %s", label, exc)
            return False
        if not compressed or len(compressed) >= len(content):
            return False
        write(compressed)
        logger.info("compressed %s: %s -> %s chars", label, len(content), len(compressed))
        return True
```

- [ ] **Step 5: 运行测试验证通过**

Run: `uv run pytest tests/services/test_memory_compress.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/secretary/services/memory_compress.py tests/services/test_memory_compress.py
git commit -m "refactor(compress): drop USER.md compression branch (退役 USER.md)"
```

---

## Task 5: ScheduledThinkService target 白名单去掉 user

**Files:**
- Modify: `src/secretary/services/scheduled_think.py:170-189`
- Test: 现有 scheduled_think 测试（若有）

- [ ] **Step 1: 查看现有 scheduled_think 测试**

Run: `uv run pytest tests/services/ -k "think or scheduled" --collect-only -q`

若无相关测试，跳过测试步骤，直接改实现。

- [ ] **Step 2: 修改 _apply_result — target=user 跳过**

`src/secretary/services/scheduled_think.py:170-189`，把：

```python
                target = str(item.get("target", "memory")).strip().lower()
                if target not in {"memory", "user"}:
                    target = "memory"
                self._memory.mutate_memory(
                    action,
                    target,
                    text=str(item.get("text", "")),
                    old_text=str(item.get("old_text", "")),
                )
                applied += 1
```

改为：

```python
                target = str(item.get("target", "memory")).strip().lower()
                # USER.md 已退役；target=user 跳过（用户事实由画像自动记录）
                if target not in {"memory"}:
                    continue
                self._memory.mutate_memory(
                    action,
                    target,
                    text=str(item.get("text", "")),
                    old_text=str(item.get("old_text", "")),
                )
                applied += 1
```

- [ ] **Step 3: 修改 _THINK_SYSTEM 提示词（如有）**

`src/secretary/services/scheduled_think.py:29` 附近，把提示词模板里：

```
{"insights":["..."], "updates":[{"action":"none"|"add"|"replace","target":"memory"|"user","text":"","old_text":""}]}
```

改为：

```
{"insights":["..."], "updates":[{"action":"none"|"add"|"replace","target":"memory","text":"","old_text":""}]}
```

- [ ] **Step 4: 运行相关测试**

Run: `uv run pytest tests/services/ -k "think or scheduled" -v`
Expected: PASS（无回归）

若无相关测试，跑全量 agent 测试：

Run: `uv run pytest tests/agent/ tests/services/ -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/secretary/services/scheduled_think.py
git commit -m "refactor(think): drop target=user from scheduled think (退役 USER.md)"
```

---

## Task 6: API 端点 /api/memory/durable 去掉 user_md

**Files:**
- Modify: `src/secretary/api/app.py:1048-1089`
- Test: `tests/api/test_app.py:53-68`

- [ ] **Step 1: 写失败测试 — durable 端点不再返回 user_md**

替换 `tests/api/test_app.py:53-68` 的 `test_durable_memory_endpoint`：

```python
def test_durable_memory_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/memory/durable")
    assert response.status_code == 200
    payload = response.json()
    assert "memory_md" in payload
    # USER.md 已退役，不再返回
    assert "user_md" not in payload

    put_response = client.put(
        "/api/memory/durable",
        json={"memory_md": "Test env fact"},
    )
    assert put_response.status_code == 200
    updated = put_response.json()
    assert updated["memory_md"] == "Test env fact"
    assert "user_md" not in updated
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/api/test_app.py::test_durable_memory_endpoint -v`
Expected: FAIL（当前响应仍含 `user_md`）

- [ ] **Step 3: 修改 app.py — GET/PUT 去掉 user_md**

`src/secretary/api/app.py:1048-1071`，替换为：

```python
@app.get("/api/memory/durable")
def get_durable_memory(request: Request) -> dict[str, str]:
    chat_service: ChatService = _svc(request).chat_service
    memory = chat_service.memory
    return {"memory_md": memory.read_memory_md()}


@app.put("/api/memory/durable")
def update_durable_memory(
    request: Request, body: dict[str, str]
) -> dict[str, str]:
    chat_service: ChatService = _svc(request).chat_service
    memory = chat_service.memory
    if "memory_md" in body:
        memory.write_memory_md(body["memory_md"])
    return {"memory_md": memory.read_memory_md()}
```

- [ ] **Step 4: 修改 /api/memory/import-hermes 响应 — 去掉 user_md**

`src/secretary/api/app.py:1074-1089`，替换为：

```python
@app.post("/api/memory/import-hermes")
def import_memory_from_hermes(request: Request) -> dict[str, object]:
    """One-shot import of Hermes MEMORY.md into ~/.lumina/memories/.

    USER.md 已退役，不再导入；用户事实请通过 /api/profile 编辑。
    """
    chat_service: ChatService = _svc(request).chat_service
    memory = chat_service.memory
    imported = memory.import_from_hermes()
    if not imported:
        raise HTTPException(
            status_code=404,
            detail="未找到可导入的 Hermes 记忆文件（~/.hermes/MEMORY.md）",
        )
    return {
        "imported": imported,
        "memory_md": memory.read_memory_md(),
    }
```

- [ ] **Step 5: 运行测试验证通过**

Run: `uv run pytest tests/api/test_app.py::test_durable_memory_endpoint -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/secretary/api/app.py tests/api/test_app.py
git commit -m "refactor(api): /api/memory/durable drops user_md (退役 USER.md)"
```

---

## Task 7: 系统提示词规则去掉 durable memory（USER.md）

**Files:**
- Modify: `src/secretary/agent/chat_service.py:1651-1652`

- [ ] **Step 1: 修改第 1651 行规则**

`src/secretary/agent/chat_service.py:1651-1652`，把：

```python
            "- 用户在本轮明确提供的个人信息，应在回复后写入 durable memory（USER.md）与用户画像\n"
            "- 完成复杂任务后，总结关键事实到 durable memory\n"
```

改为：

```python
            "- 用户在本轮明确提供的个人信息，会在后台自动写入用户画像（profile），无需手动调用 memory 工具\n"
            "- 完成复杂任务后，总结关键事实到 durable memory（target=memory）\n"
```

- [ ] **Step 2: 运行 chat_service 相关测试**

Run: `uv run pytest tests/agent/test_chat_service.py -v --tb=short`
Expected: PASS（系统提示词文本改动一般不破坏测试）

- [ ] **Step 3: Commit**

```bash
git add src/secretary/agent/chat_service.py
git commit -m "refactor(prompt): drop USER.md from system prompt rules (退役 USER.md)"
```

---

## Task 8: 前端 settings.js 去掉 USER.md 编辑框

**Files:**
- Modify: `desktop/ui/settings.js:18-19, 77-78, 836-870, 1306-1324`
- Modify: `desktop/ui/index.html`（版本号 bump）

- [ ] **Step 1: 删除 durableUserMd 变量声明**

`desktop/ui/settings.js:18-19`，删除：

```javascript
  let durableMemoryMd = "";
  let durableUserMd = "";
```

只留：

```javascript
  let durableMemoryMd = "";
```

- [ ] **Step 2: 修改 loadSettings — 不读 durable.user_md**

`desktop/ui/settings.js:77-78`，把：

```javascript
    durableMemoryMd = durable.memory_md || "";
    durableUserMd = durable.user_md || "";
```

改为：

```javascript
    durableMemoryMd = durable.memory_md || "";
```

- [ ] **Step 3: 修改 renderAgentMemoryPane — 删去 USER.md 编辑框**

`desktop/ui/settings.js:836-870`，替换整个 `renderAgentMemoryPane` 函数：

```javascript
  function renderAgentMemoryPane() {
    const bg = backgroundTasks || {};
    const thinkInfo = bg.think_enabled
      ? `每 ${bg.think_interval_hours || 6} 小时 · 上次 ${bg.last_think_at ? escapeHtml(String(bg.last_think_at).slice(0, 16)) : "尚未运行"}`
      : "已关闭";
    const summaryInfo = bg.memory_summary_enabled
      ? `每天 ${bg.memory_summary_hour ?? 23}:00 · 上次 ${bg.last_summary_date ? escapeHtml(String(bg.last_summary_date)) : "尚未运行"}`
      : "已关闭";

    contentEl.innerHTML = `
      <div class="settings-pane profile-edit-pane">
        <header class="settings-pane-head">
          <h3>持久记忆</h3>
          <p>灵犀使用 MEMORY.md 记录任务/项目/环境事实与每日会话摘要，每次对话开始时注入系统提示。Agent 也可通过 memory 工具自动更新。用户个人事实（姓名/偏好/习惯等）请编辑"个人画像"。</p>
        </header>
        <div class="platform-meta">
          <p>后台思考：${thinkInfo}</p>
          <p>记忆摘要：${summaryInfo}</p>
        </div>
        <label class="settings-field" for="durable-memory-editor">
          <span>MEMORY.md（环境与项目事实，最多 2200 字）</span>
          <textarea id="durable-memory-editor" class="profile-editor" rows="14">${escapeHtml(durableMemoryMd)}</textarea>
        </label>
        <div class="platform-actions">
          <button class="btn-text save-btn" type="button" id="btn-save-durable-memory">保存</button>
        </div>
        <div id="durable-memory-feedback" class="platform-feedback" hidden></div>
      </div>
    `;
    document.getElementById("btn-save-durable-memory").addEventListener("click", saveDurableMemory);
  }
```

- [ ] **Step 4: 修改 saveDurableMemory — 只提交 memory_md**

`desktop/ui/settings.js:1306-1324`，替换整个 `saveDurableMemory` 函数：

```javascript
  async function saveDurableMemory() {
    const memoryEditor = document.getElementById("durable-memory-editor");
    const feedback = document.getElementById("durable-memory-feedback");
    if (!memoryEditor || !feedback) return;
    try {
      const updated = await window.SecretaryAPI.request("PUT", "/api/memory/durable", {
        memory_md: memoryEditor.value,
      });
      durableMemoryMd = updated.memory_md || "";
      memoryEditor.value = durableMemoryMd;
      showFeedback(feedback, "success", "持久记忆已保存");
    } catch (error) {
      showFeedback(feedback, "error", `保存失败：${error.message}`);
    }
  }
```

- [ ] **Step 5: bump settings.js 版本号**

`desktop/ui/index.html:248`，把：

```html
    <script src="/assets/settings.js?v=15"></script>
```

改为：

```html
    <script src="/assets/settings.js?v=16"></script>
```

- [ ] **Step 6: Commit**

```bash
git add desktop/ui/settings.js desktop/ui/index.html
git commit -m "refactor(ui): drop USER.md editor from memory pane (退役 USER.md)"
```

---

## Task 9: 全量回归测试

**Files:** 无（仅运行）

- [ ] **Step 1: ruff lint**

Run: `uv run ruff check src tests`
Expected: All checks passed

- [ ] **Step 2: 全量 pytest**

Run: `uv run pytest --tb=short`
Expected: 全部 PASS（允许 2 skipped）

- [ ] **Step 3: mypy（容忍既有错误）**

Run: `uv run mypy src`
Expected: 不新增错误（USER.md 相关删除应减少错误，不增加）

- [ ] **Step 4: e2e 测试**

Run: `uv run pytest tests/e2e/ -x --tb=short`
Expected: 全部 PASS

- [ ] **Step 5: 若有失败，修复后追加 commit**

若 ruff/pytest/mypy 报错，针对性修复，commit message 用 `fix: <具体问题>`。

- [ ] **Step 6: 最终 commit（若 Step 5 有改动）**

```bash
git add <修复的文件>
git commit -m "fix: regression after USER.md retirement"
```

---

## Self-Review

### Spec coverage
- ✅ LuminaMemory 退役 USER.md → Task 1
- ✅ MemoryTool target 枚举 → Task 2
- ✅ BackgroundReviewService 不双写 → Task 3
- ✅ MemoryCompressionService 只压 MEMORY.md → Task 4
- ✅ ScheduledThinkService 白名单 → Task 5
- ✅ API 端点去掉 user_md → Task 6
- ✅ 系统提示词规则 → Task 7
- ✅ 前端编辑框 → Task 8
- ✅ 全量回归 → Task 9

### Placeholder scan
无 TBD/TODO/placeholder。每个 step 都有具体代码或命令。

### Type consistency
- `mutate_memory(action, target, *, text, old_text)` 签名不变，只是 target 白名单收窄
- `ReviewDecision` dataclass 字段不变
- `BackgroundReviewService._apply_decision` 是新方法，被 `_run_review` 和 `apply_decision_for_tests` 共用
- `import_from_hermes` 返回类型仍为 `dict[str, str]`，只是 key 集合从 `{"memory_md","user_md"}` 收窄为 `{"memory_md"}`
- 前端 `durableUserMd` 变量删除，`saveDurableMemory` 不再引用

### 风险点
1. **Agent 旧提示词记忆**：如果 Agent 在历史会话里学过调用 `memory(target=user)`，新代码会返回 `ToolResult.failure`。这是预期行为，Agent 应能根据错误信息调整。系统提示词 Task 7 已更新规则，明确告诉 Agent 不要再调 user target。
2. **既有 `~/.lumina/memories/USER.md` 文件**：不主动删除，但不再读取。用户若想迁移，可手动复制内容到 `~/.lumina/profile_chat_facts.md` 或通过设置 → 个人画像 编辑。
3. **Hermes 导入**：旧 Hermes 用户的 USER.md 不会被导入。这是预期行为；提示文案已说明"用户事实请通过 /api/profile 编辑"。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-17-retire-user-md.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
