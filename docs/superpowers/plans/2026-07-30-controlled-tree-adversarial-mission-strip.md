# Controlled Tree · Adversarial · Mission Strip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship WriteGate, configurable deep tree (≤2 / hard 3), structured adversarial debate, and Mission Strip UI per the 2026-07-30 design and PRD 0.3.2 FR-53–56.

**Architecture:** Dual engine (runtime `spawn_subagent` tree + existing workflow DAG) sharing WriteGate. Adversarial is a stacked phase with alternating debate transcript (not peer bus). UI is Mission Strip (Chinese role titles + real progress) plus a debate side panel.

**Tech Stack:** Python FastAPI harness (`src/secretary/agent/*`), Electron `desktop/ui/*`, pytest, existing IDP / TraceStore / SSE progress.

## Global Constraints

- `HARD_MAX_DEPTH = 3` (code hard limit; config cannot exceed)
- Default topology remains `shallow` (depth=1) until user enables `deep_tree`
- Subagents never write business paths; only `~/.lumina/proposals/{run_id}/` or workspace `.lumina/proposals/{run_id}/`
- Debate: alternating shared transcript; default 6 rounds, hard cap 12; referee may end early
- UI labels: 项目主管 / 产品经理 / 调研分析 / 执行者 / 方案主张 / 风险质询 / 评审仲裁 / 项目落地 — no pixel avatars / cute nicknames
- Product narrative stays harness/delegation — not “swarm collaboration platform”
- Verify: `uv run pytest && uv run ruff check src tests` before claiming done; `uv run mypy src` when touching typed APIs

**Spec:** [docs/superpowers/specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md](../specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md)

---

## File map

| File | Responsibility |
|------|----------------|
| `src/secretary/agent/write_gate.py` | **Create** — path jail, lock state, apply preview |
| `src/secretary/agent/harness_config.py` | topology / adversarial / depth / debate knobs |
| `src/secretary/agent/subagent/policy.py` | `HARD_MAX_DEPTH`, resolve effective max depth |
| `src/secretary/agent/subagent/runner.py` | depth budget, archetype re-spawn rules |
| `src/secretary/agent/subagent/registry.py` | tool lists honor WriteGate |
| `src/secretary/agent/tools/fs.py` / loop confirm path | route writes through WriteGate |
| `src/secretary/agent/idp.py` | debate_transcript channel, role display names |
| `src/secretary/agent/debate.py` | **Create** — alternating rounds, early stop |
| `src/secretary/agent/progress_events.py` | mission-strip fields on SSE |
| `desktop/ui/chat.js` + `chat.css` | Mission Strip + expand thinking |
| `desktop/ui/debate_panel.js` + css | **Create** — left/right debate UI |
| `desktop/ui/settings.js` | topology / adversarial toggles |
| `tests/agent/test_write_gate.py` | **Create** |
| `tests/agent/test_subagent_depth.py` | extend for depth=2 |
| `tests/agent/test_debate.py` | **Create** |

---

### Task 1: WriteGate core (FR-53)

**Files:**
- Create: `src/secretary/agent/write_gate.py`
- Create: `tests/agent/test_write_gate.py`
- Modify: `src/secretary/agent/tools/fs.py` (or write tool entry) to call gate
- Modify: `src/secretary/agent/subagent/registry.py` worker tools note

**Interfaces:**
- Produces:
  - `proposals_root(run_id: str, workspace: Path | None) -> Path`
  - `assert_write_allowed(role: str, path: Path, *, gate_unlocked: bool) -> None` (raises `WriteGateError`)
  - `is_proposals_path(path: Path, run_id: str, workspace: Path | None) -> bool`

- [x] **Step 1: Write failing tests** for jail allow/deny and proposals path resolution

- [x] **Step 2: Run** `uv run pytest tests/agent/test_write_gate.py -v` — expect FAIL

- [x] **Step 3: Implement `write_gate.py`**

- [x] **Step 4: Wire `file_write` / `write` / `patch`** so subagent roles without landing privilege only succeed under proposals root

- [x] **Step 5: Run tests + ruff** — pass

- [ ] **Step 6: Commit** `feat(agent): add WriteGate proposals jail (FR-53)` — wait for user ask

---

### Task 2: HarnessConfig topology knobs

**Files:**
- Modify: `src/secretary/agent/harness_config.py`
- Modify: tests covering harness load/save (find existing harness tests)
- Modify: settings UI binding in `desktop/ui/settings.js` (Harness section)

**Interfaces:**
- Produces on `HarnessConfig`:
  - `topology_default: Literal["shallow","deep_tree","workflow"] = "shallow"`
  - `deep_tree_max_depth: int = 2` (ge=1, le=3)
  - `adversarial: Literal["off","auto","force"] = "auto"`
  - `debate_max_rounds: int = 6` (ge=1, le=12)
  - `adversarial_risk_file_threshold: int = 2`

- [ ] **Step 1: Failing tests** for clamp (depth>3 rejected / clamped to 3; rounds>12 clamped)

- [ ] **Step 2: Implement fields + persist via existing agent.json harness path**

- [ ] **Step 3: Settings UI labels in Chinese**

