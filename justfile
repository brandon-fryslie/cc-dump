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
    uvx ruff check src/

# Type-check with mypy
check:
    uvx mypy src/cc_dump/

# Format code with ruff
fmt:
    uvx ruff format src/

# Run in browser via textual-serve
web:
    uv run cc-dump-serve

# Pack Textual repo into a single AI-friendly file
textual-repomix:
    repomix --remote https://github.com/Textualize/textual \
        --include "src/textual/**,tests/**,examples/**,docs/guide/**,docs/widgets/**,pyproject.toml,CHANGELOG.md" \
        --ignore "src/textual/demo/**" \
        -o textual-repomix.xml
