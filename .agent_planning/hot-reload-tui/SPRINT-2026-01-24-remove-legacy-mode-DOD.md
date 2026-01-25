# Definition of Done: remove-legacy-mode

## Verification Checklist

1. **Files deleted**: `display.py` and `formatting_ansi.py` no longer exist
2. **No dead imports**: `grep -r "formatting_ansi\|cc_dump.display" src/` returns nothing
3. **No dead references**: `grep -r "no.tui\|no_tui" src/` returns nothing
4. **TUI starts**: `just run` launches the Textual TUI without errors
5. **Lint clean**: `just lint` passes
6. **Help clean**: `cc-dump --help` shows no `--no-tui` option
7. **Proxy still works**: HTTP proxy accepts connections and forwards to target
