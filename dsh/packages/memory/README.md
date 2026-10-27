# dsh-lumina-memory

Durable `MEMORY.md` memory for DeepSeek Harness.

- injects `MEMORY.md` into the system prompt (capped)
- `memory` tool: add / replace / remove
- `search_memory` tool: MEMORY.md + local notes

## Config

```yaml
- id: lumina-memory
  config:
    enabled: true
    root: ~/.lumina/memories
    inject: true
    maxChars: 4000
```

## Install

```bash
dsh plugin --profile <name> add /absolute/path/to/dsh/packages/memory
```

The runtime (loop, sessions, persona, traces) belongs to dsh; this plugin only owns the memory store and tools.
