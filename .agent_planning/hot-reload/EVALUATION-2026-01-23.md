# Evaluation: Hot-Reload with Minimal Proxy State

## Current State

The proxy (`proxy.py`) currently:
1. Imports `cc_dump.display` (partially written facade, now deleted) and `ContentTracker`
2. Has `_check_reload()` that reloads all modules on file change
3. Owns a `ContentTracker` instance as a class attribute
4. Owns a `request_counter` as a class attribute

The `ContentTracker` is the problem:
- **Memory leak**: `self.seen` stores full content strings forever (hash → {id, content, color_idx})
- **Complex logic on proxy side**: The tracker class has methods, internal state, color cycling
- **Reload-hostile**: Instance methods bind to the old class after reload

## What Needs to Change

### Core Insight
The proxy should hold only **plain data** (dicts, ints) — no class instances with methods. All logic (hashing, diffing, formatting, color assignment) belongs on the reloadable side.

### The Memory Problem
`ContentTracker.seen` stores every unique content string ever seen. In a long session with many system prompt variations, this grows unbounded. The only reason content is stored is to produce diffs on "changed" detection.

Bounded alternative: store only the **previous** content per position (not every version ever seen). This caps memory at O(positions) rather than O(unique_contents).

### State the Proxy Actually Needs
To support "new/ref/changed" detection with diffs, the minimal state is:
- `positions: dict[str, dict]` — position_key → {hash, content, id, color_idx}
  - Only stores the CURRENT content at each position (bounded by number of positions)
- `known_hashes: dict[str, str]` — hash → id (for "ref" detection without re-storing content)
- `next_id: int` — counter for tag IDs
- `next_color: int` — counter for color cycling
- `request_counter: int`

This is all plain data. No methods, no class instance.

## Architecture

```
proxy.py (stable, not reloaded)
  ├── owns: plain dict/int state
  ├── owns: _check_reload()
  ├── calls: cc_dump.display.* (fully-qualified, through module reference)
  │
  └── passes state dict to display functions

display.py (facade, reloaded)
  ├── imports: colors, formatting
  ├── render_request(body, state) → str
  ├── render_response_header() → str
  ├── render_response_event(event_type, data) → str
  ├── render_error(code, reason) → str
  ├── render_proxy_error(err) → str
  └── render_log(command, path, status) → str

formatting.py (reloaded)
  ├── format_request(body, state) → str  (uses state dict directly)
  ├── format_response_event(...) → str
  └── helpers...

tracker.py → DELETED (logic absorbed into formatting.py)

colors.py (reloaded, unchanged)
```

### Key Design Decisions
1. **No ContentTracker class** — the "tracking" logic (hash, compare, assign ID/color) moves into `formatting.py` as pure functions operating on the state dict
2. **State dict is plain data** — proxy owns it, passes it through display facade
3. **Bounded memory** — only one content string per position (for diffs), plus a set of known hashes (8-byte strings, no content)
4. **display.py is the single reload boundary** — proxy calls `cc_dump.display.X()`, reload replaces the module, next call uses new code

## Verdict: CONTINUE
No blockers. Clear approach.
