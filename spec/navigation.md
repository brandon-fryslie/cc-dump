# Navigation and Input

## Why Navigation Exists

cc-dump renders Claude Code API traffic as a vertically scrolling conversation view
that can span thousands of lines across dozens of turns. Users need to move through
this content efficiently: scrolling line-by-line to inspect details, jumping to the
top or bottom, paging through large sections, and automatically following new content
as it arrives. The navigation system provides vim-style keyboard controls, a
three-state follow mode, structured jump navigation (special sections, session
boundaries), and search integration. Mouse interactions supplement keyboard navigation
with click-to-cycle visibility, double-click block selection, and hover-to-reveal
behaviors on specific widgets.

## Input Mode System

All keyboard input routes through `on_key` on the app. Textual `BINDINGS` are not
used. The app maintains an `_input_mode` property derived from search state:

| Mode | Derived When | Behavior |
|------|-------------|----------|
| `NORMAL` | `SearchPhase.INACTIVE` | Full keymap active |
| `SEARCH_EDIT` | `SearchPhase.EDITING` | All keys consumed for query editing |
| `SEARCH_NAV` | `SearchPhase.NAVIGATING` | Search nav keys handled first, then navigation subset |

**Source of truth:** `input_modes.py` defines `InputMode` enum and `MODE_KEYMAP` dict.

### Dispatch Flow

1. `_handle_pre_keymap_event()` runs first (in `app.py`):
   - In `SEARCH_EDIT`: `event.prevent_default()` is called, then all keys routed to `_handle_search_editing_key()` (delegates to `_search.handle_search_editing_key()`). Returns `True` (consumed).
   - In `SEARCH_NAV`: search-specific keys (`n`, `N`, `/`, `Escape`, `q`, `Enter`, `Ctrl+N`, `Ctrl+P`, `Tab`, `Shift+Tab`) handled by `_handle_search_nav_special_keys()` (delegates to `_search.handle_search_nav_special_keys()`). If it returns `True`, the event is prevented and consumed. If `False`, falls through.
   - `Escape` closes topmost panel (launch config checked first, then settings) when not in search mode. Returns `True` if a panel was closed.
   - Focused widget key consumers (`check_consume_key`) are checked — panels with focused inputs (e.g., Chip widgets consuming Enter/Space) eat keys via Textual's event bubbling before reaching app.
   - `/` in `NORMAL` mode starts search (handled here, before the keymap, not via `MODE_KEYMAP`). Returns `True`.
2. Keymap lookup runs on the mode's `MODE_KEYMAP` dict. If a match is found, `event.prevent_default()` is called and the action is dispatched via `app.run_action()`.
3. If no keymap match, the event falls through to Textual's default widget bindings (e.g., `ScrollView` handles `Ctrl+F`/`Ctrl+B`/`Ctrl+D`/`Ctrl+U` natively).

## Keyboard Shortcut Reference

### Vim-Style Navigation

Available in `NORMAL` mode via keymap, and in `SEARCH_NAV` mode for both keymap and Textual fallthrough.

| Key | Action | Effect |
|-----|--------|--------|
| `g` | `go_top` | Scroll to top of conversation. Dispatches `FollowEvent.DEACTIVATE` (ACTIVE -> ENGAGED). |
| `G` | `go_bottom` | Scroll to bottom. Dispatches `FollowEvent.SCROLL_BOTTOM` (ENGAGED -> ACTIVE; OFF stays OFF). Always scrolls to end. |
| `j` | `scroll_down_line` | Scroll down one line via `scroll_relative(y=1)` |
| `k` | `scroll_up_line` | Scroll up one line via `scroll_relative(y=-1)` |
| `h` | `scroll_left_col` | Scroll left one column via `scroll_relative(x=-1)` |
| `l` | `scroll_right_col` | Scroll right one column via `scroll_relative(x=1)` |
| `Ctrl+D` | `half_page_down` | Scroll down by `scrollable_content_region.height // 2` |
| `Ctrl+U` | `half_page_up` | Scroll up by `scrollable_content_region.height // 2` |
| `Ctrl+F` | `page_down` | Scroll down one full page via `action_page_down()` |
| `Ctrl+B` | `page_up` | Scroll up one full page via `action_page_up()` |