- [ ] **Step 4: pytest + commit** `feat(harness): topology and adversarial config knobs`

---

### Task 3: Deep tree depth=2 (FR-54)

**Files:**
- Modify: `src/secretary/agent/subagent/policy.py`
- Modify: `src/secretary/agent/subagent/runner.py`
- Modify: `src/secretary/agent/subagent/context.py` (budget fields if needed)
- Modify: `src/secretary/agent/idp.py`
- Modify: `tests/agent/test_subagent_depth.py`

**Interfaces:**
- Consumes: `HarnessConfig.deep_tree_max_depth`, `topology`
- Produces: effective `max_depth` from config when topology=`deep_tree`, else 1; never > `HARD_MAX_DEPTH`
- Only archetypes `explore`/`plan` may spawn when `depth < max_depth`

- [ ] **Step 1: Extend depth tests** — child explore at depth=1 can spawn when max=2; worker cannot; depth=2 cannot

- [ ] **Step 2: Implement policy resolve + runner checks + node budget decrement**

- [ ] **Step 3: Keep shallow default green on existing tests**

- [ ] **Step 4: Commit** `feat(agent): configurable spawn depth ≤2 (FR-54)`

---

### Task 4: Structured debate engine (FR-55)

**Files:**
- Create: `src/secretary/agent/debate.py`
- Create: `tests/agent/test_debate.py`
- Modify: `src/secretary/agent/idp.py` (`channel=debate_transcript`, roles)
- Modify: `src/secretary/agent/chat_service.py` or turn runner to enter DebatePhase when auto/force triggers

**Interfaces:**
- Produces:
  - `DebateState(round, max_rounds, transcript, status)`
  - `should_trigger_adversarial(...) -> bool`
  - `run_debate_turn(...)` alternating pro/con; referee `maybe_conclude`
  - Early exit when referee says enough OR rounds hit cap

- [ ] **Step 1: Unit tests** for trigger heuristics, alternation, early stop, hard cap 12

- [ ] **Step 2: Implement debate module** (LLM calls via existing loop helpers; both sides WriteGate-jailed)

- [ ] **Step 3: Hook auto trigger before business multi-file write / on conflicting explore summaries**

- [ ] **Step 4: Commit** `feat(agent): structured adversarial debate phase (FR-55)`

---

### Task 5: Mission Strip SSE + UI (FR-56 partial)

**Files:**
- Modify: `src/secretary/agent/progress_events.py`
- Modify: `src/secretary/agent/idp.py` (display_name map)
- Modify: `desktop/ui/chat.js`, `desktop/ui/chat.css`, `desktop/ui/index.html`
- Reuse/expand `#agent-progress` / `#subagent-tree`

**Interfaces:**
- SSE item fields: `role`, `display_name`, `progress` (0–100 or null), `phase`, `status`
- Click row → expand thinking / tool timeline / trace link (existing progress expand patterns)

- [ ] **Step 1: Backend emits Chinese display_name + progress**

- [ ] **Step 2: Render Mission Strip rows (no avatars)**

- [ ] **Step 3: Expand panel shows thinking + tools**

- [ ] **Step 4: Manual desktop check + commit** `feat(ui): Mission Strip with role progress`

---

### Task 6: Debate independent panel UI

**Files:**
- Create: `desktop/ui/debate_panel.js`, `debate_panel.css`
- Modify: `index.html` to include panel shell
- Wire open/close from Mission Strip when debate active

- [ ] **Step 1: Left 方案主张 / right 风险质询 / bottom 评审仲裁**

- [ ] **Step 2: Stream transcript updates from SSE**

- [ ] **Step 3: Human actions: 采纳 / 改判 / 再开一轮 / 取消 → API**

- [ ] **Step 4: Commit** `feat(ui): adversarial debate side panel`

---

### Task 7: Landing preview + confirm apply

**Files:**
- Modify: WriteGate apply + confirm pending_actions path
- Modify: debate/referee conclusion → diff list → existing confirm UI

- [ ] **Step 1: Tests for apply only when unlocked after confirm**

- [ ] **Step 2: Wire 项目落地 row states: locked → preview → confirming → applied**

- [ ] **Step 3: Commit** `feat(agent): WriteGate landing apply after referee`

---

### Task 8: Workflow DAG adversarial template (B path)

**Files:**
- Modify: workflow templates under existing F26 paths (locate `adversarial_review` or demos)
- Sync node status → Mission Strip / debate panel

- [ ] **Step 1: Add template JSON/YAML for adversarial_review**

- [ ] **Step 2: Auto-insert or jump when topology=workflow and adversarial=auto on risky write node**

- [ ] **Step 3: Commit** `feat(workflow): adversarial_review DAG template`

---

### Task 9: Docs + verification gate

- [ ] **Step 1: Ensure PRD FR-53–56 status notes match reality as tasks land**

- [ ] **Step 2: Full** `uv run pytest && uv run ruff check src tests && uv run mypy src`

- [ ] **Step 3: Short note in harness-design.md pointing to new spec**

---

## Execution order

Ship **Task 1 → 2 → 3** before UI-heavy 5–6 so protocol is real. Task 4 can parallelize with 3 after WriteGate exists. Do not open debate UI until Task 4 emits state.
