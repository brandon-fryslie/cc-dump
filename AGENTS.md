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

This repository is configured for agent-native issue tracking with `lit`.

Run `lit quickstart` to get instructions.

<!-- END LINKS INTEGRATION -->
