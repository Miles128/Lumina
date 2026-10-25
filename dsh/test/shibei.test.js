import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveConfig } from '../dist/config.js'
import { installShibei, shibeiRule } from '../dist/shibei.js'

function fakeCtx() {
  const sections = []
  return {
    sections,
    on() {},
    systemPrompt: {
      section: (section) => {
        sections.push(section)
        return () => {}
      },
      context: () => () => {},
    },
  }
}

test('shibei rule names the configured MCP tool', () => {
  assert.match(shibeiRule('kb'), /mcp__kb__shibei_context/)
  assert.match(shibeiRule('kb'), /mcp__kb__shibei_remember/)
})

test('shibei recall section is registered when enabled', () => {
  const ctx = fakeCtx()
  installShibei(ctx, resolveConfig({ shibei: { recall: true, serverName: 'kb' } }))
  assert.equal(ctx.sections.length, 1)
  assert.equal(ctx.sections[0].name, 'lumina:shibei-recall')
  assert.match(ctx.sections[0].text, /mcp__kb__shibei_context/)
})

test('shibei recall can be disabled', () => {
  const ctx = fakeCtx()
  installShibei(ctx, resolveConfig({ shibei: { recall: false, serverName: 'shibei' } }))
  assert.equal(ctx.sections.length, 0)
})