**Implementation note:** In `NORMAL` mode, `Ctrl+D`/`Ctrl+U`/`Ctrl+F`/`Ctrl+B` are
*not* in the keymap — they fall through to Textual's native `ScrollView` bindings
which provide equivalent behavior. In `SEARCH_NAV` mode, they are explicitly in the
keymap because search handling intercepts events before they can reach Textual's
native bindings, so they must be dispatched manually.

### Visibility Controls

These keys are only active in `NORMAL` mode.

| Key | Action | Description |
|-----|--------|-------------|
| `1` | `toggle_vis('user')` | Toggle user category visibility |
| `2` | `toggle_vis('assistant')` | Toggle assistant category visibility |
| `3` | `toggle_vis('tools')` | Toggle tools category visibility |
| `4` | `toggle_vis('system')` | Toggle system category visibility |
| `5` | `toggle_vis('metadata')` | Toggle metadata category visibility |
| `6` | `toggle_vis('thinking')` | Toggle thinking category visibility |

#### Detail Toggles (Shift+Number or Shift+Letter)

Both shifted number keys and shifted QWERTY letter keys are bound, providing
two paths to the same action for terminal compatibility. Additionally, the
descriptive key names (e.g., `exclamation_mark`, `at`) are bound for terminals
that report key names differently.

| Shifted Number | Descriptive Name | Letter | Action | Description |
|---------------|-----------------|--------|--------|-------------|
| `!` | `exclamation_mark` | `Q` | `toggle_detail('user')` | Force visible, toggle full |
| `@` | `at` | `W` | `toggle_detail('assistant')` | Force visible, toggle full |
| `#` | `number_sign` | `E` | `toggle_detail('tools')` | Force visible, toggle full |
| `$` | `dollar_sign` | `R` | `toggle_detail('system')` | Force visible, toggle full |
| `%` | `percent_sign` | `T` | `toggle_detail('metadata')` | Force visible, toggle full |
| `^` | `circumflex_accent` | `Y` | `toggle_detail('thinking')` | Force visible, toggle full |

#### Analytics Detail Toggles (Lowercase QWERTY)

| Key | Action | Description |
|-----|--------|-------------|
| `q` | `toggle_analytics('user')` | Force visible, toggle expanded |
| `w` | `toggle_analytics('assistant')` | Force visible, toggle expanded |
| `e` | `toggle_analytics('tools')` | Force visible, toggle expanded |
| `r` | `toggle_analytics('system')` | Force visible, toggle expanded |
| `t` | `toggle_analytics('metadata')` | Force visible, toggle expanded |
| `y` | `toggle_analytics('thinking')` | Force visible, toggle expanded |

#### Toggle Behavior

All three toggle types (`toggle_vis`, `toggle_detail`, `toggle_analytics`) share
a single code path (`_toggle_vis_dicts` in `action_handlers.py`) parameterized by
a spec key from `VIS_TOGGLE_SPECS` in `action_config.py`:

- **`toggle_vis`**: toggles `vis:<category>` (on/off)
- **`toggle_detail`**: forces `vis:<category>` to `True`, toggles `full:<category>`
- **`toggle_analytics`**: forces `vis:<category>` to `True`, toggles `exp:<category>`

All three clear per-block overrides for the category and invalidate the active
filterset before applying the toggle.

See `spec/visibility.md` for the full visibility state model (VisState, VIS_CYCLE,
toggle specs).

### Filterset Presets

