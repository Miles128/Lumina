# dsh-lumina-shibei

Shibei recall for DeepSeek Harness.

- prompt rule: personal/background questions call `mcp__<server>__shibei_context` first
- optional auto-recall: inject a bounded Shibei context block before each turn

## Config

```yaml
- id: lumina-shibei
  config:
    serverName: shibei
    recall: true
    autoRecall: false
    topK: 3
    maxChars: 1200
    timeoutMs: 8000
```

`autoRecall` is off by default: it costs one MCP round-trip per turn. When the tool is missing or the call fails, the plugin silently falls through.

## MCP row

The connection itself stays in the profile because command paths and credentials are machine-specific:

```yaml
- insert:
    - id: mcp-shibei
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: shibei
        transport: stdio
        command: /path/to/shibei/.venv/bin/python
        args: [-m, shibei.server]
        env:
          PYTHONPATH: /path/to/shibei/src
          SHIBEI_CONFIG: /path/to/shibei/config.yaml
```

`serverName` must match `lumina-shibei.serverName`.

## Install

```bash
dsh plugin --profile <name> add /absolute/path/to/dsh/packages/shibei
```
