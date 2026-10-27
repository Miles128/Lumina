# dsh-lumina

Lumina 在 DeepSeek Harness 上的产品层。只做三件事：

1. **跨对话记忆** — `MEMORY.md` 注入 + `memory` / `search_memory` 工具
2. **Shibei 答前召回** — 个人背景类问题先查知识库再回答
3. **对话树** — 由客户端插件 [`dsh-forkmap`](https://github.com/Miles128/dsh-forkmap) 提供（session fork 谱系 / 一键分叉）

runtime（loop · LLM · 沙箱 · 权限 · 委派 · session · 轨迹 · persona）全部由 dsh 负责，本插件不重复实现。

## 安装

```bash
cd dsh
npm install
npm run build

dsh plugin --profile lumina add /absolute/path/to/Lumina/dsh
```

对话树：

```bash
dsh plugin --profile lumina add /absolute/path/to/dsh-forkmap
```

Shibei 通过 dsh 的 MCP client 接入，见 [`profile.patch.example.yml`](profile.patch.example.yml) 的 `mcp-shibei` 段。

## 配置

```yaml
- id: lumina
  config:
    memory:
      enabled: true
      root: ~/.lumina/memories
      inject: true
      maxChars: 4000
    shibei:
      recall: true
      serverName: shibei   # 必须与 mcp-client 的 serverName 一致
      autoRecall: false    # true = 每轮第一步自动注入 Shibei 召回（多一次 MCP 调用）
      topK: 3
      maxChars: 1200
      timeoutMs: 8000
```

完整模板（含 Skill/Workflow 与 Shibei MCP）见 [`profile.patch.example.yml`](profile.patch.example.yml)。

## 工具

| 工具 | 作用 |
|---|---|
| `memory` | `add` / `replace` / `remove` MEMORY.md 中的长期事实 |
| `search_memory` | 搜索 MEMORY.md 与本地记忆笔记 |

`MEMORY.md` 每轮注入 system prompt（可用 `memory.inject: false` 关闭）。

## 跨对话记忆（规划）

当前是「手工 curated facts + 工具检索」。自动捕获 / 自动召回的设计见 [docs/cross-session-memory-design.md](../docs/cross-session-memory-design.md)。

## 开发

```bash
npm run build
npm test
```

## Legacy

Python/FastAPI + Electron 实现已退役：tag `legacy-python-v0.4.0` / branch `archive/python-legacy`。
