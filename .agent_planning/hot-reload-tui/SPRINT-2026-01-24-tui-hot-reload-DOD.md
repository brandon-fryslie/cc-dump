# Definition of Done: tui-hot-reload

## Verification Checklist

1. **Formatting reload**: Edit `formatting.py` while app is running → next request uses new formatting
2. **Rendering reload**: Edit `tui/rendering.py` while app is running → toggle a filter to see new rendering
3. **Analysis reload**: Edit `analysis.py` while app is running → next budget/economics display uses new logic
4. **Colors reload**: Edit `colors.py` → next render uses new colors
5. **No crash on bad reload**: Introduce a syntax error in `formatting.py` → app logs error, continues with old code
6. **Visual feedback**: When reload occurs, user sees indication (footer flash, log, etc.)
7. **Proxy unaffected**: `proxy.py` is never reloaded regardless of changes
8. **No stale refs**: After reload, new function code is actually called (verify with a print/log in the new code)
