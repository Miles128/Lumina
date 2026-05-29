# Lumina · 灵犀

个人 AI 秘书桌面应用。本地运行 FastAPI 后端 + Electron 前端，支持工具调用、持久记忆、数据源同步与 MCP 扩展。

## 功能概览

- **对话 Agent**：多轮工具循环（读文件、搜索、shell、联网等），读写操作需用户确认
- **持久记忆**：Hermes 风格 `MEMORY.md` / `USER.md`，对话后自动整理
- **数据源同步**：飞书、微信读书、小红书、邮箱、云盘等（按平台配置）
- **技能管理**：本地技能挂载与可执行技能
- **MCP 工具**：接入 Model Context Protocol 服务器，扩展 Agent 能力
- **流式回复**：模型回答逐字显示，工具过程通过 SSE 实时展示
- **后台任务**：定时同步、每日简报、后台思考、会话记忆摘要

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLite |
| 前端 | Electron · 原生 HTML/CSS/JS |
| Agent | 自研 Loop · OpenAI 兼容 API · MCP SDK |
| 数据 | `~/.lumina/`（配置、记忆库、会话） |

## 快速开始

### 1. 安装依赖

```bash
# Python 后端
cd Lumina
pip install -e ".[dev]"

# Electron 桌面端（国内镜像）
./scripts/install-electron.sh
```

### 2. 配置大模型

复制环境变量模板并按需填写：

```bash
cp .env.example .env
```

或在 `~/.lumina/agent.json` 中配置 API Key / Base URL / Model。  
若留空，会尝试读取 `~/.hermes/config.yaml` 中的 LLM 配置。

### 3. 启动

```bash
# 终端 1：后端（默认 http://127.0.0.1:8765）
./scripts/start-backend.sh

# 终端 2：桌面端
cd desktop && npm start
```

## MCP 服务器

在 **设置 → Agent → MCP 工具** 中添加，或编辑 `~/.lumina/mcp.json`：

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

保存后点击「重新连接」，或从 Hermes 配置一键导入。

## 目录结构

```
Lumina/
├── src/secretary/     # Python 后端（API、Agent、记忆、连接器）
├── desktop/           # Electron 应用与 UI
├── tests/             # pytest 测试
└── scripts/           # 启动与安装脚本
```

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_KEY` | 大模型 API Key | — |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | — |
| `LLM_MODEL` | 模型名称 | — |
| `LUMINA_DATA_DIR` | 数据目录 | `~/.lumina` |
| `SECRETARY_AUTO_SYNC_ENABLED` | 自动同步 | `true` |
| `SECRETARY_THINK_ENABLED` | 后台思考 | `true` |
| `SECRETARY_MEMORY_SUMMARY_ENABLED` | 每日记忆摘要 | `true` |

完整列表见 `src/secretary/config.py`。

## 开发

```bash
# 运行测试
pytest

# 代码检查
ruff check src tests
mypy src
```

## 许可证

Private — 个人项目。

## 作者

四海 · [myx28@qq.com](mailto:myx28@qq.com)
