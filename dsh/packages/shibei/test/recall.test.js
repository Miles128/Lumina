import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveConfig } from '../dist/config.js'
import { formatRecall, installAutoRecall } from '../dist/recall.js'

const DATA = {
  results: [
    { source: '/notes/rag.md', text: 'RAG 复盘：混合检索 + 意图路由' },
    { source: '/notes/noteai.md', text: 'NoteAI 用 sqlite-vec + BM25s' },
  ],
  memories: [
    { text: '用户决定用 dsh 原生 workflow', memory_type: 'instruction', priority: 90 },
  ],
  persona: { categories: { project: ['Lumina 是 dsh 插件'] } },
}

test('formatRecall renders docs, memories and persona', () => {
  const text = formatRecall(DATA, 1200)
  assert.match(text, /相关笔记/)
  assert.match(text, /rag\.md/)
  assert.match(text, /相关记忆/)
  assert.match(text, /instruction/)
  assert.match(text, /长期画像/)
})

test('formatRecall returns empty for nothing useful', () => {
  assert.equal(formatRecall({}, 1200), '')
})

test('formatRecall caps output', () => {
  const text = formatRecall(DATA, 80)
  assert.ok(text.length <= 120) // floor is 120
})

function fakeCtx() {
  const handlers = new Map()
  return {
    on(name, fn) {
      handlers.set(name, fn)
      return () => {}
    },
    tools: {
      get: () => ({}),
      execute: async () => ({
        isError: false,
        content: [{ type: 'text', text: JSON.stringify(DATA) }],
      }),
    },
    handler: () => handlers.get('agent/pre-step'),
  }
}

test('auto-recall prepends a bounded context to the user message', async () => {
  const ctx = fakeCtx()
  installAutoRecall(ctx, resolveConfig({ autoRecall: true, serverName: 'shibei' }))
  const user = { role: 'user', source: { kind: 'user' }, content: [{ type: 'text', text: '我之前做过哪些 RAG 项目？' }] }
  const payload = { agent: { session: { id: 's1' } }, turn: 1, step: 1, messages: [user], signal: new AbortController().signal }
  const decision = await ctx.handler()(payload, async () => ({ kind: 'enter', messages: [user] }))
  assert.equal(decision.kind, 'enter')
  assert.match(decision.messages[0].content[0].text, /^\[Shibei recall\]/)
  assert.match(decision.messages[0].content[0].text, /RAG 复盘/)
  assert.equal(decision.messages[0].content[1].text, '我之前做过哪些 RAG 项目？')
})

test('auto-recall is off by default', () => {
  const ctx = fakeCtx()
  installAutoRecall(ctx, resolveConfig({}))
  assert.equal(ctx.handler(), undefined)
})
