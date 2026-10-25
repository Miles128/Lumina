import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { resolveConfig } from '../dist/config.js'
import { installGrounding } from '../dist/grounding.js'
import { installTrace } from '../dist/trace.js'

function fakeCtx() {
  const handlers = new Map()
  return {
    on(name, fn) {
      const list = handlers.get(name) ?? []
      list.push(fn)
      handlers.set(name, list)
      return () => {}
    },
    emit(name, ...args) {
      for (const fn of handlers.get(name) ?? []) fn(...args)
    },
    systemPrompt: { section: () => () => {}, context: () => () => {} },
    tools: { register: () => () => {} },
  }
}

const SESSION = { id: 'session-test' }

test('trace projects wrapped session event data', () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'lumina-trace-'))
  const ctx = fakeCtx()
  installTrace(ctx, resolveConfig({ trace: { enabled: true, root, retention: 'full', retainDays: 0 } }))

  ctx.emit('session/event', SESSION, {
    type: 'tool/call', seq: 7, time: 1,
    data: { turn: 1, step: 2, callId: 'c1', name: 'read', arguments: '{"file_path":"a.md"}' },
  })
  ctx.emit('session/event', SESSION, {
    type: 'assistant/message', seq: 9, time: 2,
    data: { turn: 1, step: 2, message: { role: 'assistant', content: [{ type: 'text', text: 'hello' }] } },
  })

  const lines = readFileSync(path.join(root, 'session-test.jsonl'), 'utf8').trim().split('\n').map(JSON.parse)
  assert.equal(lines[0].kind, 'tool/call')
  assert.equal(lines[0].tool_name, 'read')
  assert.equal(lines[1].text, 'hello')
  assert.equal(lines[1].role, 'assistant')
})

test('grounding steers when a content question used no read tool', async () => {
  const ctx = fakeCtx()
  installGrounding(ctx, resolveConfig({ grounding: { enabled: true, maxRetries: 1 } }))
  const steered = []
  const agent = { session: { id: 's1' }, steer: (message) => steered.push(message) }

  ctx.emit('session/event', { id: 's1' }, { type: 'turn/start', data: { turn: 1 } })
  ctx.emit('session/event', { id: 's1' }, {
    type: 'user/message',
    data: { role: 'user', source: { kind: 'user' }, content: [{ type: 'text', text: '读一下 README.md 内容是什么' }] },
  })
  ctx.emit('session/event', { id: 's1' }, {
    type: 'assistant/message',
    data: { turn: 1, step: 1, message: { role: 'assistant', content: [{ type: 'text', text: '这个文件讲的是项目的安装和使用方法，内容比较完整，作者也写了示例。' }] } },
  })

  ctx.emit('agent/turn-stopping', { agent, turn: 1 })
  assert.equal(steered.length, 1)
  assert.match(steered[0].content[0].text, /grounding/)
})

test('grounding stays quiet once a read tool ran', async () => {
  const ctx = fakeCtx()
  installGrounding(ctx, resolveConfig({ grounding: { enabled: true, maxRetries: 1 } }))
  const steered = []
  const agent = { session: { id: 's2' }, steer: (message) => steered.push(message) }

  ctx.emit('session/event', { id: 's2' }, { type: 'turn/start', data: { turn: 1 } })
  ctx.emit('session/event', { id: 's2' }, {
    type: 'user/message',
    data: { role: 'user', source: { kind: 'user' }, content: [{ type: 'text', text: '读一下 README.md 内容是什么' }] },
  })
  ctx.emit('session/event', { id: 's2' }, { type: 'tool/call', data: { turn: 1, step: 1, name: 'read', arguments: '{}' } })
  ctx.emit('session/event', { id: 's2' }, {
    type: 'assistant/message',
    data: { turn: 1, step: 2, message: { role: 'assistant', content: [{ type: 'text', text: 'README 说明了安装步骤和用法。' }] } },
  })

  ctx.emit('agent/turn-stopping', { agent, turn: 1 })
  assert.equal(steered.length, 0)
})
