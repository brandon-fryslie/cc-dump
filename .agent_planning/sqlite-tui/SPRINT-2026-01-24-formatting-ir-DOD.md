# Definition of Done: formatting-ir
Generated: 2026-01-24

## Acceptance Criteria

1. **formatting_ansi.py exists** with `render_blocks()` and `render_block()` functions
2. **Every FormattedBlock subclass** has a corresponding render case that produces ANSI output
3. **display.py** uses the chain: `format_request()` → blocks → `render_blocks()` → stdout
4. **display.py** uses the chain: `format_response_event()` → blocks → `render_block()` per block → stdout
5. **TextDeltaBlock** renders inline (no trailing newline)
6. **TrackedContentBlock** renders tags with TAG_COLORS and shows content/diff appropriately
7. **Hot-reload** continues to work (add formatting_ansi to reload list in cli.py)
8. **No module-level mutable state** in formatting_ansi.py or display.py
9. **Output is visually identical** to pre-refactor behavior when running the proxy

## Verification Method
- Run `cc-dump` and make API requests through it
- Compare terminal output visually — should be indistinguishable from before
- Verify hot-reload: edit formatting_ansi.py while running, confirm reload message appears
