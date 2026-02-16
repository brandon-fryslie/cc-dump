# Handoff: Tmux Mouse Coordination

**Created**: 2026-02-14
**Status**: blocked-on-design
**Branch**: `bmf_fix_missing_assistant_header`

---

## Objective

When the user's mouse is over the cc-dump app, disable tmux mouse so Textual handles scrolling. When the mouse leaves the app, re-enable tmux mouse. Currently broken — three failed attempts with different bugs each time.

## The Problem

cc-dump runs inside a tmux pane. When tmux `mouse on` is set, tmux intercepts scroll events before Textual can handle them, so scrolling the ConversationView doesn't work. The fix: toggle `tmux set-option mouse on/off` based on whether the mouse is over cc-dump's terminal area.

## Why It's Hard

**Terminal protocols don't have "mouse left the window" events.** Terminals using SGR mouse tracking simply stop reporting events when the mouse leaves. Textual has no dedicated "mouse entered/left the terminal" event. The only events available are widget-level `Enter`/`Leave`, which fire on every child widget transition.

### What Textual Provides

From research of textual source (v0.96+, libtmux 0.53.0):

1. **`Enter`/`Leave` events** — `bubble=True`, fired when mouse enters/leaves any widget's region. Moving from Header to ConversationView fires `Leave(Header)` then `Enter(ConversationView)`, both bubbling to App.

2. **`app.mouse_over: Widget | None`** — Tracks which widget the mouse is currently over. Set to `None` when mouse is outside all widgets (coordinates out of bounds). Set inside `App._set_mouse_over()` which is called from `Screen._handle_mouse_move()`.

3. **`Screen._handle_mouse_move()`** — Catches `NoWidget` exception (raised when coordinates are out of bounds) and calls `app._set_mouse_over(None, None)`, which sends `Leave` to the last widget and clears `mouse_over`.

4. **`AppFocus`/`AppBlur`** — Terminal focus events, NOT mouse events. Only work in terminals that support FocusIn/FocusOut escape sequences.

5. **No `MouseLeaveScreen` or equivalent.** The gap is at the terminal protocol level, not Textual.

### The Distinguishing Signal

When mouse moves between child widgets:
- `Leave(widget_A)` then `Enter(widget_B)` — both in the same event processing cycle

When mouse leaves the terminal:
- `Leave(last_widget)` then **nothing** — no subsequent `Enter`

These look identical at the moment `Leave` fires. The ONLY way to distinguish them is temporal — did an `Enter` follow or not?

## What's Been Tried

### Attempt 1: Simple on_enter/on_leave on App
```python
def on_enter(self, event):
    tmux.set_mouse(False)
    self.notify("tmux mouse off")

def on_leave(self, event):
    tmux.set_mouse(True)
    self.notify("tmux mouse on")
```
**Failed because:** Enter/Leave bubble from all child widgets. Every widget transition fires Leave→set_mouse(True)→Enter→set_mouse(False), producing dozens of unnecessary tmux subprocess calls per second. Worse: the `notify()` creates toast widgets, which trigger MORE Enter/Leave events → infinite feedback loop.

### Attempt 2: Remove handlers, just set on mount
```python
def on_mount(self):
    tmux.set_mouse(False)  # disable once at startup
# cleanup() restores
```
**Failed because:** Mouse stays permanently off for the entire tmux session, even when mouse is in other panes. User explicitly wants runtime toggling.

### Attempt 3: Timer-based deduplication
```python
def on_enter(self, event):
    if self._mouse_leave_timer:
        self._mouse_leave_timer.stop()
    tmux.set_mouse(False)

def on_leave(self, event):
    self._mouse_leave_timer = self.set_timer(0.05, self._restore_tmux_mouse)
```
**User rejected:** Doesn't want timers.

### Also Fixed (keep this)
`save_mouse_state()` was broken: `session.show_option("mouse")` returns `bool` in libtmux 0.53+, not `str`. Was always defaulting to `"on"`. Now handles `isinstance(val, bool)`.

## Current State of the Code

### `tmux_controller.py` — Mouse methods (KEEP, these work)
- `save_mouse_state()` — captures session mouse value (bool→str conversion fixed)
- `set_mouse(on: bool) -> bool` — idempotent toggle via `_mouse_is_on` guard
- `restore_mouse_state()` — restores saved setting
- `cleanup()` — calls `restore_mouse_state()` then `unzoom()`

### `app.py` — Current state (NEEDS FIXING)
- `on_mount`: calls `save_mouse_state()` + `set_mouse(False)`
- Has timer-based Enter/Leave handlers (user rejected)
- Has `_mouse_leave_timer` field in `__init__`

### `test_tmux_controller.py` — Tests (KEEP, all pass)
- `TestSetMouse` — 5 tests for set_mouse
- `TestSaveMouseState` — 3 tests (but one uses `str` return, should add `bool` case)
- `TestRestoreMouseState` — 3 tests
- `TestCleanup` — includes mouse restore test

