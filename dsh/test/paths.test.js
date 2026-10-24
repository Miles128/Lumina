import assert from 'node:assert/strict'
import test from 'node:test'
import { isInside, isReadOnlyShell, shellEscapesJail, workspaceRoot } from '../dist/paths.js'

test('isInside accepts the root and descendants only', () => {
  assert.equal(isInside('/tmp/ws', '/tmp/ws'), true)
  assert.equal(isInside('/tmp/ws', '/tmp/ws/a/b.txt'), true)
  assert.equal(isInside('/tmp/ws', '/tmp/ws-other/b.txt'), false)
  assert.equal(isInside('/tmp/ws', '/etc/passwd'), false)
})

test('workspaceRoot defaults to cwd', () => {
  assert.equal(workspaceRoot(), process.cwd())
  assert.equal(workspaceRoot('~/x'), `${process.env.HOME}/x`)
})

test('shellEscapesJail allows relative paths and safe binaries', () => {
  assert.equal(shellEscapesJail('ls -la .', '/tmp/ws'), null)
  assert.equal(shellEscapesJail('cat README.md', '/tmp/ws'), null)
  assert.equal(shellEscapesJail('/usr/bin/python3 script.py', '/tmp/ws'), null)
  assert.equal(shellEscapesJail('cat > /dev/null', '/tmp/ws'), null)
})

test('shellEscapesJail blocks absolute paths outside the workspace', () => {
  assert.match(shellEscapesJail('cat /etc/passwd', '/tmp/ws') ?? '', /outside the workspace/)
  assert.match(shellEscapesJail('cp secrets.txt ~/Desktop/x', '/tmp/ws') ?? '', /outside the workspace/)
})

test('isReadOnlyShell is conservative', () => {
  assert.equal(isReadOnlyShell('ls -la'), true)
  assert.equal(isReadOnlyShell('cat a.txt | grep x'), true)
  assert.equal(isReadOnlyShell('rm -rf build'), false)
  assert.equal(isReadOnlyShell('ls && rm x'), false)
  assert.equal(isReadOnlyShell('echo hi > out.txt'), false)
  assert.equal(isReadOnlyShell('echo hi > /dev/null'), true)
})
