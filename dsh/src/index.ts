/**
 * dsh-lumina — Lumina's product layer as one DeepSeek Harness plugin.
 *
 * Scope: durable memory (MEMORY.md + tools), Shibei recall, and the
 * conversation tree (separate client plugin `dsh-forkmap`).
 *
 * The dsh runtime owns the loop, LLM adapters, sandbox, permissions,
 * delegation, sessions, traces and prompt persona.
 *
 * @module dsh-lumina
 */

import type { Context } from '@deepseek-ai/cordis'
import { resolveConfig, type LuminaConfig } from './config.js'
import { installMemory } from './memory.js'
import { installAutoRecall } from './recall.js'
import { installShibei } from './shibei.js'

export type { LuminaConfig, MemoryConfig, ShibeiConfig } from './config.js'
export { DEFAULT_CONFIG, resolveConfig } from './config.js'
export { memoryPath, mutateMemory, readMemory, searchMemory } from './memory.js'
export { formatRecall } from './recall.js'
export { shibeiRule } from './shibei.js'

export const name = 'lumina'
export const inject = ['tools', 'systemPrompt']

export function apply(ctx: Context, config: Partial<LuminaConfig> = {}): void {
  const cfg = resolveConfig(config)
  installShibei(ctx, cfg)
  installMemory(ctx, cfg)
  installAutoRecall(ctx, cfg)
}
