/**
 * dsh-lumina — Lumina's product layer as one DeepSeek Harness plugin.
 *
 * The dsh runtime owns the agent loop, LLM adapters, sandbox, delegation and
 * sessions. This plugin keeps only Lumina's differentiators:
 *   prompt persona · workspace jail · confirmation policy · grounding · traces
 *
 * @module dsh-lumina
 */

import type { Context } from '@deepseek-ai/cordis'
import { resolveConfig, type LuminaConfig } from './config.js'
import { installConfirm } from './confirm.js'
import { installGrounding } from './grounding.js'
import { installJail } from './jail.js'
import { installPrompt } from './prompt.js'
import { installTrace } from './trace.js'

export type {
  ConfirmRequire,
  GroundingConfig,
  LuminaConfig,
  PermissionMode,
  PromptConfig,
  TraceConfig,
  TraceRetention,
} from './config.js'
export { DEFAULT_CONFIG, DEFAULT_PERSONA, resolveConfig } from './config.js'
export { isInside, isReadOnlyShell, shellEscapesJail, workspaceRoot } from './paths.js'

export const name = 'lumina'
export const inject = ['tools', 'systemPrompt']

/**
 * Mount the Lumina product layer.
 *
 * The jail registers before the confirmation policy so a hard-denied write
 * never reaches the approval prompt.
 */
export function apply(ctx: Context, config: Partial<LuminaConfig> = {}): void {
  const cfg = resolveConfig(config)
  installPrompt(ctx, cfg)
  installJail(ctx, cfg)
  installConfirm(ctx, cfg)
  installGrounding(ctx, cfg)
  installTrace(ctx, cfg)
}
