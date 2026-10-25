import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveConfig } from '../dist/config.js'
import { GROUNDING_RULES, installPrompt } from '../dist/prompt.js'

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

test('prompt registers persona and grounding sections', () => {
  const ctx = fakeCtx()
  installPrompt(ctx, resolveConfig())
  const names = ctx.sections.map((section) => section.name)
  assert.deepEqual(names, ['lumina:persona', 'lumina:grounding', 'lumina:shibei-recall'])
  assert.equal(ctx.sections[1].text, GROUNDING_RULES)
})

test('shibei recall section names the configured MCP tool', () => {
  const ctx = fakeCtx()
  installPrompt(ctx, resolveConfig({ shibei: { recall: true, serverName: 'kb' } }))
  const section = ctx.sections.find((entry) => entry.name === 'lumina:shibei-recall')
  assert.match(section.text, /mcp__kb__shibei_context/)
})

test('shibei recall can be disabled', () => {
  const ctx = fakeCtx()
  installPrompt(ctx, resolveConfig({ shibei: { recall: false, serverName: 'shibei' } }))
  assert.equal(ctx.sections.some((entry) => entry.name === 'lumina:shibei-recall'), false)
})
