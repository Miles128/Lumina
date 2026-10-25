# Lumina docs

**产品真相源：** [PRD.md](PRD.md)  
**实现映射：** [dsh-rewrite-plan.md](dsh-rewrite-plan.md)

## 定位（v0.5 现行）

| 项 | 说明 |
|----|------|
| 品类 | 本地优先的**通用 Agent 生产力工具**（非个人 AI 秘书） |
| Runtime | **DeepSeek Harness（dsh）** 官方 runtime；Lumina 只做产品层插件 |
| 已交付差异 | 对话树（dsh-forkmap）· 跨会话记忆（MEMORY.md + 工具）· Shibei 答前召回 |
| 规划差异 | 跨对话记忆 M2/M3：自动捕获 episode + 自动召回（[设计](cross-session-memory-design.md)） |
| Skill / Workflow | dsh 原生 `SKILL.md` + JavaScript 工作流脚本 |
| 外部集成 | **只做标准 MCP 或 CLI**；Shibei 走 MCP |
| 前端 | 寄生 dsh Desktop / Web；自研 Electron 壳已退役 |

## 索引

| 文档 | 用途 |
|------|------|
| [PRD.md](PRD.md) | 愿景、FR、路线图、Open Decisions |
| [dsh-rewrite-plan.md](dsh-rewrite-plan.md) | Python/Electron → dsh 的迁移记录与 Phase 0 结论 |
| [cross-session-memory-design.md](cross-session-memory-design.md) | 跨对话记忆系统设计（L1 事实 / L2 情景 / L3 知识） |
| [../dsh/README.md](../dsh/README.md) | 插件能力、配置、安装 |
| [../dsh/WORKFLOWS.md](../dsh/WORKFLOWS.md) | Skill / Workflow 用法 |
| [4-harness-comparison.md](4-harness-comparison.md) | 四家 harness 抽象对比（参考） |
| [subagent-loop-comparison.md](subagent-loop-comparison.md) | Sub-agent 设计参考 |
| [reply-safety/](reply-safety/) | 回复过滤词表 |
| [superpowers/](superpowers/) | 历史 specs/plans（含已退役的受控深树设计） |

## 历史文档（已退役实现）

这些文档描述的是 Python/Electron 时代的设计，**不代表当前实现**，仅在需要回看或移植时参考：

- [harness-design.md](harness-design.md) — 自研 Python harness
- [workflow-dag-design.md](workflow-dag-design.md) — Skill DAG 画布（已由 dsh workflow 取代）
- [superpowers/specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md](superpowers/specs/2026-07-30-controlled-tree-adversarial-mission-strip-design.md) — 受控深树 / 结构化对抗（WriteGate 部分已落地）
- [superpowers/plans/2026-07-30-controlled-tree-adversarial-mission-strip.md](superpowers/plans/2026-07-30-controlled-tree-adversarial-mission-strip.md) — 对应实施计划

## 代码存档

Python/FastAPI + Electron 实现：

- tag：`legacy-python-v0.4.0`
- branch：`archive/python-legacy`
