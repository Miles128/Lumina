<p align="center">
  <img src="docs/assets/screenshot.jpg" alt="Lumina desktop screenshot" width="900" />
</p>

# Lumina · 灵犀

<p align="center">
  <img src="docs/assets/logo.png" alt="Lumina logo" width="120" />
</p>

<p align="center">
  <strong>Local-first personal AI secretary · 本地优先的个人 AI 秘书</strong>
</p>

<p align="center">
  Electron desktop · FastAPI · self-built agent harness · Hermes-compatible memory
</p>

---

灵犀是在你本机运行的个人 AI 秘书：读文件、搜记忆、连 MCP、同步飞书/读书/小红书等数据，并在 Shell / 写入 / 删除前征得你确认。不是又一个网页聊天框。

产品需求文档：[docs/PRD.md](docs/PRD.md)

架构参考：[docs/4-harness-comparison.md](docs/4-harness-comparison.md) · [docs/subagent-loop-comparison.md](docs/subagent-loop-comparison.md)

## 功能概览

| 能力 | 说明 |
|------|------|
| **对话 Agent** | 自研 `AgentLoop`：读/写文件、Shell、搜文件、联网、MCP；高风险操作需确认 |
| **Sub-agent（Phase 1）** | `spawn_subagent` 委派只读 `explore` 子任务，隔离 context，只回摘要 |
| **防幻觉 Grounding** | 文件类问题强制工具查证；`search_files` 结果可正常用于列表回复 |
| **持久记忆** | Hermes 风格 `MEMORY.md` / `USER.md`，对话后自动整理 |
| **数据源同步** | 飞书、微信读书、小红书、邮箱、云盘、本地文档 |
| **技能 & MCP** | 本地技能挂载；stdio MCP 扩展工具 |
| **流式体验** | 回复逐字输出；工具进度 SSE 实时可见 |
| **双语 UI** | English · 中文 标签（可切换 `en` / `zh` / `bi`） |

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLite |
| 前端 | Electron · HTML/CSS/JS |
| Agent | PromptGate → TurnOrchestrator → AgentLoop → Tools + MCP |
| Sub-agent | `spawn_subagent` · `SubAgentRunner`（无 LangGraph） |
| 数据 | `~/.lumina/` |

## 快速开始

### 1. 安装依赖

```bash
cd Lumina
pip install -e ".[dev]"

# Electron（国内镜像）
./scripts/install-electron.sh
```

### 2. 配置大模型

```bash
cp .env.example .env
# 编辑 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
```

或在 `~/.lumina/agent.json` 配置；留空时会尝试读取 `~/.hermes/config.yaml`。

### 3. 启动

```bash
# 方式 A：桌面端自动拉起后端
cd desktop && npm start

# 方式 B：分开启动
./scripts/start-backend.sh    # http://127.0.0.1:8765
cd desktop && npm start
```

## 品牌资源

| 文件 | 用途 |
|------|------|
| `docs/assets/screenshot.jpg` | README 主界面配图 |
| `docs/assets/logo.png` | README / 文档 |
| `desktop/ui/logo.png` | 顶栏、favicon、助手头像 |

## MCP 配置示例

`~/.lumina/mcp.json`：

```json
{
  "import_hermes": true,
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/you/projects"],
      "enabled": true,
      "transport": "stdio",
      "timeout": 120
    }
  }
}
```

设置 → MCP 工具 → 保存并连接。

## 目录结构

```
Lumina/
├── docs/                 # PRD、架构对比、logo
├── src/secretary/        # FastAPI 后端
│   └── agent/
│       ├── loop.py       # Agent 主循环
│       └── subagent/     # Phase 1 子 Agent
├── desktop/ui/           # Electron UI + logo.png
├── tests/
└── scripts/
```

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_KEY` | API Key | — |
| `LLM_BASE_URL` | OpenAI 兼容地址 | — |
| `LLM_MODEL` | 模型名 | — |
| `LUMINA_DATA_DIR` | 数据目录 | `~/.lumina` |
| `SECRETARY_AUTO_SYNC_ENABLED` | 自动同步 | `true` |

完整列表见 `src/secretary/config.py`。

## 开发

```bash
pytest          # 170+ tests
ruff check src tests
mypy src
```

## 许可证

Private — 个人项目。

## 作者

四海 · [myx28@qq.com](mailto:myx28@qq.com)
