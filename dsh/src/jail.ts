/**
 * Hard workspace jail for write/edit and shell absolute paths.
 *
 * Mirrors Lumina's fs_jail: reads are unrestricted, writes and shell paths must
 * stay under the workspace. `fullFsAccess` (完全权限) disables the jail and lets
 * the confirmation policy ask instead.
 */

import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-tools'
import type { LuminaConfig } from './config.js'
import { isInside, resolveTarget, shellEscapesJail, workspaceRoot } from './paths.js'

const WRITE_TOOLS = new Set(['write', 'edit', 'str_replace_editor', 'multi_edit'])
const SHELL_TOOLS = new Set(['bash', 'pwsh'])

function filePathOf(args: unknown): string | null {
  if (!args || typeof args !== 'object') return null
  const record = args as Record<string, unknown>
  const value = record.file_path ?? record.path
  return typeof value === 'string' ? value : null
}

export function installJail(ctx: Context, cfg: LuminaConfig): void {
  if (!cfg.jail) return

  ctx.on('tools/pre-execute', async (exec, next) => {
    if (cfg.fullFsAccess) return next()
    const root = workspaceRoot(cfg.workspace, exec.agent?.session?.header?.cwd)

    if (WRITE_TOOLS.has(exec.name)) {
      const raw = filePathOf(exec.arguments)
      if (raw) {
        const target = resolveTarget(raw, root)
        if (!isInside(root, target)) {
          return {
            kind: 'deny',
            reason:
              `sandbox: cannot write outside the workspace \`${root}\`: ${target}. ` +
              'Enable 完全权限 or write inside the workspace.',
          }
        }
      }
      return next()
    }

    if (SHELL_TOOLS.has(exec.name)) {
      const args = exec.arguments as Record<string, unknown> | null
      const command = typeof args?.command === 'string' ? args.command : ''
      const escape = shellEscapesJail(command, root)
      if (escape) return { kind: 'deny', reason: escape }
      return next()
    }

    return next()
  })
}
