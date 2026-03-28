# Navigation and Input

> Status: draft
> Last verified against: not yet

## Why Navigation Exists

cc-dump renders Claude Code API traffic as a vertically scrolling conversation view
that can span thousands of lines across dozens of turns. Users need to move through
this content efficiently: scrolling line-by-line to inspect details, jumping to the
top or bottom, paging through large sections, and automatically following new content
as it arrives. The navigation system provides vim-style keyboard controls, a
three-state follow mode, structured jump navigation (special sections, session
boundaries, region tags), and search integration. Mouse interactions supplement
keyboard navigation with click-to-copy, double-click-to-select, and hover-to-reveal
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

1. `_handle_pre_keymap_event()` runs first:
   - In `SEARCH_EDIT`: all keys consumed, routed to `search_controller.handle_search_editing_key()`.
   - In `SEARCH_NAV`: search-specific keys (`n`, `N`, `/`, `Esc`, `q`, `Enter`, `Ctrl+N`, `Ctrl+P`, `Tab`, `Shift+Tab`) handled by `search_controller.handle_search_nav_special_keys()`. If not consumed, falls through.
   - `Escape` closes topmost panel (launch config, then settings) when not in search.
   - Focused widget key consumers (`check_consume_key`) are checked — panels with focused inputs eat keys via Textual's event bubbling before reaching app.
   - `/` in `NORMAL` mode starts search (handled here, before the keymap, not via `MODE_KEYMAP`).
2. Keymap lookup runs on the mode's `MODE_KEYMAP` dict. If a match is found, `event.prevent_default()` is called and the action is dispatched via `app.run_action()`.
3. If no keymap match, the event falls through to Textual's default widget bindings (e.g., `ScrollView` handles `Ctrl+F`/`Ctrl+B`/`Ctrl+D`/`Ctrl+U` natively).

## Keyboard Shortcut Reference

### Vim-Style Navigation

Available in `NORMAL` mode via keymap, and in `SEARCH_NAV` mode for both keymap and Textual fallthrough.

| Key | Action | Effect |
|-----|--------|--------|
| `g` | `go_top` | Scroll to top of conversation. Deactivates follow mode (ACTIVE -> ENGAGED). |
| `G` | `go_bottom` | Scroll to bottom. Transitions ENGAGED -> ACTIVE; OFF stays OFF. |
| `j` | `scroll_down_line` | Scroll down one line |
| `k` | `scroll_up_line` | Scroll up one line |
| `h` | `scroll_left_col` | Scroll left one column (for horizontally overflowing content) |
| `l` | `scroll_right_col` | Scroll right one column |
| `Ctrl+D` | `half_page_down` | Scroll down by half the viewport height (Textual native fallthrough) |
| `Ctrl+U` | `half_page_up` | Scroll up by half the viewport height (Textual native fallthrough) |
| `Ctrl+F` | `page_down` | Scroll down one full page (Textual native fallthrough) |
| `Ctrl+B` | `page_up` | Scroll up one full page (Textual native fallthrough) |

**Implementation note:** In `NORMAL` mode, `Ctrl+D`/`Ctrl+U`/`Ctrl+F`/`Ctrl+B` are
*not* in the keymap — they fall through to Textual's native `ScrollView` bindings
which provide equivalent behavior. In `SEARCH_NAV` mode, they are explicitly in the
keymap because search handling intercepts events before they can reach Textual's
native bindings, so they must be dispatched manually.
The scroll amount for half-page is `scrollable_content_region.height // 2`.

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
two paths to the same action for terminal compatibility.

| Shifted Number | Letter | Action | Description |
|---------------|--------|--------|-------------|
| `!` (Shift+1) | `Q` | `toggle_detail('user')` | Force visible, toggle full |
| `@` (Shift+2) | `W` | `toggle_detail('assistant')` | Force visible, toggle full |
| `#` (Shift+3) | `E` | `toggle_detail('tools')` | Force visible, toggle full |
| `$` (Shift+4) | `R` | `toggle_detail('system')` | Force visible, toggle full |
| `%` (Shift+5) | `T` | `toggle_detail('metadata')` | Force visible, toggle full |
| `^` (Shift+6) | `Y` | `toggle_detail('thinking')` | Force visible, toggle full |

#### Analytics Toggles (Lowercase QWERTY)

| Key | Action | Description |
|-----|--------|-------------|
| `q` | `toggle_analytics('user')` | Force visible, toggle expanded |
| `w` | `toggle_analytics('assistant')` | Force visible, toggle expanded |
| `e` | `toggle_analytics('tools')` | Force visible, toggle expanded |
| `r` | `toggle_analytics('system')` | Force visible, toggle expanded |
| `t` | `toggle_analytics('metadata')` | Force visible, toggle expanded |
| `y` | `toggle_analytics('thinking')` | Force visible, toggle expanded |

