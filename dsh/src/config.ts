/**
 * Lumina configuration surface (PRD FR-52). The dsh bundle patch supplies an
 * empty config; every field below has a code-level default so a bare row works.
 */

export type PermissionMode = 'normal' | 'auto' | 'yolo' | 'custom'
export type TraceRetention = 'full' | 'summary' | 'off'

export interface ConfirmRequire {
  writeNew: boolean
  writeModify: boolean
  writeDelete: boolean
  shell: boolean
  action: boolean
}

export interface GroundingConfig {
  enabled: boolean
  /** Extra model steps allowed to repair an ungrounded answer. */
  maxRetries: number
}

export interface TraceConfig {
  enabled: boolean
  root: string
  retention: TraceRetention
  retainDays: number
}

export interface PromptConfig {
  enabled: boolean
  persona: string
}

export interface LuminaConfig {
  /** Workspace root used by the jail and the confirmation policy. Defaults to cwd. */
  workspace?: string
  /** Hard write jail: writes and shell paths must stay under `workspace`. */
  jail: boolean
  /** 完全权限: disable the jail and let confirmation decide instead. */
  fullFsAccess: boolean
  permissionMode: PermissionMode
  requireConfirm: ConfirmRequire
  grounding: GroundingConfig
  trace: TraceConfig
  prompt: PromptConfig
}

export const DEFAULT_PERSONA = `## Lumina (灵犀)

You are Lumina (灵犀), a local-first Agent productivity tool running on the user's machine.
Style: concise, conclusion first, short sentences, no filler.

Boundaries:
- MEMORY.md, local files, and search hits describe the user, never Lumina itself.
- When asked about your own identity or stack, answer as Lumina; do not borrow the user's profile.
- Never fabricate personal facts about the user.

Grounding:
- For questions about local files, directories, or file contents, call a read tool before answering.
- For current events or anything beyond your knowledge, call web_search/web_fetch before answering.
- Never imitate tool output (directory listings, shell transcripts, exit codes): only report what a tool actually returned.
- If a tool returned an error or "not found", say so explicitly.`

function preset(mode: PermissionMode): ConfirmRequire {
  switch (mode) {
    case 'yolo':
      return { writeNew: false, writeModify: false, writeDelete: false, shell: false, action: false }
    case 'auto':
      return { writeNew: false, writeModify: true, writeDelete: true, shell: true, action: false }
    default:
      return { writeNew: true, writeModify: true, writeDelete: true, shell: true, action: true }
  }
}

export const DEFAULT_CONFIG: LuminaConfig = {
  jail: true,
  fullFsAccess: false,
  permissionMode: 'normal',
  requireConfirm: preset('normal'),
  grounding: { enabled: true, maxRetries: 2 },
  trace: { enabled: true, root: '~/.lumina/traces', retention: 'full', retainDays: 30 },
  prompt: { enabled: true, persona: DEFAULT_PERSONA },
}

export function resolveConfig(input: Partial<LuminaConfig> = {}): LuminaConfig {
  const mode = input.permissionMode ?? DEFAULT_CONFIG.permissionMode
  const base = preset(mode)
  return {
    ...DEFAULT_CONFIG,
    ...input,
    requireConfirm: { ...base, ...(input.requireConfirm ?? {}) },
    grounding: { ...DEFAULT_CONFIG.grounding, ...(input.grounding ?? {}) },
    trace: { ...DEFAULT_CONFIG.trace, ...(input.trace ?? {}) },
    prompt: { ...DEFAULT_CONFIG.prompt, ...(input.prompt ?? {}) },
  }
}
