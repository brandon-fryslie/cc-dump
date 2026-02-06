# Implementation Context: Sprint 1 - Rename Package

## Files to Modify (complete list)

### Package rename
- `src/cc_dump/` → `src/surview/` (git mv)

### pyproject.toml changes
- name: "surview"
- description: "HTTP debugging proxy with TUI"
- keywords: ["http", "proxy", "debugging", "tui", "har"]
- scripts: `surview = "surview.cli:main"`
- packages: `["src/surview"]`
- Remove `"tiktoken>=0.5.0"` from dependencies
- URLs: update if desired (can leave as-is for now)

### Python files needing import updates
Every .py file in src/surview/ and tests/ that contains "cc_dump":
- All 26 source files in src/surview/
- All 22 test files in tests/
- Approach: `find src/ tests/ -name "*.py" -exec sed -i '' 's/cc_dump/surview/g' {} +`
- Then fix: `s/cc-dump/surview/g` for string literals

### String literal updates
- hot_reload.py: _RELOAD_ORDER and _RELOAD_IF_CHANGED lists
- har_recorder.py line 218: `"name": "cc-dump"` → `"name": "surview"`
- sessions.py: `~/.local/share/cc-dump/` → `~/.local/share/surview/`
- cli.py line 22: `~/.local/share/cc-dump/sessions.db` → `~/.local/share/surview/sessions.db`
- cli.py lines 45, 65: print messages
- tui/app.py lines 113-121, 653: log messages

### Class name updates
- tui/app.py: `CcDumpApp` → `SurviewApp`
- cli.py line 128: `from cc_dump.tui.app import CcDumpApp` → `from surview.tui.app import SurviewApp`

### justfile
- `uv run cc-dump` → `uv run surview`
- `uv tool uninstall cc-dump` → `uv tool uninstall surview`
- `python -m cc_dump` → `python -m surview`
- Comment: "cc-dump development tasks" → "surview development tasks"

### Documentation
- CLAUDE.md: all references
- ARCHITECTURE.md: all references (if exists)
- PROJECT_SPEC.md: all references (if exists)
