# Side-Channel Redaction And Minimization Policy

Version: `redaction-v1`

Purpose:
- Define a single, testable boundary for what side-channel requests can send.
- Reduce sensitive-data leakage risk and control token volume.

`// [LAW:one-source-of-truth] Canonical runtime policy is implemented in src/cc_dump/side_channel_boundary.py.`
`// [LAW:single-enforcer] Enforcement happens only in SideChannelManager.run() before subprocess dispatch.`

## Contract

Every side-channel request MUST:
- pass through boundary processing exactly once
- include `policy_version` metadata in side-channel marker payload
- redact known sensitive patterns
- apply a purpose-specific max prompt size cap

## Purpose Policy Matrix

| Purpose | Max Prompt Chars | Notes |
|---|---:|---|
| `core_debug_lane` | 12,000 | Fast debug lane with tighter bound |
| `block_summary` | 16,000 | Summary context cap |
| `decision_ledger` | 24,000 | Default cap |
| `action_extraction` | 24,000 | Default cap |
| `handoff_note` | 24,000 | Default cap |
| `release_notes` | 24,000 | Default cap |
| `incident_timeline` | 24,000 | Default cap |
| `conversation_qa` | 24,000 | Higher context utility |
| `checkpoint_summary` | 24,000 | Default cap |
| `compaction` | 40,000 | Highest cap by design |
| `utility_custom` | 12,000 | Conservative fallback cap |

## Redaction Rules

`redaction-v1` rules replace:
- bearer authorization tokens
- `x-api-key` header values
- Anthropic/OpenAI style key strings (`sk-ant-*`, `sk-*`)
- AWS access keys (`AKIA...`)
- assignment-style password fields (`password=...`, `pwd: ...`)
- PEM private key blocks

## Diagnostics

`policy_version` appears in:
- marker payload (request body prefix)
- HAR side-channel metadata (`entry._cc_dump.policy_version`)
- analytics side-channel purpose summary (`policy_versions` rollup)
