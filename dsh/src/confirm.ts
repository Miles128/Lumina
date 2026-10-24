/**
 * Confirmation policy for write / shell / MCP tools over dsh's pre-execute
 * waterfall. Read-only tools never pause; in-workspace writes never pause
 * (the user picked that workspace); escaping writes and arbitrary shell
 * commands ask through `ctx.approval`, and a missing answerer fails closed.
 */

import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-tools'
import type { LuminaConfig } from './config.js'
import { isInside, isReadOnlyShell, isSafeExecutable, resolveTarget, workspaceRoot } from './paths.js'

const WRITE_TOOLS = new Set(['write', 'edit', 'str_replace_editor', 'multi_edit'])
const SHELL_TOOLS = new Set(['bash', 'pwsh'])
const FREE_TOOLS = new Set([
  'read', 'read_image', 'glob', 'grep', 'web_search', 'web_fetch', 'ls', 'list_dir',
  'todo_write', 'ask_user_question', 'session_search', 'session_trace', 'skill',
])
const MCP_ACTION_HINTS = /(write|delete|remove|create|update|set|send|post|patch|move|rename|import|upload)/i

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

function isMcpTool(name: string): boolean {
  return name.startsWith('mcp_') || name.startsWith('mcp__')
}

/**
 * Named modes from harness_config: yolo disables every ask; auto keeps
 * modify/delete/shell; normal asks for all write kinds.
 */
export function installConfirm(ctx: Context, cfg: LuminaConfig): void {
  ctx.on('tools/pre-execute', async (exec, next) => {
    const rule = cfg.requireConfirm
    const root = workspaceRoot(cfg.workspace)

    if (WRITE_TOOLS.has(exec.name)) {
      const raw = filePathOf(exec.arguments)
      if (!raw) return next()
      const target = resolveTarget(raw, root)
      if (isInside(root, target)) return next()
      const allow = rule.writeNew || rule.writeModify
      if (!allow) return next()
      return ask(`write outside the workspace: ${target}`)
    }

    if (SHELL_TOOLS.has(exec.name)) {
      const command = commandOf(exec.arguments).trim()
      if (!command) return next()
      if (isReadOnlyShell(command)) return next()
      if (commandRunsWorkspaceScript(command, root)) return next()
      if (!rule.shell) return next()
      return ask(`shell command: ${command.slice(0, 160)}`)
    }

    if (FREE_TOOLS.has(exec.name)) return next()

    if (isMcpTool(exec.name)) {
      if (!rule.action) return next()
      if (!MCP_ACTION_HINTS.test(exec.name)) return next()
      return ask(`MCP action: ${exec.name}`)
    }

    return next()
  })
}

/** `python ./script.py` inside the workspace is the write→run loop, not a risk. */
function commandRunsWorkspaceScript(command: string, root: string): boolean {
  const first = command.split(/&&|;|\|\|/)[0]?.trim() ?? ''
  const match = /^(python3?|pypy3|node|bun|deno)\s+(?![-\s])(\S+)/.exec(first)
  if (!match) return false
  const script = resolveTarget(match[2]!, root)
  return isInside(root, script) && !isSafeExecutable(script)
}

function ask(reason: string): { kind: 'ask'; reason: string; displayReason: { en: string; zh: string } } {
  return {
    kind: 'ask',
    reason: `Lumina confirmation: ${reason}`,
    displayReason: {
      en: `Lumina wants confirmation before: ${reason}`,
      zh: `灵犀请求确认：${reason}`,
    },
  }
}
