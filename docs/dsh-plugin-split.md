# Lumina 插件拆分方案

> 状态：**已执行 phase 1+2**（两个功能包；meta 暂不发布）
> 目标：把当前单包 `dsh-lumina` 拆成职责单一、可独立安装的 dsh 插件；对话树保持独立，Skill/Workflow 保持 dsh 原生。

## 1. 先说结论

只拆 **两个代码插件 + 一个 meta 包**：

| 包 | 职责 | 是否代码 |
|---|---|---|
| `dsh-lumina-memory` | `MEMORY.md` 注入 + `memory` / `search_memory` 工具 | 是 |
| `dsh-lumina-shibei` | Shibei 召回规则 + 可选自动召回注入 | 是 |
| `dsh-lumina`（meta） | 依赖上面两个，一条命令装齐 | 仅 patch |
| `dsh-forkmap` | 对话树（已有独立仓库） | 是，不并入 |
| Skill / Workflow | dsh 原生能力 | 否，纯 profile 配置 |

**不建议再拆**：persona / trace / jail / confirm / grounding 已在之前的瘦身里删掉，重新拆成插件等于把刚减掉的复杂度加回来。只有出现真实独立需求时才加包。

## 2. 为什么这样切

| 边界 | 理由 |
|---|---|
| memory vs shibei | 数据源、失败模式、配置都不同：memory 是本地文件 + 工具；shibei 是外部 MCP + 召回策略。一个坏了不影响另一个 |
| 保持 forkmap 独立 | 它是客户端 React 插件，依赖 dsh client 包，发布节奏和 host 插件不同；塞进同一个包会让依赖变重 |
| Skill/Workflow 不进插件 | 已经是 dsh 原生 `SKILL.md` + `workflow` 工具，再包一层没有收益 |
| meta 包 | 用户不想记两个包名时，`dsh plugin add dsh-lumina` 一次装齐；也方便锁定兼容版本 |

## 3. 仓库结构

```
dsh/
  package.json                 # private workspace root
  tsconfig.base.json
  packages/
    memory/
      package.json             # dsh-lumina-memory
      cordis.patch.yml         # insert lumina-memory
      src/index.ts
      test/
      README.md
    shibei/
      package.json             # dsh-lumina-shibei
      cordis.patch.yml         # insert lumina-shibei
      src/index.ts
      test/
      README.md
    meta/
      package.json             # dsh-lumina（依赖 memory + shibei）
      cordis.patch.yml         # insert 两个 row
      README.md
  profile.patch.example.yml
```

根 `package.json`：

```json
{
  "private": true,
  "workspaces": ["packages/*"],
  "scripts": {
    "build": "npm run build --workspaces",
    "test": "npm run test --workspaces",
    "check": "npm run check --workspaces"
  }
}
```

## 4. 代码映射

| 当前文件 | 去向 |
|---|---|
| `src/memory.ts` | `packages/memory/src/index.ts` |
| `src/shibei.ts` + `src/recall.ts` | `packages/shibei/src/{prompt,recall,index}.ts` |
| `src/paths.ts`（expandHome） | 两个包各自 10 行，或放 `packages/shared`；**不建议**为一个函数建包 |
| `src/config.ts` | 拆成两个 `Config` 接口，各自持有命名空间 |
| `src/index.ts` | 删除；由 meta 的 patch 组合 |
| `test/memory.test.js` | `packages/memory/test/` |
| `test/shibei.test.js` + `test/recall.test.js` | `packages/shibei/test/` |

## 5. 包与配置

### `dsh-lumina-memory`

```yaml
- insert:
    - id: lumina-memory
      name: dsh-lumina-memory
```

```ts
export interface Config {
  root: string       // default ~/.lumina/memories
  inject: boolean    // default true
  maxChars: number   // default 4000
}
```

### `dsh-lumina-shibei`

```yaml
- insert:
    - id: lumina-shibei
      name: dsh-lumina-shibei
```

