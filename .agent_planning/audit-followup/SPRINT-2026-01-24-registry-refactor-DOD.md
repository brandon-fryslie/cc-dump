# Definition of Done: registry-refactor

## Verification Checklist

### Structure
1. [ ] `BLOCK_RENDERERS` dict exists at module level in tui/rendering.py
2. [ ] Dict maps all 19 FormattedBlock subclasses to render functions
3. [ ] Each render function follows naming convention: `_render_<block_type>`
4. [ ] Each render function has type signature: `(block, filters) -> Text | None`

### Main Function
5. [ ] `render_block()` is <10 lines
6. [ ] Uses registry lookup: `BLOCK_RENDERERS.get(type(block))`
7. [ ] Returns None for unknown block types (graceful degradation)
8. [ ] No isinstance() chains remain in render_block()

### Behavior Preservation
9. [ ] All existing hot-reload tests pass: `uv run pytest tests/test_hot_reload.py -v`
10. [ ] TUI displays correctly: manual verification with `just run`
11. [ ] Filter behavior unchanged (headers, tools, system, expand, metadata)

### New Tests
12. [ ] `tests/test_rendering.py` exists
13. [ ] Tests for registry lookup (known type, unknown type)
14. [ ] Tests for at least 5 different block type renderers
15. [ ] Tests for filter application

## Pass Criteria

```bash
# All tests pass
uv run pytest tests/ -v

# Lint passes
just lint

# Complexity check (optional if available)
# render_block() cyclomatic complexity should be ~1-3
```

## Verification Commands

```bash
# Quick check that refactor didn't break anything
uv run pytest tests/test_hot_reload.py -v

# Run new rendering tests
uv run pytest tests/test_rendering.py -v

# Manual TUI check
just run
# Verify: headers toggle (h), tools toggle (t), system toggle (s), etc.
```
