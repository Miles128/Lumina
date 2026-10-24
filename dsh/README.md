# dsh-lumina

Lumina 的产品差异化层，打包为一个 DeepSeek Harness（`dsh`）插件。runtime（agent loop · LLM 适配 · 沙箱 · 委派 · session）由 dsh 官方提供，本仓库只保留 Lumina 自己的产品逻辑。

## 已交付（Slice 1 + 2）

| 模块 | 作用 | dsh seam |
|---|---|---|
| `prompt` | 灵犀人格 + grounding 纪律 | `ctx.systemPrompt.section` |
| `writegate` | 子 Agent 只能写 `.lumina/proposals/<runId>/`；子 Agent shell 只读 | `subagent/start` · `tools/pre-execute` |
| `jail` | 工作区硬栅栏：写盘 / shell 绝对路径不得越界 | `tools/pre-execute` |
| `confirm` | 越界写、任意 shell、MCP 写操作走确认 | `tools/pre-execute` → `ctx.approval` |
| `grounding` | 文件/内容问题未读工具 → 强制补一步（动作请求不触发） | `agent/turn-stopping` → `agent.steer` |
| `memory` | `MEMORY.md` 注入 system prompt + `memory` / `search_memory` 工具 | `systemPrompt.section` · `ctx.tools.register` |
| `trace` | 本地 JSONL 思考链轨迹 | `session/event` |

工作区解析优先级：`config.workspace` > 会话 header 的 `cwd` > `process.cwd()`。

## 构建

```bash
cd dsh
npm install
npm run build
npm test
```

## 挂载到 dsh profile

```bash
dsh plugin --profile web add /absolute/path/to/Lumina/dsh
# 或在 profile 的 package.json 里 link，然后把 dsh-lumina 加进 dsh.profile.bundles
```

bundle patch 只有一行：

```yaml
- insert:
    - id: lumina
      name: dsh-lumina
```

## 配置

在 profile 的 `cordis.patch.yml` 里覆盖（整行 config 替换，所以要么全写，要么用默认）：

```yaml
- id: lumina
  config:
    workspace: /Users/me/project   # 省略 = 用会话 cwd
    jail: true
    fullFsAccess: false
    permissionMode: normal         # normal | auto | yolo | custom
    requireConfirm:
      writeNew: true
      writeModify: true
      writeDelete: true
      shell: true
      action: true
    writeGate:
      enabled: true
      proposalsDir: .lumina/proposals
    grounding:
      enabled: true
      maxRetries: 2
    memory:
      enabled: true
      root: ~/.lumina/memories
      inject: true
      maxChars: 4000
    trace:
      enabled: true
      root: ~/.lumina/traces
      retention: full              # full | summary | off
      retainDays: 30
```

`permissionMode` 预设：`normal` 全确认；`auto` 只确认改/删/shell；`yolo` 不确认。`requireConfirm` 可逐项覆盖。

## 尚未迁移（后续切片）

- 对话地图 → 已有独立客户端插件 `dsh-forkmap`
- Skill DAG 编排（dsh 自带 `skill` / `workflow`，需要做能力对齐）
- web_search / browser 服务层
- MCP 策略与 Shibei
- 退役 Python `api/` 与 Electron 壳，测试迁移
