# F21 反思记忆（Reflexion-style）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reflexion-style memory system that detects failed Build-profile turns, spawns a reflect sub-agent to generate structured lessons, stores them in the extended episodes table, and injects top-3 relevant lessons into future turns' system prompts.

**Architecture:** Heuristic failure detection (`ReflectionTrigger`) → spawn `reflect` sub-agent (read-only, 4 steps, JSON output) via existing `SubAgentRunner` → write structured reflection to extended `episodes` table (new columns: `failure_mode`, `reflection_text`, `thread_id`) → at turn start, retrieve top-3 failed episodes via FTS5 and inject into system prompt's "## 历史教训" section.

**Tech Stack:** Python 3.12, SQLite + FTS5, FastAPI, existing SubAgentRunner/LuminaMemory infrastructure

**Design doc:** [docs/superpowers/specs/2026-07-14-reflection-memory-design.md](../specs/2026-07-14-reflection-memory-design.md)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/secretary/memory/lumina_memory.py` | Modify | Extend episodes schema + `save_episode` / `search_episodes` signatures |
| `src/secretary/agent/reflection/__init__.py` | Create | Package init |
| `src/secretary/agent/reflection/trigger.py` | Create | `ReflectionTrigger` + `FailureSignal` — heuristic failure detection |
| `src/secretary/agent/reflection/runner.py` | Create | `ReflectionRunner` — wraps `SubAgentRunner` to spawn reflect sub-agent |
| `src/secretary/agent/subagent/registry.py` | Modify | Register `reflect` archetype (prompt + tools + max_steps) |
| `src/secretary/agent/subagent/policy.py` | Modify | Add `REFLECT_MAX_STEPS` + add "reflect" to `BUILTIN_ARCHETYPES` |
| `src/secretary/agent/chat_service.py` | Modify | Trigger reflection in `_finalize_agent_result` + inject in `_build_system_prompt` |
| `tests/agent/test_reflection_trigger.py` | Create | Unit tests for `ReflectionTrigger` |
| `tests/services/test_lumina_memory.py` | Modify | Tests for extended `save_episode` / `search_episodes` |
| `tests/agent/test_chat_service.py` | Modify | Tests for reflection trigger + injection |
| `tests/agent/subagent/test_runner.py` | Modify | Test for reflect archetype |

---

## Task 1: Extend episodes table schema + migration

**Files:**
- Modify: `src/secretary/memory/lumina_memory.py:181-247` (`_init_session_schema`)
- Test: `tests/services/test_lumina_memory.py`

- [ ] **Step 1: Write the failing test for schema migration**

Add to `tests/services/test_lumina_memory.py`:

```python
def test_episodes_table_has_reflection_columns(tmp_path):
    """F21: episodes table must have failure_mode, reflection_text, thread_id columns."""
    mem = LuminaMemory(tmp_path)
    with mem._connect_session() as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(episodes)")}
    assert "failure_mode" in cols
    assert "reflection_text" in cols
    assert "thread_id" in cols


def test_episodes_fts_indexes_reflection_text(tmp_path):
    """F21: episodes_fts must index reflection_text for keyword search."""
    mem = LuminaMemory(tmp_path)
    with mem._connect_session() as conn:
        # FTS5 table info — columns are accessible via pragma
        fts_cols = {row["name"] for row in conn.execute("PRAGMA table_info(episodes_fts)")}
    assert "reflection_text" in fts_cols
    assert "failure_mode" in fts_cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_lumina_memory.py::test_episodes_table_has_reflection_columns tests/services/test_lumina_memory.py::test_episodes_fts_indexes_reflection_text -v`
Expected: FAIL — columns not found

- [ ] **Step 3: Extend the schema in `_init_session_schema`**

In `src/secretary/memory/lumina_memory.py`, modify the `episodes` CREATE TABLE and FTS5 definitions inside `_init_session_schema` (around line 219-245). Replace the episodes + FTS5 block with:

```python
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    result TEXT,
                    success INTEGER NOT NULL DEFAULT 0,
                    tools_used TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    failure_mode TEXT,
                    reflection_text TEXT,
                    thread_id TEXT
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                    episode_id UNINDEXED,
                    task,
                    result,
                    failure_mode UNINDEXED,
                    reflection_text,
                    content='episodes',
                    content_rowid='rowid'
                );
```

Then update the triggers (ep_ai / ep_ad) to include the new columns:

```sql
                CREATE TRIGGER IF NOT EXISTS ep_ai AFTER INSERT ON episodes BEGIN
                    INSERT INTO episodes_fts(rowid, episode_id, task, result, failure_mode, reflection_text)
                    VALUES (new.rowid, new.episode_id, new.task, new.result, new.failure_mode, new.reflection_text);
                END;

                CREATE TRIGGER IF NOT EXISTS ep_ad AFTER DELETE ON episodes BEGIN
                    INSERT INTO episodes_fts(episodes_fts, rowid, episode_id, task, result, failure_mode, reflection_text)
                    VALUES ('delete', old.rowid, old.episode_id, old.task, old.result, old.failure_mode, old.reflection_text);
                END;
```

- [ ] **Step 4: Add migration for existing databases**

After the `executescript` in `_init_session_schema`, add migration logic (SQLite ALTER TABLE ADD COLUMN is idempotent-safe with try/except):

```python
    def _migrate_episodes_schema(self) -> None:
        """Add F21 columns to existing episodes table (idempotent)."""
        new_columns = ["failure_mode", "reflection_text", "thread_id"]
        with self._connect_session() as conn:
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(episodes)")}
            for col in new_columns:
                if col not in existing:
                    conn.execute(f"ALTER TABLE episodes ADD COLUMN {col} TEXT")
```

Call `self._migrate_episodes_schema()` at the end of `_init_session_schema`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/services/test_lumina_memory.py::test_episodes_table_has_reflection_columns tests/services/test_lumina_memory.py::test_episodes_fts_indexes_reflection_text -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/secretary/memory/lumina_memory.py tests/services/test_lumina_memory.py
git commit -m "feat(memory): extend episodes table with reflection columns (F21)"
```

---

## Task 2: Extend save_episode + search_episodes signatures

**Files:**
- Modify: `src/secretary/memory/lumina_memory.py:330-399` (`save_episode` / `search_episodes`)
- Test: `tests/services/test_lumina_memory.py`

