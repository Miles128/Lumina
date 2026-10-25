import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveConfig } from '../dist/config.js'
import { installJail } from '../dist/jail.js'
import { installConfirm } from '../dist/confirm.js'

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
    systemPrompt: { section: () => () => {}, context: () => () => {} },
  }
}

async function runPre(ctx, name, args) {
  const handler = ctx.handlers.get('tools/pre-execute')[0]
  return handler({ name, arguments: args, signal: new AbortController().signal }, async () => ({ kind: 'allow' }))
}

const ROOT = process.cwd()

test('config presets: normal asks for everything, yolo for nothing', () => {
  assert.equal(resolveConfig({ permissionMode: 'normal' }).requireConfirm.shell, true)
  assert.equal(resolveConfig({ permissionMode: 'yolo' }).requireConfirm.shell, false)
  assert.equal(resolveConfig({ permissionMode: 'auto' }).requireConfirm.writeNew, false)
  assert.equal(resolveConfig({ permissionMode: 'auto' }).requireConfirm.writeModify, true)
})

test('jail denies writes outside the workspace', async () => {
  const ctx = fakeCtx()
  installJail(ctx, resolveConfig({ workspace: ROOT, fullFsAccess: false }))
  const denied = await runPre(ctx, 'write', { file_path: '/etc/passwd', content: 'x' })
  assert.equal(denied.kind, 'deny')
  const allowed = await runPre(ctx, 'write', { file_path: `${ROOT}/tmp.txt`, content: 'x' })
  assert.equal(allowed.kind, 'allow')
})

test('jail denies shell absolute path escapes', async () => {
  const ctx = fakeCtx()
  installJail(ctx, resolveConfig({ workspace: ROOT, fullFsAccess: false }))
  const denied = await runPre(ctx, 'bash', { command: 'cat /etc/passwd' })
  assert.equal(denied.kind, 'deny')
  const allowed = await runPre(ctx, 'bash', { command: 'ls -la' })
  assert.equal(allowed.kind, 'allow')
})

test('fullFsAccess disables the hard jail', async () => {
  const ctx = fakeCtx()
  installJail(ctx, resolveConfig({ workspace: ROOT, fullFsAccess: true }))
  const result = await runPre(ctx, 'write', { file_path: '/etc/passwd', content: 'x' })
  assert.equal(result.kind, 'allow')
})

test('confirm: in-workspace write and read-only shell never ask', async () => {
  const ctx = fakeCtx()
  installConfirm(ctx, resolveConfig({ workspace: ROOT }))
  assert.equal((await runPre(ctx, 'write', { file_path: `${ROOT}/a.txt` })).kind, 'allow')
  assert.equal((await runPre(ctx, 'bash', { command: 'ls -la' })).kind, 'allow')
  assert.equal((await runPre(ctx, 'read', { file_path: '/etc/hosts' })).kind, 'allow')
})

test('confirm: escaping write and arbitrary shell ask', async () => {
  const ctx = fakeCtx()
  installConfirm(ctx, resolveConfig({ workspace: ROOT, fullFsAccess: true }))
  assert.equal((await runPre(ctx, 'write', { file_path: '/etc/passwd' })).kind, 'ask')
  assert.equal((await runPre(ctx, 'bash', { command: 'npm install left-pad' })).kind, 'ask')
})

test('confirm: workspace python script runs without asking', async () => {
  const ctx = fakeCtx()
  installConfirm(ctx, resolveConfig({ workspace: ROOT }))
  assert.equal((await runPre(ctx, 'bash', { command: 'python3 ./tools/build.py' })).kind, 'allow')
})

test('confirm: yolo disables prompts', async () => {
  const ctx = fakeCtx()
  installConfirm(ctx, resolveConfig({ workspace: ROOT, permissionMode: 'yolo' }))
  assert.equal((await runPre(ctx, 'bash', { command: 'npm install left-pad' })).kind, 'allow')
  assert.equal((await runPre(ctx, 'mcp__srv__delete_file', {})).kind, 'allow')
})

test('confirm: MCP write hints ask, reads do not', async () => {
  const ctx = fakeCtx()
  installConfirm(ctx, resolveConfig({ workspace: ROOT }))
  assert.equal((await runPre(ctx, 'mcp__srv__write_file', {})).kind, 'ask')
  assert.equal((await runPre(ctx, 'mcp__srv__search', {})).kind, 'allow')
})
