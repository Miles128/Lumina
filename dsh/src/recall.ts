/**
 * Optional Shibei auto-recall.
 *
 * When `shibei.autoRecall` is on, the plugin calls the Shibei MCP tool
 * `mcp__<server>__shibei_context` before the first step of a turn and prepends
 * a bounded, source-labelled context block to the user message. Off by default:
 * it costs one MCP round-trip and can add latency.
 */

import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-tools'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import type { LuminaConfig } from './config.js'

interface RecallDoc {
  source?: string
  file_path?: string
  text?: string
}

interface RecallMemory {
  text?: string
  memory_type?: string
  priority?: number
  scene_name?: string
}

interface RecallData {
  results?: RecallDoc[]
  memories?: RecallMemory[]
  persona?: { categories?: Record<string, string[]> }
}

/** Render a compact recall block; returns '' when nothing useful was recalled. */
export function formatRecall(data: RecallData, maxChars: number): string {
  const lines: string[] = []

  const docs = (data.results ?? []).slice(0, 3)
  if (docs.length) {
    lines.push('相关笔记：')
    for (const doc of docs) {
      const source = (doc.source ?? doc.file_path ?? '').split('/').pop() ?? ''
      const text = (doc.text ?? '').replace(/\s+/g, ' ').trim()
      if (!text) continue
      lines.push(`- [${source}] ${text.slice(0, 260)}`)
    }
  }

  const memories = (data.memories ?? []).slice(0, 3)
  if (memories.length) {
    lines.push('相关记忆：')
    for (const memory of memories) {
      const text = (memory.text ?? '').trim()
      if (!text) continue
      const kind = memory.memory_type ? `${memory.memory_type}` : 'memory'
      lines.push(`- (${kind}) ${text.slice(0, 200)}`)
    }
  }

  const categories = data.persona?.categories ?? {}
  const personaLines = Object.entries(categories)
    .flatMap(([category, facts]) => (facts ?? []).slice(0, 2).map((fact) => `- (${category}) ${fact.slice(0, 160)}`))
  if (personaLines.length) {
    lines.push('长期画像：', ...personaLines.slice(0, 5))
  }

  if (!lines.length) return ''
  return lines.join('\n').slice(0, Math.max(120, maxChars))
}

interface UserMessageLike {
  role?: string
  source?: unknown
  content?: Array<{ type: string; text?: string }>
}

function textOf(message: UserMessageLike): string {
  return (message.content ?? [])
    .filter((block) => block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
    .trim()
}

export function installAutoRecall(ctx: Context, cfg: LuminaConfig): void {
  if (!cfg.shibei.autoRecall) return
  const seen = new Set<string>()
  let counter = 0

  ctx.on('agent/pre-step', async (payload, next) => {
    const messages = payload.messages as unknown as UserMessageLike[]
    const userMessage = [...messages].reverse().find(
      (message) => message.role === 'user' && (message.source as { kind?: string })?.kind === 'user',
    )
    if (!userMessage) return next()

    const text = textOf(userMessage)
    if (text.length < 6) return next()

    const key = `${String(payload.agent.session.id)}:${payload.turn}`
    if (seen.has(key)) return next()
    if (seen.size > 2000) seen.clear()
    seen.add(key)

    const toolName = `mcp__${cfg.shibei.serverName}__shibei_context`
    if (!ctx.tools.get(toolName)) return next()

    let result: { isError?: boolean; content?: Array<{ type: string; text?: string }> }
    try {
      result = await ctx.tools.execute({
        callId: `lumina-recall-${++counter}` as never,
        name: toolName,
        arguments: { message: text, limit: cfg.shibei.topK },
        agent: payload.agent,
        signal: AbortSignal.timeout(cfg.shibei.timeoutMs),
      }) as unknown as typeof result
    } catch {
      return next()
    }
    if (result.isError) return next()

    const raw = (result.content ?? [])
      .filter((block) => block.type === 'text' && typeof block.text === 'string')
      .map((block) => block.text!)
      .join('\n')
    if (!raw.trim()) return next()

    let context = ''
    try {
      context = formatRecall(JSON.parse(raw) as RecallData, cfg.shibei.maxChars)
    } catch {
      context = raw.slice(0, cfg.shibei.maxChars)
    }
    if (!context.trim()) return next()

    const replaced = messages.map((message) => {
      if (message !== userMessage) return message
      return createUserMessage({
        content: [
          { type: 'text', text: `[Shibei recall]\n${context}\n\n` },
          ...((message.content ?? []) as never[]),
        ],
        source: (message.source ?? { kind: 'user' }) as never,
      })
    })

    return { kind: 'enter', messages: replaced as never }
  })
}
