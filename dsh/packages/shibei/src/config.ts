/** Shibei plugin configuration. */

export interface Config {
  /** MCP serverName configured on dsh-mcp-client. */
  serverName: string
  /** Add the answer-first recall rule. */
  recall: boolean
  /** Inject recall results before each step. */
  autoRecall: boolean
  topK: number
  maxChars: number
  timeoutMs: number
}

export const DEFAULT_CONFIG: Config = {
  serverName: 'shibei',
  recall: true,
  autoRecall: false,
  topK: 3,
  maxChars: 1200,
  timeoutMs: 8000,
}

export function resolveConfig(input: Partial<Config> = {}): Config {
  return { ...DEFAULT_CONFIG, ...input }
}