- [ ] **Step 1: Write the failing test for extended save_episode**

Add to `tests/services/test_lumina_memory.py`:

```python
def test_save_episode_with_reflection_fields(tmp_path):
    """F21: save_episode must accept failure_mode, reflection_text, thread_id."""
    mem = LuminaMemory(tmp_path)
    mem.save_episode(
        episode_id="ep1",
        task="test task",
        steps=[{"thought": "thinking", "tool": "file_read", "output": "ok"}],
        result="result text",
        success=False,
        tools_used=["file_read"],
        failure_mode="verify_failed",
        reflection_text='{"failure_summary": "bad patch", "lesson": "check first"}',
        thread_id="thread-1",
    )
    with mem._connect_session() as conn:
        row = conn.execute("SELECT * FROM episodes WHERE episode_id = ?", ("ep1",)).fetchone()
    assert row["success"] == 0
    assert row["failure_mode"] == "verify_failed"
    assert "bad patch" in row["reflection_text"]
    assert row["thread_id"] == "thread-1"


def test_search_episodes_success_only_filter(tmp_path):
    """F21: search_episodes must support success_only filter."""
    mem = LuminaMemory(tmp_path)
    mem.save_episode("ep1", "deploy task", [], "done", True, ["shell"])
    mem.save_episode("ep2", "deploy task", [], "failed", False, ["patch"],
                     failure_mode="grounding_failed")
    # success_only=False → only failures
    failures = mem.search_episodes("deploy", limit=5, success_only=False)
    assert len(failures) == 1
    assert failures[0]["episode_id"] == "ep2"
    # success_only=True → only successes
    successes = mem.search_episodes("deploy", limit=5, success_only=True)
    assert len(successes) == 1
    assert successes[0]["episode_id"] == "ep1"
    # success_only=None → all
    all_eps = mem.search_episodes("deploy", limit=5, success_only=None)
    assert len(all_eps) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_lumina_memory.py::test_save_episode_with_reflection_fields tests/services/test_lumina_memory.py::test_search_episodes_success_only_filter -v`
Expected: FAIL — unexpected keyword argument

- [ ] **Step 3: Extend save_episode signature**

In `src/secretary/memory/lumina_memory.py`, replace the `save_episode` method (line 330-359) with:

```python
    def save_episode(
        self,
        episode_id: str,
        task: str,
        steps: list[dict[str, str]],
        result: str,
        success: bool,
        tools_used: list[str],
        *,
        failure_mode: str | None = None,
        reflection_text: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        with self._connect_session() as conn:
            conn.execute(
                """
                INSERT INTO episodes (episode_id, task, steps_json, result, success, tools_used, created_at, failure_mode, reflection_text, thread_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id) DO UPDATE SET
                    steps_json=excluded.steps_json,
                    result=excluded.result,
                    success=excluded.success,
                    tools_used=excluded.tools_used,
                    failure_mode=excluded.failure_mode,
                    reflection_text=excluded.reflection_text,
                    thread_id=excluded.thread_id
                """,
                (
                    episode_id,
                    task[:500],
                    json.dumps(steps, ensure_ascii=False),
                    result[:2000],
                    1 if success else 0,
                    json.dumps(tools_used, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                    failure_mode,
                    reflection_text,
                    thread_id,
                ),
            )
```

- [ ] **Step 4: Extend search_episodes signature**

Replace the `search_episodes` method (line 361-399) with:

```python
    def search_episodes(
        self,
        query: str,
        limit: int = 5,
        *,
        success_only: bool | None = None,
    ) -> list[dict[str, object]]:
        safe_query = _sanitize_fts(query)
        success_filter = ""
        params: list[object] = [safe_query]
        if success_only is not None:
            success_filter = " AND e.success = ?"
            params.append(1 if success_only else 0)
        params.append(limit)

        with self._connect_session() as conn:
            rows = conn.execute(
                f"""
                SELECT e.episode_id, e.task, e.result, e.success, e.tools_used,
                       e.created_at, e.failure_mode, e.reflection_text, e.thread_id
                FROM episodes_fts f
                JOIN episodes e ON e.rowid = f.rowid
                WHERE episodes_fts MATCH ?{success_filter}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            ).fetchall()
        if not rows:
            pattern = f"%{query}%"
            like_params: list[object] = [pattern, pattern]
            like_success = ""
            if success_only is not None:
                like_success = " AND success = ?"
                like_params.append(1 if success_only else 0)
            like_params.append(limit)
            with self._connect_session() as conn:
                rows = conn.execute(
                    f"""
                    SELECT episode_id, task, result, success, tools_used,
                           created_at, failure_mode, reflection_text, thread_id
                    FROM episodes
                    WHERE (task LIKE ? OR result LIKE ?){like_success}
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    like_params,
                ).fetchall()
        items: list[dict[str, object]] = [
            {
                "episode_id": str(r["episode_id"]),
                "task": str(r["task"]),
                "result": str(r["result"])[:500] if r["result"] else "",
                "success": bool(r["success"]),
                "tools_used": str(r["tools_used"]),
                "created_at": str(r["created_at"]),
                "failure_mode": str(r["failure_mode"]) if r["failure_mode"] else None,
                "reflection_text": str(r["reflection_text"]) if r["reflection_text"] else None,
                "thread_id": str(r["thread_id"]) if r["thread_id"] else None,
            }
            for r in rows
        ]
        return items
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/services/test_lumina_memory.py::test_save_episode_with_reflection_fields tests/services/test_lumina_memory.py::test_search_episodes_success_only_filter -v`
Expected: PASS

- [ ] **Step 6: Run full memory test suite to verify no regression**

Run: `uv run pytest tests/services/test_lumina_memory.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/secretary/memory/lumina_memory.py tests/services/test_lumina_memory.py
git commit -m "feat(memory): extend save_episode/search_episodes with reflection fields (F21)"
```

---

## Task 3: Create ReflectionTrigger (failure detection)

**Files:**
- Create: `src/secretary/agent/reflection/__init__.py`
- Create: `src/secretary/agent/reflection/trigger.py`
- Test: `tests/agent/test_reflection_trigger.py`

- [ ] **Step 1: Create the reflection package**

Create `src/secretary/agent/reflection/__init__.py`:

