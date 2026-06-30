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
  Electron · FastAPI · self-built agent harness · Shibei KB · Lumina durable memory
</p>

---

灵犀是在你本机运行的个人 AI 秘书：读文件、搜 **Shibei 知识库**、连 MCP、可选同步飞书/读书等数据，Shell / 写入 / 删除前征得你确认。

**产品需求文档（含 v0.2 路线图）：** [docs/PRD.md](docs/PRD.md)

**架构：** [docs/harness-design.md](docs/harness-design.md) · [docs/4-harness-comparison.md](docs/4-harness-comparison.md)

---

## 功能概览

| 能力 | 说明 |
|------|------|
| **对话 Agent** | 自研 `AgentLoop`：读/写文件、Shell、联网、MCP；高风险操作需确认 |
| **Shibei 知识库（主）** | 直连 Shibei `config.yaml` + `~/.shibei/db`；`shibei_search` 读个人笔记/文档；**无需先同步** |
| **知识库页** | `workspace` 路由：浏览 Shibei 索引、搜索、预览（设置 → Shibei 同源） |
| **连接器同步（备选）** | 飞书、微信读书、小红书、邮箱等 → Lumina SQLite → `search_memory`；旧 `/api/kb/*` workspace 仅 legacy 手动导出 |
| **Sub-agent** | `explore` / `worker` / `verify` + 自定义 md；暂停/恢复；进度树 UI |
| **CLI Agent** | **`spawn_cli_agent`** 外接 codex/kimi 等 CLI；核心与设置 UI 已落地，provider 集成继续推进 — [FR-30](docs/PRD.md) |
| **Agent 模式** | `build` / `plan` / `orchestrator`（设置 → 大模型） |
| **防幻觉 Grounding** | 文件/记忆类回答需工具佐证；Verified / Unverified 标记 |
| **持久记忆** | Lumina `MEMORY.md` / `USER.md`；`memory` 工具写入 |
| **联网 / 天气** | `web_search`（多引擎降级）+ 桌面定位 |
| **Chat Markdown** | `markdown-it` + DOMPurify 渲染助手回复 |
| **技能 & MCP** | 本地技能；stdio MCP 扩展 |
| **双语 UI** | English · 中文（`en` / `zh` / `bi`） |

### 读记忆 vs 同步

```
读个人文档 / 笔记 / 「读取记忆」  →  shibei_search（Shibei 索引）
写偏好 / 稳定事实                  →  memory 工具（USER.md / MEMORY.md）
微信读书 / 飞书等连接器专项         →  search_memory（需先「同步」，备选）
```

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLite |
| 前端 | Electron · HTML/CSS/JS · markdown-it · DOMPurify |
| Agent | PromptGate → TurnOrchestrator → AgentLoop → Tools + MCP |
| 知识库 | [Shibei](https://github.com/Miles128/shibei) 语义索引（BM25 / 向量） |
| Sub-agent | `spawn_subagent` · pause/resume · 无 LangGraph |
| 数据 | `~/.lumina/` · Shibei `~/.shibei/` |

---

## 快速开始

### 1. 安装依赖

```bash
cd Lumina
pip install -e ".[dev]"

# Electron（国内镜像）
./scripts/install-electron.sh
cd desktop && npm install
```

### 2. 配置大模型

```bash
cp .env.example .env
# LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
```

或编辑 `~/.lumina/agent.json`。仅使用灵犀自己的配置；如需迁移，可在「设置 → 大模型」点击「一键从 Hermes 导入全部」。

### 3. 配置 Shibei（推荐）

1. 安装 [Shibei](https://github.com/Miles128/shibei)（默认路径 `~/Documents/Projects/shibei`）
2. 在 Shibei 的 `config.yaml` 配置 `sources` 监控文件夹
3. 灵犀 **设置 → Shibei 知识库**：确认安装路径 → **测试检索**

### 4. 启动

```bash
# 桌面端（自动拉起后端 :8765）
cd desktop && npm start

# 或分开启动
./scripts/start-backend.sh
cd desktop && npm start

# macOS 打包（显示名「灵犀」）
cd desktop && npm run pack
# 仍需本机 Python 3.11+ 且 pip install -e ".[dev]"
```

### 5. 可选：连接器同步

**设置 → 平台** 配置飞书/读书等 → 右上角 **「同步」**。  
同步数据进入 Lumina 记忆库，作为 Shibei 的**补充**，不是读文档的前置条件。

---

## 品牌资源

| 文件 | 用途 |
|------|------|
| `docs/assets/screenshot.jpg` | README 配图 |
| `docs/assets/logo.png` | 文档 |
| `desktop/ui/logo.png` | 顶栏、favicon、助手头像 |
| `desktop/icons/icon.icns` | macOS 应用图标 |

---

## MCP 配置

`~/.lumina/mcp.json`：

```json
{
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

设置 → MCP → 保存并连接。

---

## 目录结构

```
Lumina/
├── docs/                    # PRD、harness 设计、架构对比
├── src/secretary/
│   ├── agent/               # loop、chat_service、grounding、subagent
│   ├── services/            # shibei_service、sync、profile
│   └── api/                 # FastAPI
├── desktop/ui/
│   ├── chat.js              # 对话 + SSE
│   ├── markdown.js          # markdown-it 封装
│   ├── workspace.*          # Shibei 知识库浏览
│   └── vendor/              # markdown-it、DOMPurify
├── tests/
└── scripts/
```

---

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_KEY` | API Key | — |
| `LLM_BASE_URL` | OpenAI 兼容地址 | — |
| `LLM_MODEL` | 模型名 | — |
| `LUMINA_DATA_DIR` | 数据目录 | `~/.lumina` |
| `SECRETARY_AUTO_SYNC_ENABLED` | 自动同步 | `true` |
| `PROMPT_GATE_ENABLED` | LLM 输入分类 | `false` |

完整列表：`src/secretary/config.py`

---

## 对话路由

```
用户消息
  → 联网 / 天气（resolve_web_search）
  → PromptGate（规则默认）
  → sync_routing（Shibei 就绪 → 不拦读记忆；写记忆 → 不拦）
  → DIRECT 闲聊 | LIGHT 记忆（shibei_search 优先）| AgentLoop 工具任务
  → Grounding 校验 → 流式回复
```

子 Agent：`spawn_subagent` → 子 loop → 需确认时 pause → 用户 Allow → resume → 摘要回父 Agent。

---

## 开发

```bash
pytest                          # 301 tests
./scripts/e2e-smoke.sh            # API + Playwright（端口 8766）
ruff check src tests
mypy src

# 升级聊天 Markdown vendor
cd desktop && npm run vendor:sync
```

CI：`.github/workflows/ci.yml`（Python 3.11 / 3.12）

### 当前分支与版本

| 版本 | 说明 |
|------|------|
| `v0.1.1` | 已发布：E2E、Shibei tools、sync empty |
| `v0.1.2` | 已发布：子 Agent pause、KB UI、Shibei-first 路由、Markdown、Hermes runtime 解耦 |
| **v0.2** | 见 [PRD §12](docs/PRD.md) Sprint B–D；Shibei 空结果 UX、会话 v2、CLI provider 集成、打包体验 |

---

## 许可证

Private — 个人项目。

## 作者

四海 · [myx28@qq.com](mailto:myx28@qq.com)
