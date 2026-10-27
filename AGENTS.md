# AGENTS.md — Lumina

Lumina 是 **DeepSeek Harness（`dsh`）的差异化插件**，不是独立 harness 产品。

- runtime（agent loop · LLM 适配 · 沙箱 · 委派 · session）由 dsh 官方维护。
- 本仓库只做产品层：grounding · confirmation · WriteGate · memory · trace · prompt · Shibei。
- UI 寄生 dsh Desktop/Web（客户端插件），不再维护 Electron 壳。
- Skill / Workflow 用 dsh 原生 `SKILL.md` + JavaScript 脚本；禁止重启自研 DAG。

## Quick start

```bash
cd dsh
npm install
npm run build
npm test
```

挂载到 dsh profile：

```bash
dsh plugin --profile web add /absolute/path/to/Lumina/dsh/packages/memory
dsh plugin --profile web add /absolute/path/to/Lumina/dsh/packages/shibei
```

## Verification

```bash
cd dsh && npm run build && npm test
```

CI 只跑这一条链。提交前必须绿。

## 结构

```
dsh/              npm workspace（两个插件）
  packages/memory/    MEMORY.md + memory/search_memory
  packages/shibei/    Shibei 召回 + 可选自动注入
  profile.patch.example.yml
docs/             PRD + 迁移记录 + 历史设计
```

## 开发纪律

- **只写产品层**：不实现 agent loop、LLM 协议解析、沙箱、委派、session 持久化——这些是 dsh 的职责。
- **用 dsh seam**：工具策略走 `tools/pre-execute` / `post-execute`；强制补步走 `agent/turn-stopping`；轨迹走 `session/event`；提示词走 `systemPrompt.section`；子 Agent 识别走 `subagent/start`。
- **不引第三方 runtime**：新增依赖先说明为什么现有 dsh seam 不够。
- **最小 diff**：不要顺带重构相邻代码。
- **不造轮子**：协议/运行时用库或 dsh 原生能力；产品策略（栅栏、确认、WriteGate、grounding、memory、trace）才自研。
- **配置可覆盖**：所有行为参数进 `LuminaConfig`，默认合理，profile 可改。

## 已退役（勿恢复）

- Python/FastAPI 后端、Electron 壳、Skill DAG 画布。
- 代码存档：tag `legacy-python-v0.4.0` / branch `archive/python-legacy`。
- `docs/harness-design.md`、`docs/workflow-dag-design.md` 是历史设计，不代表当前实现。

## 产品真相

`docs/PRD.md` 定义产品意图；实现映射以 `docs/dsh-rewrite-plan.md` 为准。若两者冲突，先改 PRD 再改代码。
