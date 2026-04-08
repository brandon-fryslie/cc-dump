# Running cc-dump in the Browser

cc-dump can be run in your web browser using [textual-serve](https://github.com/Textualize/textual-serve).

## Quick Start

```bash
# Run cc-dump in the browser
just web
# or:
cc-dump-serve
```

This will:
1. Start the textual-serve server (default: http://localhost:8000)
2. Display the cc-dump TUI in your browser

## Requirements

The `textual-serve` package is a production dependency, installed automatically with cc-dump.

## Notes

- The web interface provides the same full TUI experience as the terminal
- All keyboard shortcuts work the same way
- Each browser tab runs an independent cc-dump instance
