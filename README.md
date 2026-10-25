# Lumina · 灵犀

<p align="center">
  <img src="docs/assets/logo.png" alt="Lumina logo" width="120" />
</p>

<p align="center">
  <strong>DeepSeek Harness 的差异化产品层 · 本地优先的 Agent 生产力工具</strong>
</p>

<p align="center">
  dsh plugin · grounding · confirmation · WriteGate · memory · traces · Shibei
</p>

---

灵犀不再自己维护 agent runtime。**DeepSeek Harness（`dsh`）** 负责 loop / LLM 适配 / 沙箱 / 委派 / session；本仓库只交付 Lumina 的产品差异化，打包为一个 dsh 插件 `dsh-lumina`，UI 寄生 dsh Desktop/Web（客户端插件）。

**核心差异点：** 工作区硬栅栏 · 分级确认 · WriteGate（子 Agent 只写草稿）· grounding 强制补读 · MEMORY.md + 检索 · 本地思考链轨迹 · Shibei 答前召回。

---

## 功能

| 能力 | 说明 |
|---|---|
| **WriteGate** | 子 Agent 只能写 `.lumina/proposals/<runId>/`，shell 只读；主 Agent 负责落地 |
| **Jail** | 写盘 / shell 绝对路径不得越出工作区（`完全权限` 可关） |
| **Confirm** | 越界写、任意 shell、MCP 写操作走 dsh `approval`；只读与工作区内写不打扰 |
| **Grounding** | 文件/内容问题必须先用 `read`；未读就答会被强制补一步（有限次） |
| **Memory** | `MEMORY.md` 自动注入 + `memory` / `search_memory` 工具 |
| **Trace** | `~/.lumina/traces/<session>.jsonl`，含 user / assistant / tool / turn |
| **Shibei** | 通过 MCP 接知识库，个人背景类问题先 `shibei_context` 再回答 |
| **Skill / Workflow** | 直接用 dsh 原生 `SKILL.md` + JavaScript 工作流脚本 |

## 安装

```bash
cd dsh
npm install
npm run build

dsh plugin --profile web add /absolute/path/to/Lumina/dsh
# 或新建专用 profile
dsh --profile lumina --from-default-profile web --dump-config
dsh plugin --profile lumina add /absolute/path/to/Lumina/dsh
```

完整的 profile 覆盖模板（Lumina 配置 + Skill/Workflow + Shibei MCP）见 [`dsh/profile.patch.example.yml`](dsh/profile.patch.example.yml)。

## 结构

```
dsh/                    dsh-lumina 插件（全部产品逻辑）
  src/                  prompt · writegate · jail · confirm · grounding · memory · trace
  test/                 node:test 单元测试
  WORKFLOWS.md          Skill / Workflow 用法
docs/                   PRD、迁移记录、历史设计
.github/workflows/      CI（build + test）
```

## 验证

```bash
cd dsh && npm run build && npm test
```

## 文档

- [产品需求 PRD](docs/PRD.md)
- [迁移记录（Python/Electron → dsh）](docs/dsh-rewrite-plan.md)
- [Skill / Workflow](dsh/WORKFLOWS.md)
- [历史 harness 设计](docs/harness-design.md)（已退役实现，仅存档）

## 旧实现

Python/FastAPI + Electron 版本已退役，代码不在当前树中：

- tag：`legacy-python-v0.4.0`
- branch：`archive/python-legacy`

需要回看或移植时从 tag 取。