## Possible Solutions

### Option A: Use `mouse_over` Property (Most Promising)

Textual's `App._set_mouse_over()` is called from `Screen._handle_mouse_move()`. When the mouse leaves the terminal, `_set_mouse_over(None, None)` is called. This is the internal mechanism that dispatches Enter/Leave.

**Approach:** Override `_set_mouse_over` to detect the `None` transition (mouse left terminal) vs widget-to-widget transition (both args non-None).

```python
# Pseudocode — needs validation against actual Textual source
def _set_mouse_over(self, widget, hover):
    was_in_app = self.mouse_over is not None
    super()._set_mouse_over(widget, hover)
    is_in_app = self.mouse_over is not None

    if not was_in_app and is_in_app:
        # Mouse entered terminal
        tmux.set_mouse(False)
    elif was_in_app and not is_in_app:
        # Mouse left terminal
        tmux.set_mouse(True)
```

**Risk:** `_set_mouse_over` is a private method. Could break on Textual upgrade. But it's the only place that has the complete information.

**Validation needed:** Read the actual signature and behavior of `App._set_mouse_over()` in the installed Textual version.

### Option B: Watch `mouse_over` Reactive (If It's Reactive)

If `app.mouse_over` is a Textual `reactive`, you could watch it:

```python
def watch_mouse_over(self, old, new):
    if old is None and new is not None:
        tmux.set_mouse(False)
    elif old is not None and new is None:
        tmux.set_mouse(True)
```

**Validation needed:** Check if `mouse_over` is reactive or just a plain attribute.

### Option C: Filter Enter/Leave by Checking `mouse_over` After Leave

In `on_leave`, check if `self.mouse_over is None` — if so, the mouse truly left the app (no widget is under it). In `on_enter`, check the transition from `mouse_over is None` to non-None.

```python
def on_enter(self, event):
    # Only act on the first Enter after mouse was outside the app
    # (mouse_over was None, now it's a widget)
    tmux = self._tmux_controller
    if tmux is not None:
        tmux.set_mouse(False)  # idempotent, harmless if already off

def on_leave(self, event):
    # After Leave, if mouse_over is None, mouse left the terminal
    # If mouse_over is still a widget, mouse just moved to another widget
    if self.mouse_over is None:
        tmux = self._tmux_controller
        if tmux is not None:
            tmux.set_mouse(True)
```

**Key question:** At the time `on_leave` fires for widget A (before `on_enter` fires for widget B), is `self.mouse_over` already updated to widget B, or is it still widget A, or is it None? The answer depends on Textual's internal dispatch order. If `_set_mouse_over` updates `mouse_over` BEFORE dispatching Leave, then by the time `on_leave` runs:
- Widget transition: `mouse_over` = new widget (not None) → don't re-enable → CORRECT
- Terminal exit: `mouse_over` = None → re-enable → CORRECT

This is the simplest solution IF the timing works out. **Must verify dispatch order.**

### Option D: Embrace the Timer

A 50ms `set_timer` is imperceptible and correct. The user rejected this, but it might be worth explaining why it's the standard approach for this problem (terminal protocols genuinely don't distinguish these cases). If the user insists no timer, Option A or C are the alternatives.

## Key Files

| File | What's There | What Needs Work |
|------|-------------|-----------------|
| `src/cc_dump/tmux_controller.py:269-309` | Mouse methods (save/set/restore) | Working, keep |
| `src/cc_dump/tui/app.py:109` | `_mouse_leave_timer` field | Remove if no timer |
| `src/cc_dump/tui/app.py:274-279` | `on_mount` save+set_mouse | Keep save, set depends on approach |
| `src/cc_dump/tui/app.py:692-717` | Enter/Leave handlers + timer | Replace with chosen approach |
| `tests/test_tmux_controller.py:580-643` | Mouse method tests | Add bool test for save_mouse_state |

## Next Steps for Agent

1. **Validate Option C** — Check Textual's dispatch order: when `on_leave` fires at the App level, is `self.mouse_over` already updated? Run a test app that logs `self.mouse_over` inside `on_leave`. If it's already `None` for terminal exit and non-None for widget transitions, Option C is the answer.

2. **If Option C doesn't work, validate Option A** — Read the actual `App._set_mouse_over()` method signature and behavior in `.venv/lib/python3.12/site-packages/textual/app.py`. Override it to detect None transitions.

3. **Implement the chosen approach** — Replace the timer-based handlers in `app.py`.

4. **Remove `_mouse_leave_timer` field** if not using timer approach.

5. **Test manually in tmux** — This is one of those things that must be verified by actually running in tmux. Automated tests can only verify the tmux_controller methods, not the Textual event dispatch.
