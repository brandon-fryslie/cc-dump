# Definition of Done: hot-reload-atomicity

## Verification Criteria

1. **Manual test**: Edit `colors.py` or `rendering.py` while TUI is running → hot reload succeeds, pressing toggle keys works
2. **Manual test**: Introduce a syntax error in `widget_factory.py` → hot reload fails gracefully, old widgets remain functional, pressing keys still works
3. **Unit test**: `_replace_all_widgets` with a factory that throws → old widgets remain in DOM
4. **Unit test**: Reactive watchers during swap do not throw NoMatches
5. **Existing tests**: All 30 hot reload tests pass
6. **Existing tests**: Full test suite passes
7. **Lint**: No ruff violations

## Acceptance Criteria Checklist

- [ ] New widgets created before old ones removed
- [ ] Factory failure leaves DOM intact
- [ ] Widget accessors return None on missing widget
- [ ] Reactive watchers suppressed during swap
- [ ] No behavioral regressions in normal operation
