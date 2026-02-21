# Offline Subagent Enrichment

`cc-dump` can correlate HAR runtime sessions with local Claude subagent JSONL logs for historical analysis.

This path is offline-only and optional.

## Run

```bash
uv run python -m cc_dump.subagent_enrichment /path/to/recording.har
```

Optional custom logs root:

```bash
uv run python -m cc_dump.subagent_enrichment /path/to/recording.har \
  --claude-projects-root /path/to/.claude/projects
```

## Output

JSON report with:

- `runtime_sessions`: sessions found in HAR request metadata, with Task tool IDs and correlated subagent artifacts
- `orphan_subagents`: subagent artifacts whose parent session is not present in the HAR input

## Contract

- Runtime/live rendering does not depend on this module.
- Correlation uses in-band HAR request metadata and local JSONL artifacts only.