See `spec/visibility.md` for the full visibility state model (VisState, VIS_CYCLE,
toggle specs).

### Filterset Presets

| Key | Action | Description |
|-----|--------|-------------|
| `=` | `next_filterset` | Cycle forward through filterset slots |
| `-` | `prev_filterset` | Cycle backward through filterset slots |
| `F1`-`F9` | *(display only)* | NOT implemented — these appear in `KEY_GROUPS` for the keys panel display but have no `MODE_KEYMAP` binding. They do nothing when pressed. |

Filterset slots cycle through: `1, 2, 4, 5, 6, 7, 8, 9` (slot 3 is skipped).
Named presets: Conversation (1), Overview (2), Tools (4), System (5), Cost (6),
Full Debug (7), Assistant (8), Minimal (9).

### Duplicate Key Bindings for Terminal Compatibility

Some keys have duplicate bindings to handle terminal variation in how key names are
reported. For example, both `"."` and `"full_stop"` map to `cycle_panel`, and both
`","` and `"comma"` map to `cycle_panel_mode`. This ensures the binding works across
different terminal emulators.

### Panel Controls

| Key | Action | Description |
|-----|--------|-------------|
| `.` | `cycle_panel` | Cycle active panel through `PANEL_ORDER` |
| `,` | `cycle_panel_mode` | Cycle intra-panel mode (e.g., aggregate vs per-model) |
| `f` | `toggle_follow` | Toggle follow mode (see Follow Mode section) |
| `i` | `toggle_info` | Toggle server info panel |
| `?` | `toggle_keys` | Toggle keyboard shortcuts panel |
| `Ctrl+L` | `toggle_logs` | Toggle debug logs panel |
| `S` | `toggle_settings` | Toggle settings panel |
| `C` | `toggle_launch_config` | Toggle launch configuration panel |
| `D` | `toggle_debug_settings` | Toggle debug settings panel |

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

### Search Mode Keys

See `spec/search.md` for the complete search specification. Summary of key dispatch:

**SEARCH_EDIT mode** (all keys consumed):

| Key | Action |
|-----|--------|
| Printable characters | Appended to query at cursor |
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
| `Alt+C` | Toggle case-insensitive mode |
| `Alt+W` | Toggle word-boundary mode |
| `Alt+R` | Toggle regex mode |
| `Alt+I` | Toggle incremental mode |

**SEARCH_NAV mode** (search keys handled first, then navigation keymap):

| Key | Action |
|-----|--------|
| `n` / `Enter` / `Ctrl+N` / `Tab` | Navigate to next match |
| `N` / `Ctrl+P` / `Shift+Tab` | Navigate to previous match |
| `/` | Re-enter EDITING mode (cursor at end of query) |
| `Escape` | Exit search, stay at current position |
| `q` | Exit search, restore original scroll position |
| `g`, `G`, `j`, `k`, `h`, `l` | Normal vim navigation (via keymap) |
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

### Transition Table

All transitions are table-driven (no conditional logic). The transition function
takes `(current_state, event, at_bottom)` and returns `(next_state, scroll_to_end)`.

| Current | Event | at_bottom | Next | scroll_to_end |
|---------|-------|-----------|------|---------------|
| ACTIVE | USER_SCROLL | true | ACTIVE | no |
| ACTIVE | USER_SCROLL | false | ENGAGED | no |
| ENGAGED | USER_SCROLL | true | ACTIVE | no |
| ENGAGED | USER_SCROLL | false | ENGAGED | no |
| OFF | USER_SCROLL | * | OFF | no |
| * | TOGGLE | * | see below | see below |
| ACTIVE | TOGGLE | * | OFF | no |
| ENGAGED | TOGGLE | * | OFF | no |
| OFF | TOGGLE | * | ACTIVE | yes |
| OFF | SCROLL_BOTTOM | * | OFF | yes |
| ENGAGED | SCROLL_BOTTOM | * | ACTIVE | yes |
| ACTIVE | SCROLL_BOTTOM | * | ACTIVE | yes |
| ACTIVE | DEACTIVATE | * | ENGAGED | no |
| ENGAGED | DEACTIVATE | * | ENGAGED | no |
| OFF | DEACTIVATE | * | OFF | no |

### Key Interactions with Follow Mode

- **`f`** — Dispatches `TOGGLE` event. OFF -> ACTIVE (scrolls to end). ACTIVE/ENGAGED -> OFF.
- **`G` (go_bottom)** — Dispatches `SCROLL_BOTTOM` event. Re-engages follow if ENGAGED. Always scrolls to end.
- **`g` (go_top)** — Dispatches `DEACTIVATE` event. ACTIVE -> ENGAGED. Then scrolls to top.
- **User scroll (mouse wheel, j/k, page keys)** — Dispatches `USER_SCROLL` with `at_bottom` computed from `is_vertical_scroll_end`. Scrolling away from bottom: ACTIVE -> ENGAGED. Scrolling back to bottom: ENGAGED -> ACTIVE.