| Key | Action | Description |
|-----|--------|-------------|
| `=` / `equals_sign` | `next_filterset` | Cycle forward through filterset slots |
| `-` / `minus` | `prev_filterset` | Cycle backward through filterset slots |
| `F1`-`F9` | *(display only)* | NOT implemented — these appear in `KEY_GROUPS` for the keys panel display but have no `MODE_KEYMAP` binding. They do nothing when pressed. |

Filterset slots cycle through: `1, 2, 4, 5, 6, 7, 8, 9` (slot 3 is skipped).
Named presets: Conversation (1), Overview (2), Tools (4), System (5), Cost (6),
Full Debug (7), Assistant (8), Minimal (9).

When a filterset is applied (`apply_filterset` in `action_handlers.py`), it loads
`VisState` values from `settings.get_filterset()`, batch-sets all `vis:`/`full:`/`exp:`
keys, sets `filter:active` to the slot, and shows a notification with the preset name.

### Duplicate Key Bindings for Terminal Compatibility

Some keys have duplicate bindings to handle terminal variation in how key names are
reported. The complete list of duplicated bindings in `MODE_KEYMAP`:

| Primary | Alternate | Action |
|---------|-----------|--------|
| `.` | `full_stop` | `cycle_panel` |
| `,` | `comma` | `cycle_panel_mode` |
| `?` | `question_mark` | `toggle_keys` |
| `=` | `equals_sign` | `next_filterset` |
| `-` | `minus` | `prev_filterset` |
| `[` | `left_square_bracket` | `prev_theme` |
| `]` | `right_square_bracket` | `next_theme` |
| `{` | `left_curly_bracket` | `prev_session` |
| `}` | `right_curly_bracket` | `next_session` |

### Panel Controls

| Key | Action | Description |
|-----|--------|-------------|
| `.` | `cycle_panel` | Cycle active panel through `PANEL_ORDER` (session, stats) |
| `,` | `cycle_panel_mode` | Cycle intra-panel mode (calls `panel.cycle_mode()` on active panel) |
| `f` | `toggle_follow` | Toggle follow mode (see Follow Mode section) |
| `i` | `toggle_info` | Toggle server info panel (store key: `panel:info`) |
| `?` | `toggle_keys` | Toggle keyboard shortcuts panel (store key: `panel:keys`) |
| `Ctrl+L` | `toggle_logs` | Toggle debug logs panel (store key: `panel:logs`) |
| `S` | `toggle_settings` | Toggle settings panel (calls `_open_settings`/`_close_settings`) |
| `C` | `toggle_launch_config` | Toggle launch configuration panel (calls `_open_launch_config`/`_close_launch_config`) |
| `D` | `toggle_debug_settings` | Toggle debug settings panel (store key: `panel:debug_settings`) |

**Panel toggle implementation:** Info, keys, logs, and debug_settings use the
`_toggle_panel` path which flips a boolean in the view store via `PANEL_TOGGLE_CONFIG`.
Settings and launch_config use dedicated open/close methods because they have
additional setup/teardown logic.

### Structured Navigation

| Key | Action | Description |
|-----|--------|-------------|
| `Alt+N` | `next_special` | Jump to next special content section |
| `Alt+P` | `prev_special` | Jump to previous special content section |
| `{` | `prev_session` | Jump to previous session boundary |
| `}` | `next_session` | Jump to next session boundary |

### Theme and Utilities

| Key | Action | Description |
|-----|--------|-------------|
| `[` | `prev_theme` | Cycle to previous theme |
| `]` | `next_theme` | Cycle to next theme |
| `c` | `launch_tool` | Launch active run config in tmux |
| `L` | `open_tmux_log_tail` | Tail cc-dump's log file in a tmux pane |

### Quit

| Key | Action |
|-----|--------|
| `Ctrl+C` | First press: shows "Press Ctrl+C again to quit" notification (1s timeout). Second press within 1 second: exits application. Handled via Textual's built-in `action_quit` mechanism, not via `MODE_KEYMAP`. |

