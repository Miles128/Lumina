# Lumina docs

**产品真相源：** [PRD.md](PRD.md)

## 定位（现行）

| 项 | 说明 |
|----|------|
| 品类 | 本地优先的**通用 Agent 生产力工具**（非个人 AI 秘书） |
| 已交付差异 | 对话地图 · harness · Build/Ask/Plan/Auto · MCP |
| 规划差异 | Skill 编排 / 工作流 DAG（[workflow-dag-design.md](workflow-dag-design.md)，F26，未产品化） |
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
| [reply-safety/](reply-safety/) | 回复过滤词表 |
| [superpowers/](superpowers/) | 历史 specs/plans；执行前核对 PRD 是否废止 |

## 已废止 / 勿再跟进

- [superpowers/plans/2026-07-16-settings-unified-extensions.md](superpowers/plans/2026-07-16-settings-unified-extensions.md) — 「6 连接器 → builtin MCP」已废止
- FR-30 `spawn_cli_agent` — Removed（CLI ≠ CLI Agent，见 PRD §9）