### Persistence

Follow state is persisted in the view store (`nav:follow` key) and survives
hot-reloads. The `FollowModeStore` uses SnarfX `Observable` + `reaction` for
reactive state management.

## Structured Navigation

### Special Section Navigation (`Alt+N` / `Alt+P`)

Jumps between "special" content markers in the conversation (e.g., notable system
prompt changes, specific tool patterns). The marker classification is defined in
`special_content.py`.

- Maintains a per-marker-key cursor that wraps around.
- Navigation auto-expands the target block (sets block expansion to true).
- Triggers a re-render before scrolling to ensure the target block is visible.
- Scrolls to center the target block in the viewport.
- Shows a notification with marker label and position (e.g., `"System Prompt: 3/7"`).

### Session Navigation (`{` / `}`)

Jumps between session boundaries within a merged conversation tab. Session boundaries
are determined by `DomainStore.get_session_boundaries()`.

- Wraps around: past last boundary goes to first, before first goes to last.
- Determines current position from scroll offset via `_current_turn_index()`.
- Scrolls to the turn at the session boundary.

### Location Navigation Contract

All structured jumps route through `go_to_location()` in `location_navigation.py`,
which is the sole turn/block jump executor:

1. Validates location (turn_index and block_index in bounds).
2. Expands the target block via `ConversationView.set_block_expansion()`.
3. Calls the provided `rerender` callback (if any).
4. Ensures the target turn is rendered.
5. Resolves the block's strip position via `resolve_scroll_key()`.
6. Scrolls to center the block.

`BlockLocation` is the canonical jump target: `(turn_index, block_index, block_id?, block?)`.

## Mouse Interactions

### Conversation View (ConversationView)

| Interaction | Behavior |
|-------------|----------|
| Single click | Stores click position (content y coordinate) for double-click selection scope |
| Double click | Selects text within the block at the click position (overrides Textual's default select-all). Uses `text_select_all()` override to scope selection to block boundaries. |
| Mouse move | Tracks hover for error indicator expansion/collapse (hit-tests against indicator bounds) |

**Note:** Single click does *not* toggle block expansion. The gutter arrows (`▷`/`▽`/`▶`/`▼`)
are visual indicators of expandability and current state, but click-to-expand on gutter
arrows is NOT implemented in the current codebase. The `on_click` handler only stores
the click position (for double-click selection scope). Block expansion is toggled through
the visibility keys, not through click interaction on the conversation view.

### Filter Chips (Custom Footer)

| Interaction | Behavior |
|-------------|----------|
| Click | Cycles category through 5 visibility states (VIS_CYCLE) |
| Enter/Space (when focused) | Same as click |
| Hover | Shows expanded label (chip hover state) |

### Toggle Chips

| Interaction | Behavior |
|-------------|----------|
| Click | Toggles boolean value |
| Enter/Space (when focused) | Same as click |

### Session Panel

| Interaction | Behavior |
|-------------|----------|
| Click on session ID | Copies session ID to clipboard, shows notification |

### Info Panel

| Interaction | Behavior |
|-------------|----------|
| Click on any data row | Copies that row's value to clipboard |

### Error Indicator

| Interaction | Behavior |
|-------------|----------|
| Mouse hover over indicator | Expands indicator to show details |
| Mouse leave | Collapses indicator |

## Footer Display

The footer displays mode-specific key hints, sourced from `FOOTER_KEYS` in
`input_modes.py`:

- **NORMAL:** filters, analytics, detail, panel, mode, follow, special, theme, info, preset, keys, search, launch, tail
- **SEARCH_EDIT:** enter, home/end, del-word, esc (keep), q (cancel), mode toggles
- **SEARCH_NAV:** next/prev (multiple key options), edit, esc (keep), q (cancel), scroll

## Keys Panel

The `?` key toggles a help panel that displays all keyboard shortcuts organized into
groups defined by `KEY_GROUPS` in `input_modes.py`:

- **Nav:** g/G, j/k, h/l, Ctrl+D/U, Ctrl+F/B
- **Categories:** 1-6 toggle, Q-Y detail, q-y analytics
- **Panels:** `.` cycle, `,` mode, `f` follow, Ctrl+L logs, `i` info, `?` keys
- **Search:** `/` search, `=`/`-` presets, Alt+N/P special, F1-9 load preset
- **Other:** `[`/`]` theme, `{`/`}` session, `c` launch, C/D/L/S utilities, Ctrl+C Ctrl+C quit
