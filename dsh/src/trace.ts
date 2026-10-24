/**
 * Durable local trace store (FR-51). Every committed session event that carries
 * decision value is appended to `{root}/{session}.jsonl`; the dsh session log
 * remains the source of truth, the trace file is the audit/export surface.
 */

import { appendFileSync, mkdirSync, readdirSync, statSync, unlinkSync } from 'node:fs'
import path from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-session'
import type { LuminaConfig } from './config.js'
import { expandHome } from './paths.js'

const TRACE_EVENTS = new Set([
  'user/message', 'assistant/message', 'tool/call', 'tool/result',
  'turn/start', 'turn/end', 'agent/error', 'approval/request', 'approval/outcome',
])

const SAFE_ID = /^[A-Za-z0-9._:-]{1,128}$/
const SUMMARY_LIMIT = 200

interface TraceEvent {
  type: string
  turn?: number
  step?: number
  seq?: number
  time?: number
  name?: string
  callId?: string
  message?: { role?: string; content?: Array<{ type: string; text?: string }>; isError?: boolean; source?: { kind?: string } }
  error?: unknown
}

function traceRoot(cfg: LuminaConfig): string {
  return path.resolve(expandHome(cfg.trace.root))
}

function safeId(id: string): string | null {
  if (!SAFE_ID.test(id)) return null
  return id.replace(/[/\\]/g, '_')
}

function clip(text: string, retention: string): string {
  return retention === 'summary' ? text.slice(0, SUMMARY_LIMIT) : text
}

function project(sessionId: string, event: TraceEvent, retention: string): Record<string, unknown> {
  const text = event.message?.content
    ?.filter((block) => block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n') ?? ''
  return {
    ts: Date.now(),
    trace_id: sessionId,
    seq: event.seq,
    turn: event.turn,
    step: event.step,
    kind: event.type,
    tool_name: event.name,
    call_id: event.callId,
    role: event.message?.role,
    is_error: event.message?.isError,
    text: clip(text, retention),
    error: event.error ? clip(String(event.error), retention) : undefined,
  }
}

export function installTrace(ctx: Context, cfg: LuminaConfig): void {
  if (!cfg.trace.enabled || cfg.trace.retention === 'off') return
  const root = traceRoot(cfg)
  try {
    mkdirSync(root, { recursive: true })
    if (cfg.trace.retainDays > 0) prune(root, cfg.trace.retainDays)
  } catch {
    /* an unwritable trace root must not break the agent */
  }

  ctx.on('session/event', (session, event) => {
    const typed = event as unknown as TraceEvent
    if (!TRACE_EVENTS.has(typed.type)) return
    const id = safeId(String(session.id ?? ''))
    if (!id) return
    try {
      appendFileSync(
        path.join(root, `${id}.jsonl`),
        JSON.stringify(project(id, typed, cfg.trace.retention)) + '\n',
        'utf8',
      )
    } catch {
      /* traces are best effort; never block a turn */
    }
  })
}

function prune(root: string, retainDays: number): void {
  const cutoff = Date.now() - retainDays * 86_400_000
  for (const name of readdirSync(root)) {
    if (!name.endsWith('.jsonl')) continue
    const full = path.join(root, name)
    try {
      if (statSync(full).mtimeMs < cutoff) unlinkSync(full)
    } catch {
      /* ignore */
    }
  }
}
