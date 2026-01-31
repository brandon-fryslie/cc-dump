# Sprint: hot-reload-atomicity - Fix Widget Replacement Atomicity

Generated: 2026-01-30
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal

Make hot-reload widget replacement atomic and recoverable — if new widget creation fails, the old widgets remain functional.

## Scope

**Deliverables:**
1. Atomic widget replacement (create-before-remove pattern)
2. Graceful fallback in widget accessors
3. Guard reactive watchers during swap

## Work Items

### P0: Atomic widget replacement (create-before-remove)

**Acceptance Criteria:**
- [ ] New widgets are fully created and state-restored BEFORE any old widgets are removed
- [ ] If new widget creation throws, old widgets remain in DOM and app continues working
- [ ] No duplicate IDs exist in the DOM at any point (assign temp IDs during swap)
- [ ] Test: simulated reload error leaves DOM intact

**Technical Notes:**

The fix restructures `_replace_all_widgets()`:

```python
def _replace_all_widgets(self):
    # 1. Save state from old widgets
    conv_state = self._get_conv().get_state()
    # ... etc for all widgets

    # 2. Create ALL new widgets FIRST (before touching DOM)
    #    Use temporary IDs to avoid collision
    new_conv = cc_dump.tui.widget_factory.create_conversation_view()
    new_conv.id = self._conv_id + "-new"
    new_conv.restore_state(conv_state)
    # ... etc for all widgets

    # 3. Only if ALL creation succeeded, do the swap
    #    Mount new widgets
    header = self.query_one(Header)
    self.mount(new_conv, after=header)
    # ... mount all

    # 4. Remove old widgets
    old_conv.remove()
    # ... remove all

    # 5. Reassign final IDs
    new_conv.id = self._conv_id
    # ... etc
```

Alternative simpler approach: use a `_swapping` flag to suppress reactive watchers, and wrap the whole swap in try/except that re-mounts old widgets on failure.

### P1: Widget accessor fallback

**Acceptance Criteria:**
- [ ] `_get_conv()` and other accessors return `None` instead of throwing when widget missing
- [ ] All callers handle `None` gracefully (skip operation)
- [ ] `_rerender_if_mounted()` is safe when widgets temporarily missing

**Technical Notes:**

Add a helper method:

```python
def _query_widget(self, selector: str):
    """Query a widget, returning None if not found."""
    try:
        return self.query_one(selector)
    except NoMatches:
        return None
```

Update all accessors and callers. This provides defense-in-depth even if the atomic swap is working.

### P2: Guard reactive watchers during swap

**Acceptance Criteria:**
- [ ] Reactive watcher callbacks (`watch_show_headers`, etc.) are no-ops during widget swap
- [ ] The guard is a simple boolean flag, not a complex lock
- [ ] Flag is always cleared (even on exception) via try/finally

**Technical Notes:**

```python
self._replacing_widgets = False

def _replace_all_widgets(self):
    self._replacing_widgets = True
    try:
        # ... swap logic ...
    finally:
        self._replacing_widgets = False

def _rerender_if_mounted(self):
    if self.is_running and not self._replacing_widgets:
        conv = self._get_conv()
        if conv is not None:
            conv.rerender(self.active_filters)
            self._update_footer_state()
```

## Dependencies

- None (self-contained in app.py)

## Risks

- **Textual DOM ID uniqueness**: If Textual enforces unique IDs during mount, we need the temp-ID approach. Verified: Textual does NOT enforce uniqueness on mount, so we can mount new widgets then remove old ones. But using temp IDs is cleaner.
- **Mount ordering**: `mount(after=widget)` requires the reference widget to exist in DOM. After old widgets are removed, we need an alternative anchor (Header).
