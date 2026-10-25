/**
 * WriteGate (PRD FR-53): delegated children write drafts only.
 *
 * The root agent keeps normal workspace access. Every child published through
 * `subagent/start` is jailed to `<workspace>/<proposalsDir>/<runId>/`:
 *   - write / edit → deny outside the proposals root
 *   - bash / pwsh → read-only commands only (mutation goes through write tools)
 *
 * Landing authority (referee / root writing business paths) needs no special
 * case here: those agents are never in the child registry.
 */

import path from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-subagent'
import type {} from '@deepseek-ai/dsh-tools'
import type { LuminaConfig } from './config.js'
import { isInside, isReadOnlyShell, resolveTarget, workspaceRoot } from './paths.js'

const WRITE_TOOLS = new Set(['write', 'edit', 'str_replace_editor', 'multi_edit'])
const SHELL_TOOLS = new Set(['bash', 'pwsh'])

export function proposalsRoot(cfg: LuminaConfig, runId: string, sessionCwd?: string): string {
  return path.join(workspaceRoot(cfg.workspace, sessionCwd), cfg.writeGate.proposalsDir, runId || 'anon')
}

function filePathOf(args: unknown): string | null {
  if (!args || typeof args !== 'object') return null
  const record = args as Record<string, unknown>
  const value = record.file_path ?? record.path
  return typeof value === 'string' ? value : null
}

function commandOf(args: unknown): string {
  if (!args || typeof args !== 'object') return ''
  const value = (args as Record<string, unknown>).command
  return typeof value === 'string' ? value : ''
}

export function installWriteGate(ctx: Context, cfg: LuminaConfig): void {
  if (!cfg.writeGate.enabled) return
  /** child session id → run id */
  const children = new Map<string, string>()

  ctx.on('subagent/start', (info) => {
    children.set(String(info.id), String(info.runId))
  })
  ctx.on('subagent/end', (info) => {
    children.delete(String(info.id))
  })

  ctx.on('tools/pre-execute', async (exec, next) => {
    const agentId = exec.agent ? String(exec.agent.id) : ''
    const runId = children.get(agentId)
    if (!runId) return next()
    const sessionCwd = exec.agent?.session?.header?.cwd
    const root = proposalsRoot(cfg, runId, sessionCwd)

    if (WRITE_TOOLS.has(exec.name)) {
      const raw = filePathOf(exec.arguments)
      if (!raw) return next()
      const target = resolveTarget(raw, workspaceRoot(cfg.workspace, sessionCwd))
      if (!isInside(root, target)) {
        return {
          kind: 'deny',
          reason:
            `WriteGate: 子 Agent 只能写草稿目录 \`${root}\`，不能直接改业务路径 \`${target}\`。` +
            ' 请把提案写到 proposals，由主 Agent 收尾落地。',
        }
      }
      return next()
    }

    if (SHELL_TOOLS.has(exec.name)) {
      const command = commandOf(exec.arguments).trim()
      if (!command) return next()
      if (isReadOnlyShell(command)) return next()
      return {
        kind: 'deny',
        reason:
          'WriteGate: 子 Agent 的 shell 只允许只读命令。' +
          ` 需要产出文件时请用 write 工具写到 \`${root}\`。`,
      }
    }

    return next()
  })
}
