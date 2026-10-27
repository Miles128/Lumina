/**
 * dsh-lumina-shibei — Shibei recall for Lumina.
 *
 * Scope:
 *   - prompt rule: personal/background questions call shibei_context first
 *   - optional auto-recall: inject Shibei context before each turn
 *
 * The MCP connection itself lives in the dsh profile (mcp-shibei row) because
 * command paths and credentials are deployment-specific.
 */

import type { Context } from '@deepseek-ai/cordis'
import { resolveConfig, type Config } from './config.js'
import { installShibei } from './prompt.js'
import { installAutoRecall } from './recall.js'

export type { Config } from './config.js'
export { DEFAULT_CONFIG, resolveConfig } from './config.js'
export { formatRecall } from './recall.js'
export { shibeiRule } from './prompt.js'

export const name = 'lumina-shibei'
export const inject = ['tools', 'systemPrompt']

export function apply(ctx: Context, config: Partial<Config> = {}): void {
  const cfg = resolveConfig(config)
  installShibei(ctx, cfg)
  installAutoRecall(ctx, cfg)
}
