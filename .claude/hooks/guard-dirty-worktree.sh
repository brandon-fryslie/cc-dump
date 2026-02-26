#!/bin/bash
# PreToolUse hook: block destructive git commands when working tree is dirty.
#
# When there are uncommitted changes, only allow safe git commands.
# This prevents Claude from destroying in-progress work with stash, checkout, etc.

set -e

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command')

# Not a git command — allow
if ! echo "$COMMAND" | grep -qE '\bgit\b'; then
  exit 0
fi

# Dangerous git subcommands that can destroy uncommitted work
DANGEROUS="stash checkout restore reset clean rebase"

# Extract just the git commands, not heredoc/string content.
# Split on && ; || and newlines, keep only lines starting with git (after trimming).
GIT_LINES=$(echo "$COMMAND" | tr '&;|' '\n' | grep -E '^\s*git\s' || true)

if [ -z "$GIT_LINES" ]; then
  exit 0
fi

for word in $DANGEROUS; do
  if echo "$GIT_LINES" | grep -qE "\bgit\b.*\b${word}\b"; then
    # Allow rebase --continue and --abort (needed during conflict resolution)
    if [ "$word" = "rebase" ] && echo "$GIT_LINES" | grep -qE "\bgit\b.*\brebase\b.*(--continue|--abort|--skip)"; then
      continue
    fi
    # Check for dirty worktree
    CWD=$(echo "$INPUT" | jq -r '.cwd')
    if cd "$CWD" 2>/dev/null && git status --porcelain 2>/dev/null | grep -q .; then
      echo "BLOCKED: 'git $word' is not allowed when there are uncommitted changes. Only git add/commit and read-only commands (status/diff/log/show/branch) are permitted. This hook exists because git stash destroyed in-progress work." >&2
      exit 2
    fi
  fi
done

exit 0
