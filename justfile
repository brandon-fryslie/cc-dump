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

# Check code with ruff
lint:
    uvx ruff check src/

# Format code with ruff
fmt:
    uvx ruff format src/
