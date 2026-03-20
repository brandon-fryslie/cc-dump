# Agent Instructions

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File follow-up work** - Capture any remaining tasks in the team's active tracker.
2. **Run quality gates** (if code changed) - Tests, linters, builds.
3. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
4. **Clean up** - Clear stashes, prune remote branches.
5. **Verify** - All changes committed AND pushed.
6. **Hand off** - Provide context for next session.

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds.
- NEVER stop before pushing - that leaves work stranded locally.
- NEVER say "ready to push when you are" - YOU must push.
- If push fails, resolve and retry until it succeeds.

## PR Description Quality

When opening or updating a PR, descriptions must be concrete and auditable:

1. Summarize behavior changes by subsystem (for example `src/cc_dump/ai`, `src/cc_dump/tui`, `tests/`), not vague "cleanup" language.
2. Explicitly list removed features/endpoints/prompts when code deletes functionality.
3. Include a dedicated `Non-product files` section for local/config/tracker files (for example `.mcp.json`) so reviewers can quickly assess relevance.
4. Include exact validation commands run.

<!-- BEGIN LINKS INTEGRATION -->
## links Agent-Native Workflow

This repository is configured for agent-native issue tracking with `lnks`.

Session bootstrap (every session / after compaction):
1. Run `lnks quickstart --refresh`.
2. Run `lnks workspace`.
3. If remotes are configured, run `lnks sync pull` (uses upstream remote when configured, otherwise the single configured remote; debug override: `LINKS_DEBUG_DOLT_SYNC_BRANCH`).

Work acquisition:
1. Use the issue ID already assigned in context when present.
2. Check current ready work with `lnks ready`.
3. Create or claim an issue only when the work needs tracking. Do not create tickets for trivial drive-by edits like one-line doc fixes that will be resolved immediately.
4. For tracked work, mark it in progress with `lnks update <issue-id> --status in_progress` (or `lnks start ...`).
5. For tracked work, record work start with `lnks comment add <issue-id> --body "Starting: <plan>"`.

Execution:
- Keep structure current with `lnks parent` / `lnks dep` / `lnks label` / `lnks comment`.

Closeout:
1. For tracked work, add completion summary: `lnks comment add <issue-id> --body "Done: <summary>"`.
2. For tracked work, close completed issue: `lnks close <issue-id> --reason "<completion reason>"`.
3. You MUST create a git commit for the completed work: `git add -A && git commit -m "<summary>"`.
4. Work is NOT complete until the commit exists. Do NOT start the next issue before committing.

Traceability:
- `git push` triggers hook-driven `lnks sync push` attempts (warn-only on failure).
- On failure, follow command remediation output; do not invent hidden fallback behavior.

<!-- END LINKS INTEGRATION -->
