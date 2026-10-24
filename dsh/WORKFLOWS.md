# Skills & Workflows (dsh native)

Slice 3 decision: **Lumina 不再维护 Skill DAG / 画布编排**。流程编排直接用 DeepSeek Harness 的两套原生能力：

| 能力 | 用途 | 入口 |
|---|---|---|
| **Skill** | 可复用的任务方法论（Markdown 指令包），按需加载 | `skill` 工具 / `/name` 用户手势 |
| **Workflow** | 模型写 JavaScript 脚本，扇出多个子 Agent，返回结构化 JSON | `workflow` 工具 |

## 一、Skill

### 目录与优先级

`dsh-skill-filesystem` 从这些根目录发现技能（rank 越小越优先）：

| Rank | 来源 | 路径 |
|---|---|---|
| 100 | project-dsh | `<project>/.dsh/skills` |
| 200 | project-agents | `<project>/.agents/skills` |
| 300 | custom | `customSkillDirs`（本 profile 配了 `/Users/<you>/.lumina/skills`；dsh 不展开 `~`，必须写绝对路径） |
| 400 | user-dsh | `~/.dsh/skills` |
| 500 | user-agents | `~/.agents/skills` |

格式：目录包 `<name>/SKILL.md` 或平铺 `<name>.md`，YAML frontmatter 必填 `name`（kebab-case）和 `description`：

```markdown
---
name: weekly-report
description: 每周汇总本周提交与会议纪要，输出 Markdown 周报。
---

# Weekly Report
...
```

可选字段：`whenToUse`、`metadata`、`disable-model-invocation`、`user-invocable`。

现有 `~/skills/` 下的 144 个技能已通过 `~/.agents/skills` 被 dsh 发现；`article-flow` 等可直接用 `skill` 工具加载，或在输入框打 `/article-flow`。

### 验证

```
用 skill 工具加载 article-flow，然后只回复它的标题行。
→ Article-Flow：中文自媒体文章全流程方法论
```

## 二、Workflow

`workflow` 工具接收 `meta` + `script`（纯 JavaScript 函数体）+ 可选 `args`。脚本可用：

- `agent(prompt, options?)`：启动一个子 Agent，返回文本或结构化结果；失败返回 `null`
- `parallel([...])` / `pipeline([...])`：并发 / 串行组合
- `phase(name)`：进度阶段
- `log(message)`：实时日志

### 示例：最小可跑脚本

```js
phase('ping')
const reply = await agent('只回复 pong')
return { reply }
```

模型在正常会话里会说成：

> 用 workflow 跑一个最小工作流：一个 phase，一个 agent 返回 pong。

实测（DeepSeek-V4.1-Flash，前台）：`demo-ping` 1 个 agent，3 秒完成，返回 `{ "reply": "pong" }`。

### 示例：审计/调研型扇出

```js
phase('scan')
const files = args.files
const findings = await parallel(
  files.map((file) => async () => {
    const result = await agent(
      `只读审计 ${file}，列出风险点。返回 JSON：{"file": string, "issues": string[]}`,
      { schema: { type: 'object', properties: { file: { type: 'string' }, issues: { type: 'array', items: { type: 'string' } } }, required: ['file', 'issues'] } },
    )
    return result ?? { file, issues: [] }
  }),
)
return { files: files.length, findings }
```

### 使用边界

- `workflow` 适合 **多文件审计 / 迁移 / 多角度调研**；1–2 次委派直接用 `subagent`。
- 子 Agent 仍然受 WriteGate 约束：只能写 `.lumina/proposals/<runId>/`，shell 只读。
- 前台运行会等全部子 Agent 结束；`run_in_background: true` 返回 job id，用 `job_output` / `job_kill` 收尾。
- 取消或异常不会返回部分结果（返回 error）。

## 三、迁移状态

| 旧实现 | 新实现 | 状态 |
|---|---|---|
| `src/secretary/workflow/`（DAG 引擎，1,076 行） | dsh `workflow` JS 脚本 | **停止演进**，Slice 5 删除 |
| `desktop/ui/workflows.js`（画布） | dsh Web job 面板 + `ui-workflow-run` | **退役** |
| `src/secretary/agent/skills.py` / `executable_skill.py` | dsh `skill` + `SKILL.md` | **停止演进**，Slice 5 删除 |
