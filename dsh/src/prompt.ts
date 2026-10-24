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
}
