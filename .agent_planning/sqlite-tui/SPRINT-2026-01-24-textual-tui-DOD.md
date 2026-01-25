# Definition of Done: textual-tui
Generated: 2026-01-24

## Acceptance Criteria

1. **textual>=0.80.0** in pyproject.toml dependencies
2. **tui/ package** exists with __init__.py, app.py, widgets.py, rendering.py, styles.css
3. **rendering.py** converts all FormattedBlock types to Rich renderables
4. **ConversationView** displays turns, auto-scrolls, supports re-render on filter change
5. **StatsPanel** shows live stats (request count, tokens, model, duration)
6. **Keyboard bindings** work: h, t, a, s, e, m, p, q
7. **Toggling filters** hides/shows relevant content and re-renders
8. **Worker-based event consumption** from QueueSubscriber
9. **TUI is default mode** — running `cc-dump` launches TUI
10. **--no-tui** launches legacy terminal output
11. **Hot-reload** works in TUI mode (formatting changes reflected)
12. **Footer** shows current filter states
13. **Clean exit** via q key or Ctrl+C
14. **Coexists with SQLite**: both subscribers receive events simultaneously

## Verification Method
- Run `cc-dump` (no flags) — TUI launches with empty conversation view
- Make API requests through proxy — conversation appears in TUI
- Press each toggle key — verify content visibility changes
- Press p — stats panel toggles visibility
- Press q — clean exit
- Run `cc-dump --no-tui` — legacy output works as before
- Edit rendering.py while TUI running — hot-reload triggers re-render