```python
"""F21 Reflexion-style memory: failure detection and reflection generation."""

from secretary.agent.reflection.trigger import FailureSignal, ReflectionTrigger

__all__ = ["FailureSignal", "ReflectionTrigger"]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/agent/test_reflection_trigger.py`:

```python
"""Tests for F21 ReflectionTrigger — heuristic failure detection."""

from __future__ import annotations

from secretary.agent.reflection import FailureSignal, ReflectionTrigger


def _make_loop_result(
    reply: str = "done",
    total_steps: int = 3,
    cancelled: bool = False,
    grounding_verified: bool = True,
    used_tools: list[str] | None = None,
):
    """Build a minimal LoopResult-like object for testing."""
    from secretary.agent.loop import LoopResult

    return LoopResult(
        reply=reply,
        steps=[],
        used_tools=used_tools or [],
        total_steps=total_steps,
        cancelled=cancelled,
        grounding_verified=grounding_verified,
    )


def test_no_failure_returns_none():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result(success_ok=True)
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="done",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is None


def test_max_steps_exhausted():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result(total_steps=20)
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="incomplete",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is not None
    assert signal.mode == "max_steps_exhausted"


def test_grounding_failed():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result(grounding_verified=False)
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="unverified reply",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is not None
    assert signal.mode == "grounding_failed"


def test_turn_aborted():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result(cancelled=True)
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="",
        loop_result=result,
        turn_status="cancelled",
        tool_call_history=[],
    )
    assert signal is not None
    assert signal.mode == "turn_aborted"


def test_user_correction_keyword():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result()
    signal = trigger.evaluate(
        profile="build",
        user_message="不对，重新做",
        raw_reply="previous reply",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is not None
    assert signal.mode == "user_correction"


def test_user_correction_not_in_ask_profile():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result()
    signal = trigger.evaluate(
        profile="ask",
        user_message="不对",
        raw_reply="reply",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is None


def test_verify_failed_detection():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result()
    tool_history = [
        {"name": "spawn_subagent", "arguments": {"archetype": "verify"},
         "output": "Pass: False\nIssues found: test missing"},
    ]
    signal = trigger.evaluate(
        profile="build",
        user_message="implement feature",
        raw_reply="done",
        loop_result=result,
        turn_status="completed",
        tool_call_history=tool_history,
    )
    assert signal is not None
    assert signal.mode == "verify_failed"
    assert signal.verify_issues is not None


def test_priority_short_circuit_max_steps_over_verify():
    """F4 (max_steps) should take priority over F2 (verify_failed)."""
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result(total_steps=20)
    tool_history = [
        {"name": "spawn_subagent", "arguments": {"archetype": "verify"},
         "output": "Pass: False"},
    ]
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="",
        loop_result=result,
        turn_status="completed",
        tool_call_history=tool_history,
    )
    assert signal is not None
    assert signal.mode == "max_steps_exhausted"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_reflection_trigger.py -v`
Expected: FAIL — module not found

- [ ] **Step 4: Implement ReflectionTrigger**

Create `src/secretary/agent/reflection/trigger.py`:

```python
"""F21 Reflexion: heuristic failure detection for Build-profile turns.

Evaluates a completed turn against 5 failure signals (priority order:
F4 max_steps → F2 verify_failed → F1 user_correction → F3 grounding → F5 aborted).
Returns the first matching FailureSignal, or None if no failure detected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from secretary.agent.loop import LoopResult

logger = logging.getLogger(__name__)

# F1: user correction keywords (Chinese + English)
_CORRECTION_KEYWORDS = frozenset({
    "不对", "错了", "重新", "撤销", "不要这样", "不要这样改", "这不是我要的",
    "revert", "rollback", "undo", "redo",
})

# F2: verify sub-agent failure markers
_VERIFY_FAIL_MARKERS = ("pass: false", "fail", "issues found")


@dataclass
class FailureSignal:
    """Detected failure context, passed to the reflect sub-agent."""

    mode: str  # user_correction | verify_failed | grounding_failed | max_steps_exhausted | turn_aborted
    summary: str
    user_message: str
    raw_reply: str
    tool_calls_summary: list[str] = field(default_factory=list)
    verify_issues: str | None = None


class ReflectionTrigger:
    """Heuristic failure detector. Stateless; safe to reuse across turns."""

    def __init__(self, max_steps: int = 20) -> None:
        self._max_steps = max_steps

    def evaluate(
        self,
        *,
        profile: str,
        user_message: str,
        raw_reply: str,
        loop_result: LoopResult,
        turn_status: str,
        tool_call_history: list[dict[str, Any]],
    ) -> FailureSignal | None:
        """Check failure signals in priority order. Returns first match or None."""
        # Only Build profile triggers reflection
        if profile != "build":
            return None

        tool_summary = self._summarize_tool_calls(tool_call_history)

        # F4: max steps exhausted (most fundamental failure)
        if loop_result.total_steps >= self._max_steps:
            return FailureSignal(
                mode="max_steps_exhausted",
                summary=f"Turn exhausted all {self._max_steps} steps without finalizing",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
            )

        # F2: verify sub-agent returned Fail
        verify_issues = self._check_verify_failure(tool_call_history)
        if verify_issues is not None:
            return FailureSignal(
                mode="verify_failed",
                summary="Verify sub-agent reported failure",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
                verify_issues=verify_issues,
            )

        # F1: user correction keyword (only in Build)
        if self._has_correction_keyword(user_message):
            return FailureSignal(
                mode="user_correction",
                summary="User explicitly corrected the previous turn",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
            )

        # F3: grounding not verified
        if not loop_result.grounding_verified:
            return FailureSignal(
                mode="grounding_failed",
                summary="Reply failed grounding verification",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
            )

        # F5: turn aborted (cancelled or failed)
        if loop_result.cancelled or turn_status in ("failed", "cancelled"):
            return FailureSignal(
                mode="turn_aborted",
                summary=f"Turn ended with status: {turn_status}",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
            )

        return None

    def _has_correction_keyword(self, message: str) -> bool:
        lower = message.lower()
        return any(kw in lower for kw in _CORRECTION_KEYWORDS)

    def _check_verify_failure(self, tool_history: list[dict[str, Any]]) -> str | None:
        """Scan tool calls for verify sub-agent failures. Returns issues text or None."""
        for call in tool_history:
            args = call.get("arguments", {})
            if args.get("archetype") != "verify":
                continue
            output = str(call.get("output", "")).lower()
            if any(marker in output for marker in _VERIFY_FAIL_MARKERS):
                return str(call.get("output", ""))
        return None

    def _summarize_tool_calls(self, tool_history: list[dict[str, Any]]) -> list[str]:
        """Build compact summaries of tool calls for the reflector."""
        summaries: list[str] = []
        for call in tool_history:
            name = call.get("name", "unknown")
            output = str(call.get("output", ""))[:150]
            summaries.append(f"{name}: {output}")
        return summaries
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_reflection_trigger.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/secretary/agent/reflection/ tests/agent/test_reflection_trigger.py
git commit -m "feat(reflection): add ReflectionTrigger for heuristic failure detection (F21)"
```

