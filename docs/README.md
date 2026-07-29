# Lumina docs

**产品真相源：** [PRD.md](PRD.md)

## 定位（现行）

| 项 | 说明 |
|----|------|
| 品类 | 本地优先的**通用 Agent 生产力工具**（非个人 AI 秘书） |
| 已交付差异 | 对话地图 · harness · Build/Ask/Plan/Auto · MCP |
| 规划差异 | Skill 编排 / 工作流 DAG（F26，高级能力仍后续） |
| 已交付（MVP） | 思考链可追溯（FR-51）· Harness 可定制参数（FR-52） |
| 外部集成 | **只做标准 MCP 或 CLI**；平台专用 Connector = Legacy frozen |
| 可选扩展 | Shibei 知识库、持久记忆 |

## 索引

| 文档 | 用途 |
|------|------|
| [PRD.md](PRD.md) | 愿景、FR、路线图、Open Decisions |
| [harness-design.md](harness-design.md) | 自研 runtime 原则与 checklist |
| [workflow-dag-design.md](workflow-dag-design.md) | Skill 编排设计（规划中） |
| [4-harness-comparison.md](4-harness-comparison.md) | 四家 harness 抽象对比（参考） |
| [subagent-loop-comparison.md](subagent-loop-comparison.md) | Sub-agent 设计参考 |
| [superpowers/specs/2026-07-27-idp-design.md](superpowers/specs/2026-07-27-idp-design.md) | Internal Delegation Protocol（委派协议化） |
| [superpowers/specs/2026-07-27-tree-swarm-agent-design.md](superpowers/specs/2026-07-27-tree-swarm-agent-design.md) | 树状 swarm 早期方案（已被下条取代） |
| [superpowers/specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md](superpowers/specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md) | **受控深树 · 结构化对抗 · Mission Strip**（现行规格；PRD 0.3.2） |
| [superpowers/plans/2026-07-30-controlled-tree-adversarial-mission-strip.md](superpowers/plans/2026-07-30-controlled-tree-adversarial-mission-strip.md) | FR-53–56 实施计划（WriteGate 已开工） |
| [reply-safety/](reply-safety/) | 回复过滤词表 |
| [superpowers/](superpowers/) | 历史 specs/plans；执行前核对 PRD 是否废止 |

## 已废止 / 勿再跟进

- [superpowers/plans/2026-07-16-settings-unified-extensions.md](superpowers/plans/2026-07-16-settings-unified-extensions.md) — 「6 连接器 → builtin MCP」已废止
- FR-30 `spawn_cli_agent` — Removed（CLI ≠ CLI Agent，见 PRD §9）