**Implementation:** `action_quit` in `app.py` checks `_quit_requested_at`. If it's
set and within 1.0 seconds of `time.monotonic()`, it calls `self.exit()`. Otherwise
it records the timestamp and shows a notification with `timeout=1`.

### Search Mode Keys

See `spec/search.md` for the complete search specification. Summary of key dispatch:

**SEARCH_EDIT mode** (all keys consumed by `handle_search_editing_key`):

| Key | Action |
|-----|--------|
| Printable characters | Appended to query at cursor position |
| `Backspace` / `Ctrl+H` | Delete character before cursor |
| `Delete` / `Ctrl+D` | Delete character at cursor |
| `Left` / `Right` | Move cursor |
| `Home` / `Ctrl+A` | Cursor to start |
| `End` / `Ctrl+E` | Cursor to end |
| `Alt+B` / `Alt+F` | Move word left/right |
| `Ctrl+W` / `Alt+Backspace` | Delete previous word |
| `Ctrl+U` | Kill to start of line |
| `Ctrl+K` | Kill to end of line |
| `Enter` | Commit search, transition to NAVIGATING |
| `Escape` | Exit search, stay at current position |
| `Alt+C` | Toggle case-insensitive mode (`SearchMode.CASE_INSENSITIVE`) |
| `Alt+W` | Toggle word-boundary mode (`SearchMode.WORD_BOUNDARY`) |
| `Alt+R` | Toggle regex mode (`SearchMode.REGEX`) |
| `Alt+I` | Toggle incremental mode (`SearchMode.INCREMENTAL`) |

**SEARCH_NAV mode** (search keys handled first via `handle_search_nav_special_keys`, then navigation keymap):

