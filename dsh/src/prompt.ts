/** Persona and grounding discipline, registered as dsh system-prompt sections. */

import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-system-prompt'
import type { LuminaConfig } from './config.js'

export const GROUNDING_RULES = `## Grounding rules (Lumina)

- A question about local files, directories, repository structure, or file contents requires a read tool (read / glob / grep / bash read-only) in this turn. Listing a directory is not enough for a content question.
- A question about current or external facts requires web_search / web_fetch in this turn.
- Never simulate tool output: no invented directory listings, no fake shell transcripts, no invented exit codes or test results.
- Report tool errors and empty results as they are; do not replace them with plausible text.`

export function installPrompt(ctx: Context, cfg: LuminaConfig): void {
  if (!cfg.prompt.enabled) return
  ctx.systemPrompt.section({
    name: 'lumina:persona',
    order: 0,
    text: cfg.prompt.persona,
  })
  ctx.systemPrompt.section({
    name: 'lumina:grounding',
    order: 120,
    text: GROUNDING_RULES,
  })
  if (cfg.shibei.recall) {
    const server = cfg.shibei.serverName
    ctx.systemPrompt.section({
      name: 'lumina:shibei-recall',
      order: 125,
      text: `## Personal knowledge recall (Shibei)

When the \`mcp__${server}__shibei_context\` tool is available, call it BEFORE answering any non-imperative question about the user's background, personal notes, projects, decisions, or past conversations. Pass the user's original message and 5–8 keywords (synonyms and Chinese/English variants). If the tool suggests remembering a new durable fact, call \`mcp__${server}__shibei_remember\` after answering. Do not use Shibei for pure coding or generic world-knowledge questions.`,
    })
  }
}
