# Side-Channel Summary Cache Schema

Location:
- `XDG_CACHE_HOME/cc-dump/summary-cache.json`
- fallback: `~/.cache/cc-dump/summary-cache.json`

`// [LAW:one-source-of-truth] Canonical implementation lives in src/cc_dump/summary_cache.py.`

## Cache Key

Key format:
- `<purpose>:<prompt_version>:<sha256(content)>`

Collision boundaries:
- Different `purpose` => different key
- Different `prompt_version` => different key
- Different normalized content bytes => different SHA-256 hash

## File Shape

```json
{
  "version": 1,
  "entries": {
    "<key>": {
      "purpose": "block_summary",
      "prompt_version": "v1",
      "content_hash": "<sha256>",
      "summary_text": "<cached summary>",
      "created_at": "2026-02-22T00:00:00+00:00"
    }
  }
}
```

## Runtime Behavior

- Read-through: dispatcher checks cache before side-channel call.
- Write-through: successful AI summary writes to cache immediately.
- Eviction: oldest-first when `max_entries` is exceeded.
- Writes are atomic (`tempfile` + `os.replace`).