| Key | Action |
|-----|--------|
| `n` / `Enter` / `Ctrl+N` / `Tab` | Navigate to next match |
| `N` / `Ctrl+P` / `Shift+Tab` | Navigate to previous match |
| `/` | Re-enter EDITING mode (cursor at end of query) |
| `Escape` | Exit search, stay at current position |
| `q` | Exit search, restore original scroll position |
| `g`, `G`, `j`, `k`, `h`, `l` | Normal vim navigation (via SEARCH_NAV keymap) |
| `Ctrl+F`/`Ctrl+B`/`Ctrl+D`/`Ctrl+U` | Page/half-page navigation (explicitly in SEARCH_NAV keymap because Textual's native bindings may not fire when search handling intercepts events) |

## Follow Mode

Follow mode controls whether the conversation view automatically scrolls to show new
content as it arrives during live proxy or replay sessions.

### State Machine

Three states form the follow mode, modeled in `follow_mode.py`:

```
         ┌──────────────────────────────────────────┐
         │              OFF                          │
         │  (No auto-scroll. Manual control only.)   │
         └─────────┬────────────────────────▲────────┘
                   │ toggle (f)             │ toggle (f)
                   ▼                        │
         ┌──────────────────────────────────┴────────┐
         │            ACTIVE                          │
         │  (Auto-scrolls to end on new content.)     │
         └─────────┬────────────────────────▲────────┘
       user scroll  │                        │ scroll to bottom (G)
       away from    │                        │ or toggle from OFF
       bottom       │                        │
                   ▼                        │
         ┌──────────────────────────────────┴────────┐
         │           ENGAGED                          │
         │  (Wants follow, but user scrolled away.    │
         │   Re-engages when user scrolls to bottom.) │
         └───────────────────────────────────────────┘
```

### Four Event Types

The follow state machine responds to four events, each dispatched via
`_dispatch_follow_event()` on `ConversationView`:

| Event | Dispatched By | Purpose |
|-------|--------------|---------|
| `USER_SCROLL` | `watch_scroll_y()` reactive watcher | User moved the scroll position (mouse wheel, j/k, page keys). Guarded by `_scrolling_programmatically` — programmatic scrolls (via `_programmatic_scroll()` context manager) do not trigger this event. |
| `TOGGLE` | `toggle_follow()` (`f` key) | Explicit follow toggle |
| `SCROLL_BOTTOM` | `scroll_to_bottom()` (`G` key) | Programmatic scroll to end. Does not scroll directly — the transition's `scroll_to_end=True` flag causes `_apply_follow_transition` to call `scroll_end(animate=False)`. |
| `DEACTIVATE` | `scroll_to_top()` (`g` key), `scroll_to_block()` (structured nav), `reveal_search_match()` (search navigation) | Leave ACTIVE without turning OFF |

### Transition Table

All transitions are table-driven (no conditional logic). The transition function
takes `(current_state, event, at_bottom)` and returns `FollowTransition(next_state, scroll_to_end)`.

| Current | Event | at_bottom | Next | scroll_to_end |
|---------|-------|-----------|------|---------------|
| ACTIVE | USER_SCROLL | true | ACTIVE | no |
| ACTIVE | USER_SCROLL | false | ENGAGED | no |
| ENGAGED | USER_SCROLL | true | ACTIVE | no |
| ENGAGED | USER_SCROLL | false | ENGAGED | no |
| OFF | USER_SCROLL | true | OFF | no |
| OFF | USER_SCROLL | false | OFF | no |
| ACTIVE | TOGGLE | * | OFF | no |
| ENGAGED | TOGGLE | * | OFF | no |
| OFF | TOGGLE | * | ACTIVE | yes |
| ACTIVE | SCROLL_BOTTOM | * | ACTIVE | yes |
| ENGAGED | SCROLL_BOTTOM | * | ACTIVE | yes |
| OFF | SCROLL_BOTTOM | * | OFF | yes |
| ACTIVE | DEACTIVATE | * | ENGAGED | no |
| ENGAGED | DEACTIVATE | * | ENGAGED | no |
| OFF | DEACTIVATE | * | OFF | no |

### Key Interactions with Follow Mode

- **`f`** — Dispatches `TOGGLE` event. OFF -> ACTIVE (scrolls to end). ACTIVE/ENGAGED -> OFF.
- **`G` (go_bottom)** — Dispatches `SCROLL_BOTTOM` event. Re-engages follow if ENGAGED. OFF stays OFF. The actual scroll happens indirectly: `_apply_follow_transition` observes the transition's `scroll_to_end=True` and calls `scroll_end(animate=False)` inside `_programmatic_scroll()`.
- **`g` (go_top)** — Dispatches `DEACTIVATE` event first (ACTIVE -> ENGAGED), then scrolls to top via `scroll_home(animate=False)` inside `_programmatic_scroll()`. The programmatic scroll guard prevents `watch_scroll_y` from re-dispatching a `USER_SCROLL` event.
- **User scroll (mouse wheel, j/k, page keys)** — Detected by `watch_scroll_y` reactive watcher. Dispatches `USER_SCROLL` with `at_bottom` computed from `is_vertical_scroll_end`. Also recomputes `_scroll_anchor` for turn-level position tracking. Scrolling away from bottom: ACTIVE -> ENGAGED. Scrolling back to bottom: ENGAGED -> ACTIVE. Programmatic scrolls (inside `_programmatic_scroll()` guard) are excluded.
- **Structured navigation** (special sections, session boundaries) — Dispatches `DEACTIVATE` when using `scroll_to_block()`.

### Reactive Architecture

The follow mode uses SnarfX reactive state:

- `FollowModeStore` holds `state` (Observable), `intent` (Observable), and `transition` (Observable).
- `dispatch()` sets intent; a `reaction` on intent calls `_apply_intent` which computes the transition via `transition_follow_state()` and updates both `state` and `transition`.
- The ConversationView observes `transition` to execute scroll side effects (`scroll_to_end`).
- Follow state is persisted in the view store (`nav:follow` key) and survives hot-reloads. A sync reaction propagates store changes to the FollowModeStore and vice versa.

## Structured Navigation

### Special Section Navigation (`Alt+N` / `Alt+P`)

Jumps between "special" content markers in the conversation (e.g., notable system
prompt changes, specific tool patterns). The marker classification is defined in
`special_content.py`.

- Maintains a per-marker-key cursor (in `_app_state["special_nav_cursor"]` dict) that wraps around.
- Navigation auto-expands the target block (sets block expansion to `True` via `set_block_expansion`).
- Triggers a re-render via `conv.rerender(app.active_filters)` before scrolling to ensure the target block is visible.
- Scrolls to center the target block in the viewport.
- Shows a notification with marker label and position (e.g., `"System Prompt: 3/7"`).
- All jumps route through `go_to_location()` in `location_navigation.py`.

### Session Navigation (`{` / `}`)

Jumps between session boundaries within a merged conversation tab. Session boundaries
are determined by `DomainStore.get_session_boundaries()` on the active tab's domain
store (resolved via `_active_domain_store()`).

- Wraps around: past last boundary goes to first, before first goes to last.
- Determines current position from scroll offset via `_current_turn_index()` (uses `_find_turn_for_line(scroll_y)`).
- Scrolls to the turn at the session boundary via `scroll_to_block(turn_idx, 0)`.
- Does NOT use `go_to_location()` — it calls `scroll_to_block` directly.

### Region Tag Navigation (Internal API)

`next_region_tag` / `prev_region_tag` exist in `action_handlers.py` and have
corresponding `action_*` methods on the app, but are NOT bound to any key in
`MODE_KEYMAP`. They navigate between `ContentRegion.tags` matches across turns
using the same `go_to_location()` path as special navigation. They maintain a
separate cursor map in `_app_state["region_nav_cursor"]`.

These are available programmatically (e.g., via `app.run_action("next_region_tag('sometag')")`)
but have no keyboard binding.

### Location Navigation Contract

All structured jumps that need block expansion route through `go_to_location()` in
`location_navigation.py`, which is the sole turn/block jump executor:

1. Validates location (turn_index and block_index in bounds) via `_turn_for_location()`.
2. Expands the target block via `_expand_location_block()` which calls `ConversationView.set_block_expansion(block_id, True, rerender=False)`.
3. Calls the provided `rerender` callback (if any).
4. Ensures the target turn is rendered via `conv.ensure_turn_rendered()`.
5. Resolves the block's strip position via `resolve_scroll_key()` (uses identity matching against `turn._flat_blocks` when an exact block object is available).
6. Scrolls to center the block via `conv.scroll_to_block()`.

`BlockLocation` is the canonical jump target: `(turn_index, block_index, block_id?, block?)`.

## Mouse Interactions

### Conversation View (ConversationView in `widget_factory.py`)

| Interaction | Behavior |
|-------------|----------|
| Single click | Stores click position (`_last_click_content_y = event.y + scroll_offset.y`) for double-click selection scope |
| Double click | Selects text within the block at the click position. Textual's `Widget._on_click` calls `text_select_all()` on `chain==2`. The override narrows selection to the block under the cursor using the stored click position, computing block boundaries from `block_strip_map`. Falls back to `super().text_select_all()` if position resolution fails. |
| Mouse move | Tracks hover for error indicator expansion/collapse. Hit-tests against indicator bounds via `error_indicator.hit_test_event()`. Toggles `_indicator_state` expanded flag. |

**Note:** Single click does *not* toggle block expansion. The gutter arrows (`▷`/`▽`/`▶`/`▼`)
are visual indicators of expandability and current state, but click-to-expand on gutter
arrows is NOT implemented in the current codebase. The `on_click` handler only stores
the click position (for double-click selection scope). Block expansion is toggled through
the visibility keys, not through click interaction on the conversation view.

### Footer Chips (Custom Footer in `custom_footer.py`)

The footer contains three rows of `Chip` widgets (from `chip.py`):

**Row 1 — Category chips:** One chip per category, each with
`action=f"app.cycle_vis('{name}')"`. Clicking cycles the category through the
5-state `VIS_CYCLE` (hidden -> summary collapsed -> summary expanded -> full
collapsed -> full expanded -> hidden).

**Row 2 — Command chips:**
| Chip | Action |
|------|--------|
| `/ search` | `app.simulate_key('/')` (NOTE: `action_simulate_key` does not exist on app — this chip action is a no-op) |
| `f FOLLOW` | `app.toggle_follow` |
| `c launch` | `app.launch_tool` |

**Row 3 — Log row:**
| Chip | Action |
|------|--------|
| `log:` label | `app.copy_log_path` (copies log path to clipboard) |
| `L tail` | `app.open_tmux_log_tail` |
| Log path | `app.copy_log_path` |

**Chip activation model** (in `chip.py`): `Chip._activate()` is called by both
`on_click` and `on_key` (Enter/Space). It runs the action string via
`self.run_action(self._action)`. Chips also implement `check_consume_key` for
Enter/Space, so focused chips consume those keys before they reach the app keymap.

### Toggle Chips (in `chip.py`)

`ToggleChip` is a subclass-like pattern (separate class in `chip.py`) for boolean
toggles. Click or Enter/Space calls `_toggle()` which flips `self.value` and
notifies via callback.

### Session Panel

| Interaction | Behavior |
|-------------|----------|
| Click on session ID span | Copies session ID to clipboard via `app.copy_to_clipboard()`, shows "Copied session ID" notification. Hit-tests against `_session_id_span` (start, end) x-coordinates. |

### Info Panel

| Interaction | Behavior |
|-------------|----------|
| Click on any row | Copies that row's copy_value to clipboard. Maps click y to row index. Shows "Copied: {value}" notification. |

### Error Indicator

| Interaction | Behavior |
|-------------|----------|
| Mouse hover over indicator | Expands indicator to show details (sets `_indicator_state` expanded to `True`) |
| Mouse leave indicator area | Collapses indicator (sets `_indicator_state` expanded to `False`) |

## Footer Display

The footer displays mode-specific key hints, sourced from `FOOTER_KEYS` in
`input_modes.py`:

- **NORMAL:** `1-6` filters, `qwerty` analytics, `QWERTY` detail, `.` panel, `,` mode, `f` follow, `M-n/p` special, `[]` theme, `i` info, `-=` preset, `?` keys, `/` search, `c` launch, `L` tail
- **SEARCH_EDIT:** `enter` search, `^A/^E` home/end, `^W` del-word, `esc` keep, `q` cancel, `alt+c/w/r/i` modes
- **SEARCH_NAV:** `n/N` next/prev, `^N/^P` next/prev, `tab/S-tab` next/prev, `/` edit, `esc` keep, `q` cancel, `jk` scroll

## Keys Panel

The `?` key toggles a help panel that displays all keyboard shortcuts organized into
groups defined by `KEY_GROUPS` in `input_modes.py`:

- **Nav:** g/G top/bottom, j/k line up/down, h/l column L/R, ^D/^U half page, ^F/^B full page
- **Categories:** 1-6 toggle on/off, Q-Y detail level, q-y analytics detail
- **Panels:** `.` cycle panel, `,` panel mode, `f` follow mode, `^L` debug logs, `i` server info, `?` this panel
- **Search:** `/` search, `=/-` next/prev preset, `M-n/M-p` special sections, `F1-9` load preset
- **Other:** `[/]` cycle theme, `{/}` prev/next session, `c` launch tool (tmux), `C` run configs, `D` debug (listed twice), `L` tail logs (tmux), `S` settings, `^C ^C` quit

**Note on KEY_GROUPS accuracy:** The `KEY_GROUPS` list is display-only data for the
keys panel. It contains a duplicate entry for `D` (debug) and lists `F1-9` (load preset)
which is not actually bound. These are cosmetic issues in the help display, not
functional bugs.
