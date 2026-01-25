# Definition of Done: hot-reload-facade

## Must Pass

1. **No class instances in proxy state** — `ProxyHandler.state` is a plain dict with only str/int/dict values
2. **tracker.py deleted** — no ContentTracker class exists
3. **Single import boundary** — proxy.py contains only `import cc_dump.display`, no `from cc_dump.X`
4. **Hot reload works** — editing formatting.py or colors.py mid-session picks up changes on next request
5. **Tracking works** — system prompts show new/ref/changed correctly across multiple requests
6. **Bounded memory** — state stores at most one content string per position_key, plus a hash→id mapping
7. **No stashed state** — no `sys.modules` tricks, no module-level mutable singletons

## Verification Method

1. Run proxy with `just run`
2. Point claude at it: `ANTHROPIC_BASE_URL=http://127.0.0.1:3344 claude`
3. Send a message (observe REQUEST/RESPONSE formatting)
4. Edit a label in formatting.py (e.g. "REQUEST" → "REQ")
5. Send another message — should show "REQ" without restart
6. Confirm system prompt shows as "ref" (unchanged) on second request
