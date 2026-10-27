/** Path helpers. */

import os from 'node:os'
import path from 'node:path'

/** Expand `~` and `~/…`. */
export function expandHome(input: string): string {
  if (input === '~') return os.homedir()
  if (input.startsWith('~/')) return path.join(os.homedir(), input.slice(2))
  return input
}
