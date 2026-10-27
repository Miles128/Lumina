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
  /**
   * Inject Shibei recall results before each step instead of relying on the
   * model to call shibei_context. Off by default (costs one MCP call per turn).
   */
  autoRecall: boolean
  /** Max documents + memories to include. */
  topK: number
  /** Hard cap for the injected text. */
  maxChars: number
  /** Timeout for the recall tool call. */
  timeoutMs: number
}

export interface LuminaConfig {
  memory: MemoryConfig
  shibei: ShibeiConfig
}

export const DEFAULT_CONFIG: LuminaConfig = {
  memory: { enabled: true, root: '~/.lumina/memories', inject: true, maxChars: 4000 },
  shibei: {
    recall: true,
    serverName: 'shibei',
    autoRecall: false,
    topK: 3,
    maxChars: 1200,
    timeoutMs: 8000,
  },
}

export function resolveConfig(input: Partial<LuminaConfig> = {}): LuminaConfig {
  return {
    memory: { ...DEFAULT_CONFIG.memory, ...(input.memory ?? {}) },
    shibei: { ...DEFAULT_CONFIG.shibei, ...(input.shibei ?? {}) },
  }
}
