# Running cc-dump in the Browser

cc-dump can be run in your web browser using [textual-web](https://github.com/Textualize/textual-web).

## Quick Start

```bash
# Run cc-dump in the browser
just web
```

This will:
1. Start the textual-web server (default: http://localhost:8000)
2. Open your browser automatically
3. Display the cc-dump TUI in your browser

## Configuration

The `textual-web.toml` file configures the web deployment:

```toml
[account]
# api_key = "your-key-here"  # Optional: for textual.textualize.io hosting

[app.cc-dump]
command = "uv run cc-dump"
path = "."
color = "cyan"
```

## Manual Launch

If you prefer to launch manually:

```bash
# Start the server
uv run textual-web --config textual-web.toml --environment local

# Then open http://localhost:8000 in your browser
```

## Requirements

The `textual-web` package is included in the dev dependencies. Install with:

```bash
uv sync --group dev
```

## Notes

- The web interface provides the same full TUI experience as the terminal
- All keyboard shortcuts work the same way
- Multiple users can connect to the same session
- textual-web is currently in active development
