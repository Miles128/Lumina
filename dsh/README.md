# dsh-lumina

Lumina 在 DeepSeek Harness 上的产品层，拆成两个独立插件：

| 包 | 作用 | 默认行为 |
|---|---|---|
| **dsh-lumina-memory** | `MEMORY.md` 注入 + `memory` / `search_memory` 工具 | 开启 |
| **dsh-lumina-shibei** | Shibei 答前召回规则 + 可选自动召回注入 | 规则开启，自动注入关闭 |

对话树仍由 [`dsh-forkmap`](https://github.com/Miles128/dsh-forkmap) 提供；Skill / Workflow 用 dsh 原生能力，不在本仓库。

## 安装

```bash
cd dsh
npm install
npm run build

# 两个都装
dsh plugin --profile lumina add "$PWD/packages/memory"
dsh plugin --profile lumina add "$PWD/packages/shibei"

# 或只装一个
dsh plugin --profile lumina add "$PWD/packages/shibei"
```

## dsh-lumina-memory

```yaml
- id: lumina-memory
  config:
    enabled: true
    root: ~/.lumina/memories
    inject: true
    maxChars: 4000
```

- `MEMORY.md` 每轮注入 system prompt
- `memory`：add / replace / remove
- `search_memory`：搜索 MEMORY.md 与本地笔记

## dsh-lumina-shibei

```yaml
- id: lumina-shibei
  config:
    serverName: shibei   # 必须与 mcp-client 的 serverName 一致
    recall: true         # prompt 规则
    autoRecall: false    # 每轮第一步自动注入（多一次 MCP 调用）
    topK: 3
    maxChars: 1200
    timeoutMs: 8000
```

MCP 连接本身不进插件，继续放 profile 的 `mcp-shibei` 行（命令路径、`PYTHONPATH`、`SHIBEI_CONFIG` 都是机器相关的）。插件检测不到 `mcp__<server>__shibei_context` 时直接 no-op。

完整模板见 [`profile.patch.example.yml`](profile.patch.example.yml)。

## 开发

```bash
cd dsh
npm install
npm run build      # 两个包
npm test           # build + 两个包的测试
```

## Legacy

单包 `dsh-lumina` 已拆分为 `dsh-lumina-memory` + `dsh-lumina-shibei`。Python/Electron 实现存档于 tag `legacy-python-v0.4.0`。
