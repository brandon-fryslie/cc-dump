# cc-dump development tasks

# Run the proxy with default settings
run *args:
    uv run cc-dump {{args}}

# Install as a uv tool (editable)
install:
    uv tool install -e .

# Uninstall the tool
uninstall:
    uv tool uninstall cc-dump

# Reinstall (useful after structural changes)
reinstall: uninstall install

# Run directly via module
run-module *args:
    uv run python -m cc_dump {{args}}

# Check code with ruff and mypy
lint: check
    uv run ruff check src/

# Type-check with mypy
check:
    uv run mypy src/

# Run tests in parallel
test *args:
    uv run pytest -n auto --dist loadgroup {{args}}

# Run tests sequentially
test-seq *args:
    uv run pytest {{args}}

# Run deterministic smoke checks for d6u follow-up M1-M4
smoke-d6u:
    uv run pytest tests/test_d6u_smoke_checks.py

# Offline HAR + subagent log enrichment report (JSON)
subagent-enrich har projects="~/.claude/projects":
    uv run python -m cc_dump.experiments.subagent_enrichment {{har}} --claude-projects-root {{projects}}

# Format code with ruff
fmt:
    uv run ruff format src/

# Run in browser via textual-serve
web:
    uv run cc-dump-serve

# Pack Textual repo into a single AI-friendly file
textual-repomix:
    repomix --remote https://github.com/Textualize/textual \
        --include "src/textual/**,tests/**,examples/**,docs/guide/**,docs/widgets/**,pyproject.toml,CHANGELOG.md" \
        --ignore "src/textual/demo/**" \
        -o textual-repomix.xml