---

## Task 4: Register reflect archetype

**Files:**
- Modify: `src/secretary/agent/subagent/policy.py`
- Modify: `src/secretary/agent/subagent/registry.py:54-69, 79-144`
- Test: `tests/agent/subagent/test_runner.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/agent/subagent/test_runner.py`:

```python
def test_reflect_archetype_registered():
    """F21: reflect archetype must be in BUILTIN_ARCHETYPES."""
    from secretary.agent.subagent.policy import BUILTIN_ARCHETYPES, REFLECT_MAX_STEPS
    assert "reflect" in BUILTIN_ARCHETYPES
    assert REFLECT_MAX_STEPS == 4


def test_get_reflect_archetype_spec():
    """F21: get_archetype('reflect') must return ArchetypeSpec with correct config."""
    from secretary.agent.subagent.registry import get_archetype
    spec = get_archetype("reflect")
    assert spec is not None
    assert spec.name == "reflect"
    assert spec.max_steps == 4
    assert "reflection" in spec.system_prompt.lower() or "reflect" in spec.system_prompt.lower()
    # Tools must be read-only
    assert "file_write" not in (spec.tool_names or frozenset())
    assert "shell" not in (spec.tool_names or frozenset())
    assert "patch" not in (spec.tool_names or frozenset())


def test_reflect_archetype_in_list():
    """F21: list_archetype_names must include reflect."""
    from secretary.agent.subagent.registry import list_archetype_names
    names = list_archetype_names()
    assert "reflect" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/subagent/test_runner.py::test_reflect_archetype_registered tests/agent/subagent/test_runner.py::test_get_reflect_archetype_spec tests/agent/subagent/test_runner.py::test_reflect_archetype_in_list -v`
Expected: FAIL — "reflect" not in BUILTIN_ARCHETYPES

- [ ] **Step 3: Add REFLECT_MAX_STEPS to policy.py**

In `src/secretary/agent/subagent/policy.py`, add:

```python
"""Spawn depth, quotas, and timeout limits for sub-agents."""

from __future__ import annotations

MAX_SPAWN_DEPTH = 1
MAX_SPAWNS_PER_TURN = 3
MAX_PARALLEL_EXPLORE = 3
EXPLORE_MAX_STEPS = 8
WORKER_MAX_STEPS = 12
VERIFY_MAX_STEPS = 6
PLAN_MAX_STEPS = 8
REFLECT_MAX_STEPS = 4

SUBAGENT_TIMEOUT_SEC = 120
REFLECT_TIMEOUT_SEC = 60

BUILTIN_ARCHETYPES = frozenset({"explore", "worker", "verify", "plan", "reflect"})
```

- [ ] **Step 4: Add REFLECT_PROMPT and archetype registration in registry.py**

In `src/secretary/agent/subagent/registry.py`, add the REFLECT_PROMPT after VERIFY_PROMPT (around line 69):

```python
REFLECT_PROMPT = (
    "You are a reflection agent for Lumina (read-only).\n"
    "Your job: analyze a failed turn and produce a structured lesson for future turns.\n\n"
    "You have read-only tools. Use them ONLY if needed to confirm a specific fact "
    "(e.g., read a file that was patched wrong). Do not explore broadly — max 4 steps.\n\n"
    "Input context will include:\n"
    "- failure_mode: why this turn was flagged as failed\n"
    "- user_message: what the user wanted\n"
    "- raw_reply: what the LLM produced\n"
    "- tool_calls_summary: tools invoked and their outcomes\n"
    "- verify_issues: (if applicable) issues found by verify sub-agent\n\n"
    "Output STRICT JSON, nothing else:\n"
    "{\n"
    '  "failure_summary": "一句话总结失败本质（≤120 字符）",\n'
    '  "root_cause": "根本原因（≤300 字符）",\n'
    '  "lesson": "可迁移的教训，未来类似场景应如何避免（≤300 字符）",\n'
    '  "related_files": ["相关文件路径（如有）"],\n'
    '  "failure_tags": ["1-3 个标签，如 patch_error, shell_failure, scope_creep, wrong_abstraction"]\n'
    "}\n\n"
    "Rules:\n"
    '- Be specific, not generic. "应更仔细" is useless; '
    '"patch 前应先用 search_files 确认函数签名" is useful.\n'
    "- Focus on actionable lessons, not blame.\n"
    '- If the failure is genuinely uninformative (e.g., user just changed mind), '
    'output {"failure_summary": "non-informative", "root_cause": "", "lesson": "", '
    '"related_files": [], "failure_tags": []} and we will skip saving.\n'
    "Do not modify files or spawn other agents."
)
```

Add import of `REFLECT_MAX_STEPS` at the top of registry.py (in the existing import from policy):

```python
from secretary.agent.subagent.policy import (
    BUILTIN_ARCHETYPES,
    EXPLORE_MAX_STEPS,
    PLAN_MAX_STEPS,
    REFLECT_MAX_STEPS,
    VERIFY_MAX_STEPS,
    WORKER_MAX_STEPS,
)
```

Add the reflect archetype case in `get_archetype()` (after the "verify" case, around line 125):

```python
    if normalized == "reflect":
        return ArchetypeSpec(
            name="reflect",
            max_steps=REFLECT_MAX_STEPS,
            system_prompt=REFLECT_PROMPT,
            tool_names=frozenset(
                {
                    "list_dir",
                    "file_read",
                    "read_document",
                    "search_files",
                    "search_memory",
                    "web_search",
                    "web_fetch",
                    "session_search",
                }
            ),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/agent/subagent/test_runner.py::test_reflect_archetype_registered tests/agent/subagent/test_runner.py::test_get_reflect_archetype_spec tests/agent/subagent/test_runner.py::test_reflect_archetype_in_list -v`
