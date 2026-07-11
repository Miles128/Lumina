# 回复安全过滤词表（待审核）

本目录是 Lumina **面向用户回复** 的固定用词过滤规则源文件。  
`src/secretary/agent/reply_safety_rules.py` 启动时从这里加载；改完需重启后端生效。

| 文件 | 用途 | 命中后行为 |
|------|------|------------|
| [profanity.md](./profanity.md) | 脏话 / 粗口 / 俚语 | 回灌 LLM 重写至干净（不用 `***`） |
| [unprofessional.md](./unprofessional.md) | 不专业自贬 / 抬杠口吻 | 匹配片段 → `我这次判断失误` |
| [meta-reply.md](./meta-reply.md) | 第三人称「审稿腔」泄漏 | 整段替换为道歉重问模板 |
| [forbidden-terms.md](./forbidden-terms.md) | 禁用标签字面替换 | 如 `用户` → `你` |

## 编辑约定

1. 规则写在 fenced code block 里；块信息串以 `regex` 开头。
2. 需要忽略大小写时写：\`\`\`regex ignorecase
3. 空行与 `#` 开头行为注释，不参与匹配。
4. `forbidden-terms.md` 使用 `原文 -> 替换` 行格式（非正则）。
5. 审核时请标出：保留 / 删除 / 收窄（附建议 pattern）。

## 审核状态

- [ ] profanity.md
- [ ] unprofessional.md
- [ ] meta-reply.md
- [ ] forbidden-terms.md
