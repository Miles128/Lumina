/**
 * Grounding enforcement at the turn boundary.
 *
 * Lumina's rule: a filesystem/content question must be answered from a read
 * tool, not from model memory. dsh exposes `agent/turn-stopping`, where a
 * listener may steer the agent and force another step — the same retry loop
 * Lumina implements with explicit verification. Retries are capped per turn.
 *
 * Evidence is accumulated from the live `session/event` stream so this plugin
 * never reads the session log synchronously.
 */

import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-session'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import type { LuminaConfig } from './config.js'

const LISTING_MARKERS = [
  '有哪些', '列出', '列出来', '目录结构', '项目结构', '里有什么', '里面有什么',
  'list ', 'ls ', 'what files', 'which files', 'directory structure',
]

const CONTENT_MARKERS = [
  '内容是什么', '文件内容', '读一下', '读取', '打开看看', '打开文件', '总结', '概括',
  '讲了什么', '写了什么', '说了什么', '作者', 'summarize', 'what does', 'read the file',
]

const FS_MARKERS = [
  '文件', '目录', '路径', '文件夹', '代码库', '项目结构', '仓库', '本地', '磁盘',
  'readme', 'file', 'folder', 'directory', 'repo', 'workspace',
]

const WEB_MARKERS = ['联网', '网上', '搜索一下', '最新', '新闻', 'trending', 'web search', 'google']

const PATH_RE = /(?:^|[\s(（"'`])(~\/[^\s"'`]+|\/[A-Za-z0-9._+-][^\s"'`]*|\.{1,2}\/[^\s"'`]+)/
const FILE_EXT_RE = /\b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|md|yaml|yml|toml|txt|csv|rs|go|java|html|css|sh)\b/i

const READ_TOOLS = new Set(['read', 'read_image'])
const DISCOVERY_TOOLS = new Set(['glob', 'grep', 'bash', 'pwsh', 'list_dir', 'ls'])

interface TurnState {
  turn: number
  question: string
  reply: string
  tools: Set<string>
  commands: string[]
}

interface MessageLike {
  content?: Array<{ type: string; text?: string }>
  source?: { kind?: string }
}

interface EventLike {
  type: string
  turn?: number
  message?: MessageLike
  name?: string
  arguments?: string
}

function textOf(message: MessageLike | undefined): string {
  if (!message?.content) return ''
  return message.content
    .filter((block) => block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
    .trim()
}

function isWebQuestion(text: string): boolean {
  const lowered = text.toLowerCase()
  return WEB_MARKERS.some((marker) => lowered.includes(marker))
}

export function isContentQuestion(text: string): boolean {
  if (isWebQuestion(text)) return false
  const lowered = text.toLowerCase()
  if (CONTENT_MARKERS.some((marker) => text.includes(marker) || lowered.includes(marker))) return true
  return FILE_EXT_RE.test(text)
}

export function isFilesystemQuestion(text: string): boolean {
  if (!text || isWebQuestion(text)) return false
  const lowered = text.toLowerCase()
  if (FS_MARKERS.some((marker) => text.includes(marker) || lowered.includes(marker))) return true
  return PATH_RE.test(text)
}

export function installGrounding(ctx: Context, cfg: LuminaConfig): void {
  if (!cfg.grounding.enabled) return
  const states = new Map<string, TurnState>()
  const attempts = new Map<string, number>()

  ctx.on('session/event', (session, event) => {
    const typed = event as unknown as EventLike
    const id = String(session.id ?? '')
    if (!id) return

    if (typed.type === 'turn/start') {
      states.set(id, { turn: typed.turn ?? 0, question: '', reply: '', tools: new Set(), commands: [] })
      return
    }
    const state = states.get(id)
    if (!state) return

    if (typed.type === 'user/message') {
      if (typed.message?.source?.kind === 'user') state.question = textOf(typed.message)
      return
    }
    if (typed.type === 'assistant/message') {
      const turn = typed.turn ?? state.turn
      if (turn === state.turn) state.reply = textOf(typed.message)
      return
    }
    if (typed.type === 'tool/call') {
      if (typed.name) {
        state.tools.add(typed.name)
        if (/^(bash|pwsh)$/.test(typed.name)) {
          try {
            const args = JSON.parse(typed.arguments ?? '{}') as { command?: string }
            if (args.command) state.commands.push(args.command)
          } catch {
            /* malformed args are the tool layer's problem */
          }
        }
      }
      return
    }
    if (typed.type === 'turn/end') {
      attempts.delete(`${id}:${state.turn}`)
    }
  })

  ctx.on('agent/turn-stopping', async ({ agent, turn }) => {
    const id = String(agent.session.id ?? '')
    const state = states.get(id)
    if (!state || state.turn !== turn) return
    const question = state.question
    const reply = state.reply
    if (!question || !reply) return

    // A clarifying question is not a fabricated answer.
    if (reply.length < 80 && /[?？]\s*$/.test(reply)) return

    const contentQuestion = isContentQuestion(question)
    const filesystemQuestion = isFilesystemQuestion(question)
    if (!contentQuestion && !filesystemQuestion) return

    const hasRead = [...state.tools].some((name) => READ_TOOLS.has(name))
    const hasDiscovery = [...state.tools].some((name) => DISCOVERY_TOOLS.has(name))
      || state.commands.some((command) => /^(ls|find|tree|cat|head|tail|grep|rg|wc|stat)\b/.test(command.trim()))
    const satisfied = contentQuestion ? hasRead : hasRead || hasDiscovery
    if (satisfied) return

    const key = `${id}:${turn}`
    const tried = attempts.get(key) ?? 0
    if (tried >= cfg.grounding.maxRetries) return
    attempts.set(key, tried + 1)

    agent.steer(createUserMessage({
      content: [{
        type: 'text',
        text: contentQuestion
          ? (LISTING_MARKERS.some((marker) => question.includes(marker))
            ? '[Lumina grounding] 你刚才没有查看目录就回答了本地文件问题。请先用 glob、grep 或只读 bash（ls / find）确认真实结果，再重写回答。'
            : '[Lumina grounding] 你刚才没有读取文件就开始回答内容问题。请先用 read 工具读取相关文件，再基于真实内容重写回答；未读到的内容不要猜测。')
          : '[Lumina grounding] 你刚才没有查看目录就用记忆描述了本地文件/目录。请先用 glob、grep 或只读 bash（ls / find）确认真实结果，再重写回答。',
      }],
      source: { kind: 'user' },
    }))
  })

  ctx.on('agent/disposed', ({ agent }) => {
    const id = String(agent.session.id ?? '')
    states.delete(id)
    for (const key of attempts.keys()) {
      if (key.startsWith(`${id}:`)) attempts.delete(key)
    }
  })
}