Expected: All 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/secretary/agent/subagent/policy.py src/secretary/agent/subagent/registry.py tests/agent/subagent/test_runner.py
git commit -m "feat(subagent): register reflect archetype for F21 reflection"
```

---

## Task 5: Create ReflectionRunner (spawn reflect sub-agent)

**Files:**
- Create: `src/secretary/agent/reflection/runner.py`
- Modify: `src/secretary/agent/reflection/__init__.py`
- Test: `tests/agent/test_reflection_runner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agent/test_reflection_runner.py`:

```python
"""Tests for F21 ReflectionRunner — spawns reflect sub-agent and parses output."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from secretary.agent.reflection import FailureSignal, ReflectionRunner
from secretary.agent.reflection.trigger import FailureSignal as FS


def _make_signal(mode: str = "verify_failed") -> FailureSignal:
    return FS(
        mode=mode,
        summary="test failure",
        user_message="do something",
        raw_reply="reply text",
        tool_calls_summary=["file_read: ok"],
        verify_issues="issues found",
    )


def test_reflection_runner_parses_valid_json():
    """ReflectionRunner must extract JSON from reflector output."""
    runner = ReflectionRunner(
        llm_config=MagicMock(),
        file_auth=None,
        memory_store=MagicMock(),
        memory=MagicMock(),
        lumina_dir=Path("/tmp"),
    )
    reflector_output = (
        'Some preamble text\n'
        '{"failure_summary": "bad patch", "root_cause": "no signature check", '
        '"lesson": "verify first", "related_files": ["src/foo.py"], '
        '"failure_tags": ["patch_error"]}\n'
        'trailing text'
    )
    with patch.object(runner._runner, "run_from_tool", return_value=reflector_output):
        signal = _make_signal()
        result = runner.run(signal, working_dir=Path("/tmp"), parent_session_id="sess1")
    parsed = json.loads(result)
    assert parsed["failure_summary"] == "bad patch"
    assert parsed["lesson"] == "verify first"


def test_reflection_runner_returns_empty_on_failure():
    """If reflector fails or returns non-JSON, return empty string (not crash)."""
    runner = ReflectionRunner(
        llm_config=MagicMock(),
        file_auth=None,
        memory_store=MagicMock(),
        memory=MagicMock(),
        lumina_dir=Path("/tmp"),
    )
    with patch.object(runner._runner, "run_from_tool", return_value="Error: timeout"):
        signal = _make_signal()
        result = runner.run(signal, working_dir=Path("/tmp"), parent_session_id="sess1")
    assert result == ""


def test_reflection_runner_returns_empty_on_exception():
    """If reflector raises, return empty string (not crash)."""
    runner = ReflectionRunner(
        llm_config=MagicMock(),
        file_auth=None,
        memory_store=MagicMock(),
        memory=MagicMock(),
        lumina_dir=Path("/tmp"),
    )
    with patch.object(runner._runner, "run_from_tool", side_effect=RuntimeError("boom")):
        signal = _make_signal()
        result = runner.run(signal, working_dir=Path("/tmp"), parent_session_id="sess1")
    assert result == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_reflection_runner.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement ReflectionRunner**

Create `src/secretary/agent/reflection/runner.py`:

```python
"""F21 Reflexion: spawn reflect sub-agent to generate structured reflection.

Wraps SubAgentRunner.run_from_tool with archetype="reflect".
Parses JSON output; returns empty string on any failure (never crashes main flow).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from secretary.agent.reflection.trigger import FailureSignal
from secretary.agent.subagent.context import SpawnContext
from secretary.agent.subagent.runner import SubAgentDeps, SubAgentRunner

logger = logging.getLogger(__name__)

# Extract first JSON object from text (reflector may wrap JSON in prose)
_JSON_EXTRACT = re.compile(r"\{[^{}]*\}", re.DOTALL)


class ReflectionRunner:
    """Spawns a reflect sub-agent and parses its JSON output."""

    def __init__(
        self,
        *,
        llm_config: Any,
        file_auth: Any,
        memory_store: Any,
        memory: Any,
        lumina_dir: Path | None = None,
    ) -> None:
        deps = SubAgentDeps(
            llm_config=llm_config,
            file_auth=file_auth,
            memory_store=memory_store,
            memory=memory,
            lumina_dir=lumina_dir,
            temperature=0.3,
        )
        self._runner = SubAgentRunner(deps)

    def run(
        self,
        signal: FailureSignal,
        *,
        working_dir: Path,
        parent_session_id: str = "",
    ) -> str:
        """Spawn reflect sub-agent. Returns JSON string, or "" on failure."""
        context = self._build_context(signal)
        goal = f"分析失败 turn: mode={signal.mode}, summary={signal.summary}"

        spawn_context = SpawnContext(
            parent_session_id=parent_session_id,
            depth=0,
        )
        try:
            output = self._runner.run_from_tool(
                {
                    "goal": goal,
                    "context": context,
                    "archetype": "reflect",
                },
                spawn_context,
                working_dir,
                progress_callback=None,
                cancel_check=None,
            )
        except Exception as exc:
            logger.warning("Reflection sub-agent failed: %s", exc)
            return ""

        return self._extract_json(output)

    def _build_context(self, signal: FailureSignal) -> str:
        """Build context string for the reflector."""
        parts = [
            f"failure_mode: {signal.mode}",
            f"summary: {signal.summary}",
            f"user_message: {signal.user_message}",
            f"raw_reply: {signal.raw_reply}",
            f"tool_calls_summary: {json.dumps(signal.tool_calls_summary, ensure_ascii=False)}",
        ]
        if signal.verify_issues:
            parts.append(f"verify_issues: {signal.verify_issues}")
        return "\n".join(parts)

    @staticmethod
    def _extract_json(output: str) -> str:
        """Extract the first JSON object from reflector output."""
        if not output or output.startswith("Error:"):
            return ""
        match = _JSON_EXTRACT.search(output)
        if match is None:
            logger.warning("No JSON found in reflector output: %s", output[:200])
            return ""
        try:
            # Validate it's parseable
            json.loads(match.group())
            return match.group()
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in reflector output: %s", output[:200])
            return ""