```ts
export interface Config {
  serverName: string   // default shibei
  recall: boolean      // prompt 规则，default true
  autoRecall: boolean  // agent/pre-step 注入，default false
  topK: number         // default 3
  maxChars: number     // default 1200
  timeoutMs: number    // default 8000
}
```

MCP 连接本身**不进插件**：命令路径、PYTHONPATH、SHIBEI_CONFIG 都是机器相关，继续放在 profile 的 `mcp-shibei` 行。插件只做「工具在不在 → 召回/注入」，找不到工具就静默 no-op。

### `dsh-lumina`（meta）

```yaml
- insert:
    - id: lumina-memory
      name: dsh-lumina-memory
    - id: lumina-shibei
      name: dsh-lumina-shibei
```

`package.json` 依赖两个功能包（发布时用 semver，本地开发用 `file:../memory`）。

> 安装规则：**meta 和单个功能包二选一**。同时把两个功能包加进 `dsh.profile.bundles` 会导致同名 row 重复插入，后一个覆盖前一个，配置容易错乱。

## 6. 安装与升级

```bash
# 全量
dsh plugin --profile lumina add /path/to/dsh/packages/meta

# 只要 Shibei
dsh plugin --profile lumina add /path/to/dsh/packages/shibei

# 只要 memory
dsh plugin --profile lumina add /path/to/dsh/packages/memory
```

- 每个包独立 semver；meta 用**精确版本**锁住两个功能包，避免 memory 0.2 + shibei 0.1 的隐性不兼容。
- 发布到 npm 后，`dsh plugin add dsh-lumina` 即可；本地开发用 `link:`。
- dsh 仍是 RC：每个包 peer 依赖写 `>=0.1.0-rc.6`，升级 dsh 时先跑各包测试。

## 7. 迁移步骤

| 阶段 | 动作 | 验收 |
|---|---|---|
| 1 | 建 workspace；把 memory 代码/测试移入 `packages/memory`；补 package.json + patch | `npm test -w packages/memory` 绿 |
| 2 | 把 shibei prompt/recall 移入 `packages/shibei`；拆 Config | `npm test -w packages/shibei` 绿 |
| 3 | 建 meta 包；profile 换成 meta 安装 | `dsh --profile lumina --dump-config` 出现两个 row |
| 4 | 保留 `dsh-lumina` 旧包一个版本，内部改为依赖两个新包并插入两行（兼容别名） | 旧 profile 不改也能跑 |
| 5 | 更新 README / profile 模板 / CI；下个版本删除旧包 | 文档无单包引用 |

CI：

```yaml
- run: npm ci
- run: npm run build --workspaces
- run: npm run test --workspaces
```

## 8. 风险与取舍

| 风险 | 应对 |
|---|---|
| 包变多，安装/升级更麻烦 | meta 包一次装齐；文档只推 meta |
| 配置分散，用户不知道改哪个 | 每个包 README 只写自己的 key；meta README 给一张对照表 |
| 两个包重复 `expandHome` 等小工具 | 接受 10 行重复，胜过为一个函数建 shared 包 |
| meta 与单包同时安装导致重复 row | 安装规则写死「二选一」；meta patch 使用不同 row id 也可规避 |
| dsh RC 破坏性变更 | 各包独立测试 + meta 锁版本；升级前跑真实会话冒烟 |
| Shibei MCP 不可用 | 插件检测 `ctx.tools.get()`，缺失直接 no-op，不影响 memory |

## 9. 不拆的部分

- **对话树**：留在 `dsh-forkmap`，它是 client plugin，依赖 React 与 dsh client 包；合并会让 host 包变重。
- **Skill / Workflow**：dsh 原生，配置即可，不需要 Lumina 包。
- **persona / trace / jail / confirm / grounding**：已删除，不恢复。

## 10. 建议

先做 **phase 1 + 2**（两个功能包），meta 可以晚一周；确认 `dsh plugin add` 的依赖解析在 meta 上没问题后再发 meta。拆分本身不改变任何行为，验收标准就是「拆完后 profile 行为与单包一致」。
