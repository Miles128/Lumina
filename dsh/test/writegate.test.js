import assert from 'node:assert/strict'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { resolveConfig } from '../dist/config.js'
import { installWriteGate, proposalsRoot } from '../dist/writegate.js'

function fakeCtx() {
  const handlers = new Map()
  return {
    handlers,
    on(name, fn) {
      const list = handlers.get(name) ?? []
      list.push(fn)
      handlers.set(name, list)
      return () => {}
    },
    emit(name, payload) {
      for (const fn of handlers.get(name) ?? []) fn(payload)
    },
  }
}

async function runPre(ctx, name, args, agent) {
  const handler = ctx.handlers.get('tools/pre-execute')[0]
  return handler(
    { name, arguments: args, agent, signal: new AbortController().signal },
    async () => ({ kind: 'allow' }),
  )
}

const WORKSPACE = path.join(os.tmpdir(), 'lumina-wg-ws')

test('children may only write inside proposals/<runId>', async () => {
  const ctx = fakeCtx()
  const cfg = resolveConfig({ workspace: WORKSPACE })
  installWriteGate(ctx, cfg)
  ctx.emit('subagent/start', { id: 'child-1', runId: 'run-42', provider: 'spawn', local: true })
  const child = { id: 'child-1' }

  const denied = await runPre(ctx, 'write', { file_path: `${WORKSPACE}/src/app.ts` }, child)
  assert.equal(denied.kind, 'deny')
  assert.match(denied.reason, /proposals/)

  const allowed = await runPre(
    ctx,
    'write',
    { file_path: path.join(proposalsRoot(cfg, 'run-42'), 'draft.md') },
    child,
  )
  assert.equal(allowed.kind, 'allow')
})

test('child shell is read-only', async () => {
  const ctx = fakeCtx()
  const cfg = resolveConfig({ workspace: WORKSPACE })
  installWriteGate(ctx, cfg)
  ctx.emit('subagent/start', { id: 'child-2', runId: 'run-7', provider: 'spawn', local: true })
  const child = { id: 'child-2' }

  assert.equal((await runPre(ctx, 'bash', { command: 'ls -la' }, child)).kind, 'allow')
  assert.equal((await runPre(ctx, 'bash', { command: 'rm -rf src' }, child)).kind, 'deny')
})

test('root agents are unaffected', async () => {
  const ctx = fakeCtx()
  const cfg = resolveConfig({ workspace: WORKSPACE })
  installWriteGate(ctx, cfg)
  assert.equal((await runPre(ctx, 'write', { file_path: `${WORKSPACE}/src/app.ts` }, { id: 'root' })).kind, 'allow')
})

test('subagent/end releases the jail', async () => {
  const ctx = fakeCtx()
  const cfg = resolveConfig({ workspace: WORKSPACE })
  installWriteGate(ctx, cfg)
  ctx.emit('subagent/start', { id: 'child-3', runId: 'run-9', provider: 'spawn', local: true })
  ctx.emit('subagent/end', { id: 'child-3', runId: 'run-9', provider: 'spawn', local: true, stopReason: 'completed' })
  assert.equal((await runPre(ctx, 'write', { file_path: `${WORKSPACE}/src/app.ts` }, { id: 'child-3' })).kind, 'allow')
})
