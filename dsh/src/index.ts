/**
 * dsh-lumina — Lumina's product layer as one DeepSeek Harness plugin.
 *
 * The dsh runtime owns the agent loop, LLM adapters, sandbox, delegation and
 * sessions. This plugin keeps only Lumina's differentiators:
 *   prompt persona · workspace jail · confirmation policy · WriteGate
 *   grounding · memory · traces
 *
 * @module dsh-lumina
 */

import type { Context } from '@deepseek-ai/cordis'
import { resolveConfig, type LuminaConfig } from './config.js'
import { installConfirm } from './confirm.js'
import { installGrounding } from './grounding.js'
import { installJail } from './jail.js'
import { installMemory } from './memory.js'
import { installPrompt } from './prompt.js'
import { installTrace } from './trace.js'
import { installWriteGate } from './writegate.js'

export type {
  ConfirmRequire,
  GroundingConfig,
  LuminaConfig,
  MemoryConfig,
  PermissionMode,
  PromptConfig,
  ShibeiConfig,
  TraceConfig,
  TraceRetention,
  WriteGateConfig,
} from './config.js'
export { DEFAULT_CONFIG, DEFAULT_PERSONA, resolveConfig } from './config.js'
export { isInside, isReadOnlyShell, shellEscapesJail, workspaceRoot } from './paths.js'
export { memoryPath, mutateMemory, readMemory, searchMemory } from './memory.js'
export { proposalsRoot } from './writegate.js'

export const name = 'lumina'
export const inject = ['tools', 'systemPrompt']

/**
 * Mount the Lumina product layer.
 *
 * Order matters: WriteGate → jail → confirm. A child's draft-only violation or
 * a hard jail escape must never reach an approval prompt.
 */
export function apply(ctx: Context, config: Partial<LuminaConfig> = {}): void {
  const cfg = resolveConfig(config)
  installPrompt(ctx, cfg)
  installWriteGate(ctx, cfg)
  installJail(ctx, cfg)
  installConfirm(ctx, cfg)
  installGrounding(ctx, cfg)
  installTrace(ctx, cfg)
  installMemory(ctx, cfg)
}
