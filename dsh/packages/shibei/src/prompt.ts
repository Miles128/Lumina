/**
 * Shibei recall rule.
 *
 * Shibei is a local knowledge base exposed as an MCP server. The rule tells the
 * model to pull context before answering questions about the user's background,
 * notes, projects, or past decisions.
 */

import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-system-prompt'
import type { Config } from './config.js'

export function shibeiRule(serverName: string): string {
  return `## Personal knowledge recall (Shibei)

When the \`mcp__${serverName}__shibei_context\` tool is available, call it BEFORE answering any non-imperative question about the user's background, personal notes, projects, decisions, or past conversations. Pass the user's original message and 5–8 keywords (synonyms and Chinese/English variants). If the tool suggests remembering a new durable fact, call \`mcp__${serverName}__shibei_remember\` after answering. Do not use Shibei for pure coding or generic world-knowledge questions.`
}

export function installShibei(ctx: Context, cfg: Config): void {
  if (!cfg.recall) return
  ctx.systemPrompt.section({
    name: 'lumina:shibei-recall',
    order: 125,
    text: shibeiRule(cfg.serverName),
  })
}