```

Update `src/secretary/agent/reflection/__init__.py`:

```python
"""F21 Reflexion-style memory: failure detection and reflection generation."""

from secretary.agent.reflection.runner import ReflectionRunner
from secretary.agent.reflection.trigger import FailureSignal, ReflectionTrigger

__all__ = ["FailureSignal", "ReflectionTrigger", "ReflectionRunner"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_reflection_runner.py -v`
Expected: All 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/secretary/agent/reflection/runner.py src/secretary/agent/reflection/__init__.py tests/agent/test_reflection_runner.py
git commit -m "feat(reflection): add ReflectionRunner to spawn reflect sub-agent (F21)"
```

---

## Task 6: Integrate reflection trigger into _finalize_agent_result

**Files:**
- Modify: `src/secretary/agent/chat_service.py:1156-1231` (`_finalize_agent_result`)
- Modify: `src/secretary/agent/chat_service.py:123-200` (`__init__`)
- Test: `tests/agent/test_chat_service.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/agent/test_chat_service.py`:

```python
def test_finalize_agent_result_triggers_reflection_on_failure(monkeypatch):
    """F21: _finalize_agent_result must trigger reflection when Build turn fails."""
    from secretary.agent.chat_service import ChatService
    from secretary.agent.loop import LoopResult

    # Mock ChatService with minimal setup
    service = _build_minimal_chat_service()
    service._reflection_runner = MagicMock()
    service._reflection_runner.run.return_value = '{"failure_summary": "test", "lesson": "lesson"}'

    result = LoopResult(
        reply="incomplete",
        steps=[],
        used_tools=["file_read"],
        total_steps=20,  # max_steps exhausted
        cancelled=False,
        grounding_verified=True,
    )

    # Patch save_episode to verify it's called with reflection data
    service._memory.save_episode = MagicMock()

    with patch.object(service, "_prepare_user_reply", return_value=("reply", True, "")):
        service._finalize_agent_result(
            cleaned="do something",
            messages=[],
            result=result,
            llm_config=MagicMock(),
            session_id="sess1",
            profile_excerpt="build",
            memory_hits=0,
        )

    # Verify reflection was triggered
    service._reflection_runner.run.assert_called_once()
    # Verify save_episode was called with failure data
    save_calls = service._memory.save_episode.call_args_list
    assert len(save_calls) >= 1
    # Find the reflection save call
    reflection_call = None
    for call in save_calls:
        kwargs = call.kwargs
        if kwargs.get("failure_mode") is not None:
            reflection_call = call
            break
    assert reflection_call is not None
    assert reflection_call.kwargs["success"] is False
    assert reflection_call.kwargs["failure_mode"] == "max_steps_exhausted"


def test_finalize_agent_result_no_reflection_on_success():
    """F21: _finalize_agent_result must NOT trigger reflection on successful turn."""
    from secretary.agent.loop import LoopResult

    service = _build_minimal_chat_service()
    service._reflection_runner = MagicMock()

    result = LoopResult(
        reply="done",
        steps=[],
        used_tools=["file_read"],
        total_steps=3,
        cancelled=False,
        grounding_verified=True,
    )

    with patch.object(service, "_prepare_user_reply", return_value=("reply", True, "")):
        service._finalize_agent_result(
            cleaned="do something",
            messages=[],
            result=result,
            llm_config=MagicMock(),
            session_id="sess1",
            profile_excerpt="build",
            memory_hits=0,
        )

    service._reflection_runner.run.assert_not_called()


def test_finalize_agent_result_no_reflection_in_ask_profile():
    """F21: reflection must not trigger in Ask profile."""
    from secretary.agent.loop import LoopResult

    service = _build_minimal_chat_service()
    service._reflection_runner = MagicMock()

    result = LoopResult(
        reply="done",
        steps=[],
        used_tools=["file_read"],
        total_steps=20,  # would trigger, but...
        cancelled=False,
        grounding_verified=True,
    )

    with patch.object(service, "_prepare_user_reply", return_value=("reply", True, "")):
        service._finalize_agent_result(
            cleaned="do something",
            messages=[],
            result=result,
            llm_config=MagicMock(),
            session_id="sess1",
            profile_excerpt="ask",  # ...profile is ask
            memory_hits=0,
        )

    service._reflection_runner.run.assert_not_called()
```

Note: `_build_minimal_chat_service()` is a helper that should already exist in the test file. If not, add:

```python
def _build_minimal_chat_service():
    """Build a ChatService with mocked dependencies for unit testing."""
    from secretary.agent.chat_service import ChatService
    from secretary.agent.profile_service import ProfileService
    from secretary.agent.skill_manager import SkillManager
    from secretary.memory.db import MemoryStore
    from secretary.services.settings import Settings

    settings = Settings()
    settings._data_dir = Path("/tmp/lumina_test")
    settings._data_dir.mkdir(parents=True, exist_ok=True)
    store = MagicMock(spec=MemoryStore)
    profile_service = MagicMock(spec=ProfileService)
    skill_manager = MagicMock(spec=SkillManager)
    return ChatService(
        settings=settings,
        store=store,
        profile_service=profile_service,
        skill_manager=skill_manager,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_chat_service.py::test_finalize_agent_result_triggers_reflection_on_failure tests/agent/test_chat_service.py::test_finalize_agent_result_no_reflection_on_success tests/agent/test_chat_service.py::test_finalize_agent_result_no_reflection_in_ask_profile -v`
Expected: FAIL — `_reflection_runner` attribute not found

- [ ] **Step 3: Add ReflectionRunner to ChatService.__init__**

In `src/secretary/agent/chat_service.py`, add import at top:

```python
from secretary.agent.reflection import ReflectionTrigger, ReflectionRunner
```

In `__init__` (after `self._exec_skills = ...`, around line 152), add:

```python
        self._reflection_trigger = ReflectionTrigger(max_steps=20)
        self._reflection_runner: ReflectionRunner | None = None
```

Add a method to lazily initialize the runner (after `__init__`):

```python
    def _ensure_reflection_runner(self, llm_config: LlmConfig) -> ReflectionRunner:
        """Lazily create ReflectionRunner with current llm_config."""
        if self._reflection_runner is None:
            self._reflection_runner = ReflectionRunner(
                llm_config=llm_config,
                file_auth=self._file_auth,
                memory_store=self._store,
                memory=self._memory,
                lumina_dir=self._settings.resolved_data_dir(),
            )
        return self._reflection_runner
```

- [ ] **Step 4: Add reflection trigger logic to _finalize_agent_result**

In `_finalize_agent_result` (line 1156-1231), after the existing `save_episode` call (line 1196-1203) and before `self._append_history` (line 1205), add:

```python
        # F21: Reflexion — trigger reflection on Build-profile failures
        if (
            not result.pending_confirmation
            and result.used_tools
            and "build" in (profile_excerpt or "").lower()
        ):
            self._maybe_trigger_reflection(
                signal_user_message=cleaned,
                raw_reply=raw_reply,
                loop_result=result,
                turn_status="completed" if not result.cancelled else "cancelled",
                tool_call_history=self._extract_tool_call_history(result),
                llm_config=llm_config,
                thread_id=self._active_thread_id,
            )
```

Add the helper methods to ChatService:

```python
    def _maybe_trigger_reflection(
        self,
        *,
        signal_user_message: str,
        raw_reply: str,
        loop_result: LoopResult,
        turn_status: str,
        tool_call_history: list[dict[str, str]],
        llm_config: LlmConfig,
        thread_id: str,
    ) -> None:
        """F21: Evaluate failure signals and trigger reflection if matched."""
        signal = self._reflection_trigger.evaluate(
            profile="build",
            user_message=signal_user_message,
            raw_reply=raw_reply,
            loop_result=loop_result,
            turn_status=turn_status,
            tool_call_history=tool_call_history,
        )
        if signal is None:
            return

        try:
            runner = self._ensure_reflection_runner(llm_config)
            working_dir = self._turn_working_dir or Path.cwd()
            reflection_json = runner.run(
                signal,
                working_dir=working_dir,
                parent_session_id=self._get_or_create_session_id(),
            )
            if not reflection_json:
                logger.debug("Reflection produced no output for mode=%s", signal.mode)
                return
            # Save reflection as a separate failed episode
            reflection_episode_id = f"refl_{uuid.uuid4().hex[:8]}"
            self._memory.save_episode(
                episode_id=reflection_episode_id,
                task=signal_user_message[:500],
                steps=[],
                result=raw_reply[:2000],
                success=False,
                tools_used=loop_result.used_tools,
                failure_mode=signal.mode,
                reflection_text=reflection_json,
                thread_id=thread_id or None,
            )
            logger.info("Reflection saved: mode=%s, episode=%s", signal.mode, reflection_episode_id)
        except Exception as exc:
            logger.warning("Reflection failed (non-blocking): %s", exc)

    @staticmethod
    def _extract_tool_call_history(result: LoopResult) -> list[dict[str, str]]:
        """Extract tool call summaries from LoopResult for reflection trigger."""
        history: list[dict[str, str]] = []
        for step in result.steps:
            if step.tool_call is None:
                continue
            history.append({
                "name": step.tool_call.name,
                "arguments": step.tool_call.arguments if hasattr(step.tool_call, "arguments") else {},
                "output": (step.tool_output or "")[:500],
            })
        return history
```

Also fix the existing `save_episode` call (line 1196-1203) to use proper `success` value instead of hardcoded `True`:

```python
        if result.used_tools:
            episode_id = str(uuid.uuid4())[:8]
            steps_data = [
                {
                    "thought": s.thought[:200],
                    "tool": s.tool_call.name if s.tool_call else "",
                    "output": (s.tool_output or "")[:200],
                }
                for s in result.steps
            ]
            # F21: Fix bug — success was always True; now infer from LoopResult
            episode_success = (
                result.grounding_verified
                and not result.cancelled
                and result.total_steps < self._reflection_trigger._max_steps
            )
            self._memory.save_episode(
                episode_id=episode_id,
                task=cleaned[:500],
                steps=steps_data,
                result=safe_reply[:2000],
                success=episode_success,
                tools_used=result.used_tools,
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_chat_service.py::test_finalize_agent_result_triggers_reflection_on_failure tests/agent/test_chat_service.py::test_finalize_agent_result_no_reflection_on_success tests/agent/test_chat_service.py::test_finalize_agent_result_no_reflection_in_ask_profile -v`
Expected: All 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/secretary/agent/chat_service.py tests/agent/test_chat_service.py
git commit -m "feat(reflection): integrate reflection trigger into _finalize_agent_result (F21)"
```

---

## Task 7: Inject top-3 reflections into system prompt

**Files:**
- Modify: `src/secretary/agent/chat_service.py:1376-1455` (`_build_system_prompt`)
- Test: `tests/agent/test_chat_service.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/agent/test_chat_service.py`:

```python
def test_build_system_prompt_includes_reflections_block():
    """F21: _build_system_prompt must include '## 历史教训' section when reflections exist."""
    service = _build_minimal_chat_service()

    # Seed a failed episode with reflection
    service._memory.save_episode(
        episode_id="refl_test1",
        task="deploy the app",
        steps=[],
        result="failed to deploy",
        success=False,
        tools_used=["shell"],
        failure_mode="grounding_failed",
        reflection_text='{"failure_summary": "missing env var", "lesson": "check env first", '
                        '"related_files": [], "failure_tags": ["shell_failure"]}',
    )

    prompt = service._build_system_prompt("profile markdown", [])
    assert "## 历史教训" in prompt
    assert "missing env var" in prompt
    assert "check env first" in prompt


def test_build_system_prompt_no_reflections_when_empty():
    """F21: no '## 历史教训' section when no reflections exist."""
    service = _build_minimal_chat_service()
    # Use a fresh temp dir with no episodes
    prompt = service._build_system_prompt("profile markdown", [])
    assert "## 历史教训" not in prompt


def test_build_system_prompt_skips_non_informative_reflections():
    """F21: reflections with 'non-informative' summary must be skipped."""
    service = _build_minimal_chat_service()

    service._memory.save_episode(
        episode_id="refl_skip1",
        task="some task",
        steps=[],
        result="result",
        success=False,
        tools_used=["file_read"],
        failure_mode="user_correction",
        reflection_text='{"failure_summary": "non-informative", "lesson": "", '
                        '"related_files": [], "failure_tags": []}',
    )

    prompt = service._build_system_prompt("profile markdown", [])
    assert "## 历史教训" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_chat_service.py::test_build_system_prompt_includes_reflections_block tests/agent/test_chat_service.py::test_build_system_prompt_no_reflections_when_empty tests/agent/test_chat_service.py::test_build_system_prompt_skips_non_informative_reflections -v`
Expected: FAIL — "## 历史教训" not in prompt

- [ ] **Step 3: Add _build_reflections_block method to ChatService**

In `src/secretary/agent/chat_service.py`, add this method (before `_build_system_prompt`, around line 1370):

```python
    def _build_reflections_block(self, user_message: str) -> str:
        """F21: Retrieve top-3 relevant failed-turn reflections and format for prompt."""
        if not user_message.strip():
            return ""
        try:
            episodes = self._memory.search_episodes(
                query=user_message,
                limit=3,
                success_only=False,
            )
        except Exception:
            return ""
        if not episodes:
            return ""

        lines = ["## 历史教训（按相关性检索，避免重蹈覆辙）"]
        for ep in episodes:
            refl_text = ep.get("reflection_text")
            if not refl_text:
                continue
            try:
                refl = json.loads(refl_text)
            except (json.JSONDecodeError, TypeError):
                continue
            summary = str(refl.get("failure_summary", ""))
            lesson = str(refl.get("lesson", ""))
            if not summary or summary == "non-informative":
                continue
            mode = ep.get("failure_mode") or "unknown"
            entry = f"- [{mode}] {summary} → {lesson[:120]}"
            lines.append(entry[:200])

        if len(lines) == 1:
            return ""
        return "\n".join(lines) + "\n\n"
```

- [ ] **Step 4: Inject reflections block into _build_system_prompt**

In `_build_system_prompt` (line 1376-1455), modify the method signature to accept `user_message`:

```python
    def _build_system_prompt(
        self, profile_markdown: str, hits: list[MemoryChunk], user_message: str = ""
    ) -> str:
```

In the return statement (around line 1444), add the reflections block between `notes_block` and `"## 对话规则"`:

```python
        reflections_block = self._build_reflections_block(user_message)

        return prefix + (
            "## 关于用户的资料（用户画像与本地文档，描述用户本人，不是灵犀）\n"
            f"{profile_block[:6000]}\n\n"
            "## 关于用户的本地记忆（用户经历与资料，不是灵犀的属性）\n"
            f"{memory_block}\n"
            f"{memory_section}"
            f"{shibei_section}"
            f"{notes_block}\n\n"
            f"{reflections_block}"
            "## 对话规则\n"
```

- [ ] **Step 5: Update all callers of _build_system_prompt**

Find all call sites (lines 816, 931, 1015) and add `user_message=` argument. For example at line 816:

```python
        system_prompt = self._build_system_prompt(profile_markdown, hits, user_message=cleaned)
```

At line 931:

```python
        system_prompt = (
            self._build_system_prompt(profile_markdown, hits, user_message=cleaned)
            + "\n\n" + appendix
        )
```

At line 1015:

```python
        system_prompt = (
            self._build_system_prompt(profile_markdown, hits, user_message=cleaned)
            + profile_system_appendix(profile)
        )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_chat_service.py::test_build_system_prompt_includes_reflections_block tests/agent/test_chat_service.py::test_build_system_prompt_no_reflections_when_empty tests/agent/test_chat_service.py::test_build_system_prompt_skips_non_informative_reflections -v`
Expected: All 3 PASS

- [ ] **Step 7: Run full test suite to verify no regressions**

Run: `uv run pytest tests/agent/test_chat_service.py -v -x`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/secretary/agent/chat_service.py tests/agent/test_chat_service.py
git commit -m "feat(reflection): inject top-3 reflections into system prompt (F21)"
```

---

## Task 8: Update PRD and run final verification

**Files:**
- Modify: `docs/PRD.md:357` (F21 status)
- Modify: `docs/PRD.md` §12 (implementation index)

- [ ] **Step 1: Update PRD F21 status**

In `docs/PRD.md`, find line 357 (F21 row in the Future table) and change status from Research to Done(MVP):

```markdown
| F21 | **反思记忆（Reflexion-style）** | **Done（MVP）**：失败 turn → reflect 子 agent → episodes 表扩展 → top-3 注入 |
```

- [ ] **Step 2: Add implementation index entry**

In `docs/PRD.md` §12, add a new row to the implementation index table:

```markdown
| 反思记忆 | `src/secretary/agent/reflection/` |
```

- [ ] **Step 3: Run ruff check**

Run: `uv run ruff check src tests`
Expected: No errors

- [ ] **Step 4: Run mypy**

Run: `uv run mypy src`
Expected: No errors (or only pre-existing warnings)

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest`
Expected: All tests PASS (including new F21 tests)

- [ ] **Step 6: Commit**

```bash
git add docs/PRD.md
git commit -m "docs: update PRD — F21 reflection memory Done(MVP)"
```

---

## Self-Review Notes

**Spec coverage:**
- ✅ episodes table extension (Task 1)
- ✅ save_episode / search_episodes signature extension (Task 2)
- ✅ ReflectionTrigger with 5 failure signals + priority (Task 3)
- ✅ reflect archetype registration (Task 4)
- ✅ ReflectionRunner to spawn reflect sub-agent (Task 5)
- ✅ _finalize_agent_result integration + bug fix (Task 6)
- ✅ top-3 reflection injection (Task 7)
- ✅ PRD update (Task 8)

**Type consistency:**
- `FailureSignal` fields consistent across trigger.py, runner.py, and chat_service.py
- `save_episode` signature: `episode_id` is first positional arg (matches existing code, not spec's ordering)
- `search_episodes` returns `list[dict[str, object]]` (matches existing code, not spec's `list[Episode]`)
- `REFLECT_MAX_STEPS = 4` consistent in policy.py and registry.py

**Deviations from spec (adjusted to match actual code):**
- `save_episode` keeps `episode_id` as first positional arg (spec showed `task` first)
- `search_episodes` returns dicts, not Episode objects (existing code uses dicts)
- FTS5 indexes `task + result + reflection_text + failure_mode` (spec mentioned steps_json, but actual FTS5 doesn't index steps_json)
- Profile detection uses `profile_excerpt` string contains "build" (simpler than passing enum)
