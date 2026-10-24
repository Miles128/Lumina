/** Path, shell, and workspace helpers shared by the jail and confirm plugins. */

import os from 'node:os'
import path from 'node:path'

/** Expand `~` and `~/…` the way the dsh tools do. */
export function expandHome(input: string): string {
  if (input === '~') return os.homedir()
  if (input.startsWith('~/')) return path.join(os.homedir(), input.slice(2))
  return input
}

/** Absolute workspace root, resolved once per call. */
export function workspaceRoot(configured?: string): string {
  return path.resolve(expandHome(configured ?? process.cwd()))
}

/** Resolve a user/model supplied path against the workspace root. */
export function resolveTarget(raw: string, root: string): string {
  return path.resolve(root, expandHome(raw))
}

/** True when `target` is the root or lives inside it. */
export function isInside(root: string, target: string): boolean {
  const rel = path.relative(root, target)
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel))
}

const READ_ONLY_COMMANDS = new Set([
  'ls', 'find', 'mdfind', 'mdls', 'pwd', 'cat', 'head', 'tail', 'less', 'more',
  'grep', 'rg', 'wc', 'sort', 'uniq', 'cut', 'stat', 'du', 'tree', 'fd', 'test',
  'nl', 'xxd', 'xattr', 'which', 'type', 'echo', 'printf', 'date', 'whoami',
])

/**
 * Conservative read-only check: chained commands, pipes, and writes are never
 * treated as read-only, so a false negative only costs one confirmation.
 */
export function isReadOnlyShell(command: string): boolean {
  const text = command.trim()
  if (!text) return false
  if (text.includes('&&') || text.includes('||') || text.includes(';')) return false
  if (text.includes('>>')) return false
  for (const match of text.matchAll(/(?<!\d)>\s*(\S+)|\d>\s*(\S+)/g)) {
    const target = (match[1] ?? match[2] ?? '').trim()
    if (target !== '/dev/null') return false
  }
  if (text.includes('<') && !text.includes('</')) return false
  for (const segment of text.split('\n')) {
    for (const part of segment.split('|')) {
      const argv = splitShellWords(part.trim())
      if (!argv.length) return false
      if (!READ_ONLY_COMMANDS.has(argv[0]!.toLowerCase())) return false
    }
  }
  return true
}

/**
 * Minimal POSIX-ish word splitter: quotes and backslash escapes are honored.
 * Returns [] when quoting is unbalanced (the caller then fails closed).
 */
export function splitShellWords(input: string): string[] {
  const out: string[] = []
  let current = ''
  let quote: '"' | "'" | null = null
  let escaped = false
  for (const char of input) {
    if (escaped) {
      current += char
      escaped = false
      continue
    }
    if (char === '\\' && quote !== "'") {
      escaped = true
      continue
    }
    if (quote) {
      if (char === quote) quote = null
      else current += char
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      continue
    }
    if (/\s/.test(char)) {
      if (current) {
        out.push(current)
        current = ''
      }
      continue
    }
    current += char
  }
  if (escaped || quote) return []
  if (current) out.push(current)
  return out
}

/** Absolute-path candidates in a shell command, mirroring Lumina's fs_jail regex. */
const ABS_PATH_RE = /(?:(?<=\s)|^|[=:'"])(~(?:\/[^\s'"`;|&><]*)?|\/[A-Za-z0-9._+-][^\s'"`;|&><]*)/g

const SAFE_EXECUTABLE_DIRS = [
  '/usr/bin', '/bin', '/usr/sbin', '/sbin', '/usr/local/bin',
  '/opt/homebrew/bin', '/opt/homebrew/Cellar',
]

const ALLOWED_DEVICE_PATHS = new Set(['/dev/null', '/dev/stdin', '/dev/stdout', '/dev/stderr'])

/** True when the path names an interpreter/CLI binary we should not jail. */
export function isSafeExecutable(target: string): boolean {
  return SAFE_EXECUTABLE_DIRS.some((dir) => isInside(dir, target))
}

/**
 * Return an error message when the command references an absolute path outside
 * the workspace, or null when every path stays inside (or is allowlisted).
 */
export function shellEscapesJail(command: string, root: string): string | null {
  for (const match of command.matchAll(ABS_PATH_RE)) {
    const raw = match[1]!.replace(/[)\]},.]+$/, '')
    if (!raw || raw === '/' || raw === '~') continue
    const resolved = path.resolve(expandHome(raw))
    if (ALLOWED_DEVICE_PATHS.has(resolved)) continue
    if (isSafeExecutable(resolved)) continue
    if (isInside(root, resolved)) continue
    return `sandbox: shell command references a path outside the workspace \`${root}\`: ${resolved}. Use relative paths or enable 完全权限.`
  }
  return null
}
