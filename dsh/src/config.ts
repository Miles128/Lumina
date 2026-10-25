/**
 * Lumina configuration surface. A bare bundle row works: every field has a
 * code-level default.
 */

export interface MemoryConfig {
  enabled: boolean
  root: string
  /** Inject MEMORY.md into the system prompt on every assembly. */
  inject: boolean
  maxChars: number
}

export interface ShibeiConfig {
  /** Add an answer-first recall rule for the Shibei MCP server. */
  recall: boolean
  /** MCP serverName configured on dsh-mcp-client. */
  serverName: string
}

export interface LuminaConfig {
  memory: MemoryConfig
  shibei: ShibeiConfig
}

export const DEFAULT_CONFIG: LuminaConfig = {
  memory: { enabled: true, root: '~/.lumina/memories', inject: true, maxChars: 4000 },
  shibei: { recall: true, serverName: 'shibei' },
}

export function resolveConfig(input: Partial<LuminaConfig> = {}): LuminaConfig {
  return {
    memory: { ...DEFAULT_CONFIG.memory, ...(input.memory ?? {}) },
    shibei: { ...DEFAULT_CONFIG.shibei, ...(input.shibei ?? {}) },
  }
}
