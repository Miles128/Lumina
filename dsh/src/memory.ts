/**
 * Memory: durable MEMORY.md facts plus a local note search.
 *
 * Ported from Lumina's three-layer memory (the session archive layer is now
 * dsh's own session log, so it is intentionally not duplicated here):
 *   - MEMORY.md is injected into every system prompt (frozen snapshot, capped)
 *   - a `memory` tool mutates it (add / replace / remove)
 *   - a `search_memory` tool searches MEMORY.md and any notes under the root
 */

import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-system-prompt'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type {} from '@deepseek-ai/dsh-tools'
import type { LuminaConfig } from './config.js'
import { expandHome } from './paths.js'

const MEMORY_FILE = 'MEMORY.md'
const POLLUTED = /^\s*(system|assistant|user):|^\[System\]/i

export function memoryRoot(cfg: LuminaConfig): string {
  return path.resolve(expandHome(cfg.memory.root))
}

export function memoryPath(cfg: LuminaConfig): string {
  return path.join(memoryRoot(cfg), MEMORY_FILE)
}

export function readMemory(cfg: LuminaConfig): string {
  try {
    return readFileSync(memoryPath(cfg), 'utf8').trim()
  } catch {
    return ''
  }
}

function appendFact(cfg: LuminaConfig, text: string): string {
  const line = text.trim()
  if (!line) return 'Error: empty text'
  if (POLLUTED.test(line)) return 'Skipped: looks like transcript pollution, not a fact'
  const existing = readMemory(cfg)
  if (existing.includes(line)) return 'Already present in MEMORY.md'
  const updated = `${existing}\n${line}`.trim().slice(0, cfg.memory.maxChars)
  writeMemory(cfg, updated)
  return `Added to MEMORY.md: ${line}`
}

function writeMemory(cfg: LuminaConfig, content: string): void {
  const root = memoryRoot(cfg)
  mkdirSync(root, { recursive: true })
  writeFileSync(memoryPath(cfg), content.trim().slice(0, cfg.memory.maxChars) + '\n', 'utf8')
}

export function mutateMemory(
  cfg: LuminaConfig,
  action: string,
  text: string,
  oldText: string,
): string {
  const content = readMemory(cfg)
  const normalized = action.trim().toLowerCase()

  if (normalized === 'add') return appendFact(cfg, text)

  if (normalized === 'replace' || normalized === 'remove') {
    const needle = oldText.trim()
    if (!needle) return `Error: old_text is required for ${normalized}`
    const first = content.indexOf(needle)
    if (first < 0) return `Not found in MEMORY.md: ${needle}`
    if (content.indexOf(needle, first + needle.length) >= 0) {
      return `Error: old_text appears more than once; pass a unique substring`
    }
    const next = normalized === 'remove'
      ? content.replace(needle, '').replace(/\n{3,}/g, '\n\n')
      : content.replace(needle, text.trim())
    writeMemory(cfg, next)
    return `${normalized === 'remove' ? 'Removed' : 'Replaced'} in MEMORY.md`
  }

  return `Error: unknown action ${action} (expected add / replace / remove)`
}

interface NoteHit {
  file: string
  line: number
  text: string
}

export function searchMemory(cfg: LuminaConfig, query: string, limit = 5): NoteHit[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return []
  const root = memoryRoot(cfg)
  const files: string[] = []
  try {
    for (const name of readdirSync(root)) {
      if (name.endsWith('.md')) files.push(path.join(root, name))
    }
  } catch {
    return []
  }

  const hits: NoteHit[] = []
  for (const file of files) {
    let content = ''
    try {
      if (!statSync(file).isFile()) continue
      content = readFileSync(file, 'utf8')
    } catch {
      continue
    }
    content.split('\n').forEach((line, index) => {
      if (line.toLowerCase().includes(needle)) {
        hits.push({ file: path.basename(file), line: index + 1, text: line.trim().slice(0, 300) })
      }
    })
  }
  return hits.slice(0, Math.max(1, limit))
}

export function installMemory(ctx: Context, cfg: LuminaConfig): void {
  if (!cfg.memory.enabled) return

  if (cfg.memory.inject) {
    ctx.systemPrompt.section({
      name: 'lumina:memory',
      order: 5,
      text: () => {
        const memory = readMemory(cfg)
        if (!memory) return ''
        return `## MEMORY.md (durable facts about the user and this machine)\n\n${memory}`
      },
    })
  }

  ctx.tools.register(defineTool({
    name: 'memory',
    description:
      'Manage the durable cross-session MEMORY.md (user facts, environment and project facts). '
      + 'Actions: add, replace (needs old_text), remove (needs old_text). '
      + 'Do not store transient task state here.',
    parameters: {
      action: { type: 'string', required: true, enum: ['add', 'replace', 'remove'] },
      text: { type: 'string', description: 'Text to add, or the replacement text' },
      old_text: { type: 'string', description: 'Unique substring to replace or remove' },
    },
    output: {
      schema: { type: 'object', additionalProperties: false, properties: { result: { type: 'string', required: true } } },
      render: (_args, value) => [{ type: 'text', text: value.result }],
    },
    execute: async (args) => ({
      result: mutateMemory(cfg, args.action, args.text ?? '', args.old_text ?? ''),
    }),
  }))

  ctx.tools.register(defineTool({
    name: 'search_memory',
    description: 'Search MEMORY.md and local memory notes for a literal string.',
    parameters: {
      query: { type: 'string', required: true },
      limit: { type: 'integer', description: 'Max results (default 5)' },
    },
    output: {
      schema: { type: 'object', additionalProperties: false, properties: { result: { type: 'string', required: true } } },
      render: (_args, value) => [{ type: 'text', text: value.result }],
    },
    execute: async (args) => {
      const hits = searchMemory(cfg, args.query, args.limit ?? 5)
      return {
        result: hits.length
          ? hits.map((hit, index) => `${index + 1}. ${hit.file}:${hit.line}\n   ${hit.text}`).join('\n')
          : 'No matching memory found.',
      }
    },
  }))
}

export function ensureMemoryRoot(cfg: LuminaConfig): void {
  const root = memoryRoot(cfg)
  if (!existsSync(root)) mkdirSync(root, { recursive: true })
}
