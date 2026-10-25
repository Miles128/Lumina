import assert from 'node:assert/strict'
import test from 'node:test'
import { isContentQuestion, isFilesystemQuestion } from '../dist/grounding.js'

test('filesystem questions are recognized', () => {
  for (const text of [
    '看看这个目录下有什么',
    '帮我读一下 README.md',
    '项目结构是怎样的',
    'what files are in this folder',
    'open ./src/main.py',
  ]) {
    assert.equal(isFilesystemQuestion(text), true, text)
  }
})

test('web and chit-chat questions are not filesystem questions', () => {
  for (const text of ['今天天气怎么样', '搜索一下最新的 DeepSeek 新闻', '你好']) {
    assert.equal(isFilesystemQuestion(text), false, text)
  }
})

test('content questions require a real read', () => {
  assert.equal(isContentQuestion('帮我总结 README.md 的内容'), true)
  assert.equal(isContentQuestion('这个文件内容是什么'), true)
  assert.equal(isContentQuestion('列出目录里有哪些文件'), false)
  assert.equal(isContentQuestion('今天有什么新闻'), false)
})

test('write/action requests are not grounding questions', () => {
  assert.equal(isContentQuestion('把 hello 写到 /private/tmp/x.txt'), false)
  assert.equal(isFilesystemQuestion('用 write 工具把内容保存到 out.md'), false)
  assert.equal(isFilesystemQuestion('删除这个目录'), false)
})
