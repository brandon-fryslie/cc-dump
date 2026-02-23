"""Search controller — all search interaction logic.

// [LAW:one-way-deps] Depends on search, formatting, rendering. No upward deps.
// [LAW:locality-or-seam] All search logic here — app.py keeps thin delegates.
// [LAW:single-enforcer] _force_vis is the sole runtime visibility override for search.

Not hot-reloadable (accesses app state and widgets).
"""

import cc_dump.core.formatting
import cc_dump.tui.search
import cc_dump.tui.location_navigation
from cc_dump.tui.category_config import CATEGORY_CONFIG


def _move_word_left(query: str, cursor_pos: int) -> int:
    """Return cursor position after moving one word left."""
    i = cursor_pos
    while i > 0 and query[i - 1].isspace():
        i -= 1
    while i > 0 and not query[i - 1].isspace():
        i -= 1
    return i


def _move_word_right(query: str, cursor_pos: int) -> int:
    """Return cursor position after moving one word right."""
    i = cursor_pos
    n = len(query)
    while i < n and query[i].isspace():
        i += 1
    while i < n and not query[i].isspace():
        i += 1
    return i


def _delete_prev_word(query: str, cursor_pos: int) -> tuple[str, int]:
    """Delete the word before cursor and return (query, cursor)."""
    start = _move_word_left(query, cursor_pos)
    return (query[:start] + query[cursor_pos:], start)


def _apply_edit_action(state, action: str) -> tuple[bool, bool]:
    """Apply an editing action.

    Returns (text_changed, cursor_changed).
    """
    query = state.query
    cursor = state.cursor_pos

    # [LAW:dataflow-not-control-flow] Action dispatch by value, not nested branches.
    if action == "backspace":
        if cursor <= 0:
            return (False, False)
        state.query = query[: cursor - 1] + query[cursor:]
        state.cursor_pos = cursor - 1
        return (True, True)
    if action == "delete":
        if cursor >= len(query):
            return (False, False)
        state.query = query[:cursor] + query[cursor + 1 :]
        return (True, False)
    if action == "left":
        if cursor <= 0:
            return (False, False)
        state.cursor_pos = cursor - 1
        return (False, True)
    if action == "right":
        if cursor >= len(query):
            return (False, False)
        state.cursor_pos = cursor + 1
        return (False, True)
    if action == "home":
        if cursor == 0:
            return (False, False)
        state.cursor_pos = 0
        return (False, True)
    if action == "end":
        end = len(query)
        if cursor == end:
            return (False, False)
        state.cursor_pos = end
        return (False, True)
    if action == "word_left":
        next_cursor = _move_word_left(query, cursor)
        if next_cursor == cursor:
            return (False, False)
        state.cursor_pos = next_cursor
        return (False, True)
    if action == "word_right":
        next_cursor = _move_word_right(query, cursor)
        if next_cursor == cursor:
            return (False, False)
        state.cursor_pos = next_cursor
        return (False, True)
    if action == "delete_prev_word":
        if cursor <= 0:
            return (False, False)
        next_query, next_cursor = _delete_prev_word(query, cursor)
        state.query = next_query
        state.cursor_pos = next_cursor
        return (True, True)
    if action == "kill_to_start":
        if cursor <= 0:
            return (False, False)
        state.query = query[cursor:]
        state.cursor_pos = 0
        return (True, True)
    if action == "kill_to_end":
        if cursor >= len(query):
            return (False, False)
        state.query = query[:cursor]
        return (True, False)
    return (False, False)


def _post_search_edit(app, *, text_changed: bool, cursor_changed: bool) -> None:
    """Run shared post-edit side effects for search query editing."""
    if text_changed or cursor_changed:
        update_search_bar(app)
    if text_changed and app._search_state.modes & cc_dump.tui.search.SearchMode.INCREMENTAL:
        schedule_incremental_search(app)


def start_search(app) -> None:
    """Transition: INACTIVE → EDITING. Save filter state and scroll position."""
    SearchPhase = cc_dump.tui.search.SearchPhase
    state = app._search_state
    state.phase = SearchPhase.EDITING
    state.query = ""
    state.cursor_pos = 0
    state.matches = []
    state.current_index = 0
    state.expanded_blocks = []
    # Save current filter state for restore on cancel
    store = app._view_store
    state.saved_filters = {
        name: (
            store.get(f"vis:{name}"),
            store.get(f"full:{name}"),
            store.get(f"exp:{name}"),
        )
        for _, name, _, _ in CATEGORY_CONFIG
    }
    # Save current scroll position
    conv = app._get_conv()
    if conv is not None:
        state.saved_scroll_y = conv.scroll_offset.y
    else:
        state.saved_scroll_y = None
    update_search_bar(app)


def handle_search_editing_key(app, event) -> None:
    """Handle keystrokes while editing the search query."""
    SearchMode = cc_dump.tui.search.SearchMode
    state = app._search_state
    key = event.key

    # Mode toggles (alt+key)
    _MODE_TOGGLES = {
        "alt+c": SearchMode.CASE_INSENSITIVE,
        "alt+w": SearchMode.WORD_BOUNDARY,
        "alt+r": SearchMode.REGEX,
        "alt+i": SearchMode.INCREMENTAL,
    }
    if key in _MODE_TOGGLES:
        state.modes ^= _MODE_TOGGLES[key]
        update_search_bar(app)
        if state.modes & SearchMode.INCREMENTAL:
            schedule_incremental_search(app)
        return

    # Editing actions and aliases.
    _EDIT_ACTIONS = {
        "backspace": "backspace",
        "ctrl+h": "backspace",
        "delete": "delete",
        "ctrl+d": "delete",
        "left": "left",
        "right": "right",
        "home": "home",
        "ctrl+a": "home",
        "end": "end",
        "ctrl+e": "end",
        "alt+b": "word_left",
        "alt+f": "word_right",
        "ctrl+w": "delete_prev_word",
        "alt+backspace": "delete_prev_word",
        "ctrl+u": "kill_to_start",
        "ctrl+k": "kill_to_end",
    }
    action = _EDIT_ACTIONS.get(key)
    if action is not None:
        text_changed, cursor_changed = _apply_edit_action(state, action)
        _post_search_edit(app, text_changed=text_changed, cursor_changed=cursor_changed)
        return

    # Submit
    if key == "enter":
        commit_search(app)
        return

    # Exit search - keep current position
    if key == "escape":
        exit_search_keep_position(app)
        return

    # Exit search - restore original position
    if key == "q":
        exit_search_restore_position(app)
        return

    # Printable character
    if event.character and len(event.character) == 1 and event.character.isprintable():
        state.query = (
            state.query[: state.cursor_pos]
            + event.character
            + state.query[state.cursor_pos :]
        )
        state.cursor_pos += 1
        update_search_bar(app)
        if state.modes & SearchMode.INCREMENTAL:
            schedule_incremental_search(app)
        return


def handle_search_nav_special_keys(app, event) -> bool:
    """Handle search-specific keys in NAVIGATING mode.

    Returns True if key was handled, False if it should fall through to keymap.
    """
    SearchPhase = cc_dump.tui.search.SearchPhase
    key = event.key

    # Navigate next/prev
    if key in {"n", "enter", "ctrl+n", "tab"}:
        navigate_next(app)
        return True

    if key in {"N", "ctrl+p", "shift+tab"}:
        navigate_prev(app)
        return True

    # Re-edit query
    if event.character == "/":
        app._search_state.phase = SearchPhase.EDITING
        app._search_state.cursor_pos = len(app._search_state.query)
        update_search_bar(app)
        return True

    # Exit search - keep current position
    if key == "escape":
        exit_search_keep_position(app)
        return True

    # Exit search - restore original position
    if key == "q":
        exit_search_restore_position(app)
        return True

    return False


def _exit_search_common(app) -> None:
    """Common cleanup when exiting search (any mode)."""
    SearchPhase = cc_dump.tui.search.SearchPhase
    state = app._search_state

    # Clear block expansion overrides we set
    clear_search_expand(app)

    # Restore saved filter levels — batched via store.update()
    updates = {}
    for name, (vis, full, exp) in state.saved_filters.items():
        updates[f"vis:{name}"] = vis
        updates[f"full:{name}"] = full
        updates[f"exp:{name}"] = exp
    app._view_store.update(updates)

    # Reset state
    state.phase = SearchPhase.INACTIVE
    state.query = ""
    state.matches = []
    state.current_index = 0
    state.expanded_blocks = []

    # Cancel debounce timer
    if state.debounce_timer is not None:
        state.debounce_timer.stop()
        state.debounce_timer = None

    update_search_bar(app)
    # Re-render without search context (highlights removed)
    conv = app._get_conv()
    if conv is not None:
        conv.rerender(app.active_filters)


def exit_search_keep_position(app) -> None:
    """Exit search and stay at current scroll position (Esc)."""
    conv = app._get_conv()
    if conv is not None:
        conv._scroll_anchor = conv._compute_anchor_from_scroll()
    _exit_search_common(app)


def exit_search_restore_position(app) -> None:
    """Exit search and restore original scroll position (q)."""
    _exit_search_common(app)
    state = app._search_state
    if state.saved_scroll_y is not None:
        conv = app._get_conv()
        if conv is not None:
            conv.scroll_to(y=state.saved_scroll_y, animate=False)
    state.saved_scroll_y = None


def commit_search(app) -> None:
    """Transition: EDITING → NAVIGATING. Run final search, navigate to first result."""
    SearchPhase = cc_dump.tui.search.SearchPhase
    state = app._search_state

    # Cancel debounce timer
    if state.debounce_timer is not None:
        state.debounce_timer.stop()
        state.debounce_timer = None

    # Run search
    run_search(app)

    if state.matches:
        state.phase = SearchPhase.NAVIGATING
        state.current_index = 0
        navigate_to_current(app)
    else:
        state.phase = SearchPhase.NAVIGATING

    update_search_bar(app)


def schedule_incremental_search(app) -> None:
    """Schedule a debounced incremental search (150ms)."""
    state = app._search_state
    if state.debounce_timer is not None:
        state.debounce_timer.stop()
    state.debounce_timer = app.set_timer(0.15, lambda: run_incremental_search(app))


def run_incremental_search(app) -> None:
    """Execute incremental search during editing."""
    state = app._search_state
    state.debounce_timer = None
    run_search(app)
    search_rerender(app)
    update_search_bar(app)


def run_search(app) -> None:
    """Compile pattern and find all matches."""
    state = app._search_state
    pattern = cc_dump.tui.search.compile_search_pattern(state.query, state.modes)
    if pattern is None:
        state.matches = []
        state.current_index = 0
        return

    conv = app._get_conv()
    if conv is None:
        state.matches = []
        return

    # // [LAW:no-shared-mutable-globals] Cache is state-owned; bounded locally.
    if len(state.text_cache) > 20_000:
        state.text_cache.clear()

    state.matches = cc_dump.tui.search.find_all_matches(
        conv._turns,
        pattern,
        text_cache=state.text_cache,
    )
    if state.current_index >= len(state.matches):
        state.current_index = 0


def navigate_next(app) -> None:
    """Move to next match (wraps around)."""
    state = app._search_state
    if not state.matches:
        return
    state.current_index = (state.current_index + 1) % len(state.matches)
    navigate_to_current(app)


def navigate_prev(app) -> None:
    """Move to previous match (wraps around)."""
    state = app._search_state
    if not state.matches:
        return
    state.current_index = (state.current_index - 1) % len(state.matches)
    navigate_to_current(app)


def navigate_to_current(app) -> None:
    """Navigate to the current match: expand block with _force_vis, scroll.

    For container children, sets _force_vis on both the container (so it
    expands to show children) AND the actual child block. Scroll uses
    identity-based lookup against td._flat_blocks to resolve the flat index.

    // [LAW:single-enforcer] _force_vis is the sole runtime visibility override.
    """
    state = app._search_state
    if not state.matches:
        return

    match = state.matches[state.current_index]
    conv = app._get_conv()
    if conv is None:
        return

    # Clear previous expansion
    clear_search_expand(app)

    # Get the block
    if match.turn_index >= len(conv._turns):
        return
    td = conv._turns[match.turn_index]
    if match.block_index >= len(td.blocks):
        return

    # // [LAW:single-enforcer] _force_vis is the runtime visibility override
    force_indices = {match.block_index}

    # Turn header cluster (HeaderBlock, SeparatorBlock, NewlineBlock at start)
    for i, b in enumerate(td.blocks):
        if type(b).__name__ in ("HeaderBlock", "SeparatorBlock", "NewlineBlock"):
            force_indices.add(i)
        else:
            break

    # Nearest preceding MessageBlock for role context
    for i in range(match.block_index - 1, -1, -1):
        if type(td.blocks[i]).__name__ == "MessageBlock":
            force_indices.add(i)
            break

    # // [LAW:one-source-of-truth] force_vis in ViewOverrides only
    for i in force_indices:
        if conv is not None:
            conv._view_overrides.get_block(td.blocks[i].block_id).force_vis = cc_dump.core.formatting.ALWAYS_VISIBLE
            conv._view_overrides._search_block_ids.add(td.blocks[i].block_id)
        state.expanded_blocks.append((match.turn_index, i, td.blocks[i].block_id))

    # Also force-vis the actual matched child block when it differs from
    # the container (i.e., the match is inside a child, not the container itself)
    matched_block = match.block
    if matched_block is not None and matched_block is not td.blocks[match.block_index]:
        if conv is not None:
            conv._view_overrides.get_block(matched_block.block_id).force_vis = cc_dump.core.formatting.ALWAYS_VISIBLE
            conv._view_overrides._search_block_ids.add(matched_block.block_id)
        state.expanded_blocks.append((match.turn_index, match.block_index, matched_block.block_id))

    # Re-render with search context, then navigate via shared location helper.
    location = cc_dump.tui.location_navigation.BlockLocation(
        turn_index=match.turn_index,
        block_index=match.block_index,
        block=matched_block,
    )
    cc_dump.tui.location_navigation.go_to_location(
        conv,
        location,
        rerender=lambda: search_rerender(app),
    )
    update_search_bar(app)


def clear_search_expand(app) -> None:
    """Reset force_vis on blocks we expanded during search.

    expanded_blocks entries are (turn_idx, block_idx, block_id) triples.
    // [LAW:one-source-of-truth] Clears via ViewOverrides.clear_search() only.
    """
    state = app._search_state
    conv = app._get_conv()
    if conv is not None:
        conv._view_overrides.clear_search()
    state.expanded_blocks.clear()


def search_rerender(app) -> None:
    """Re-render conversation with search highlights."""
    state = app._search_state
    conv = app._get_conv()
    if conv is None:
        return

    pattern = cc_dump.tui.search.compile_search_pattern(state.query, state.modes)
    search_ctx = None
    if pattern is not None:
        current_match = state.matches[state.current_index] if state.matches else None
        search_ctx = cc_dump.tui.search.SearchContext(
            pattern=pattern,
            pattern_str=state.query,
            current_match=current_match,
            all_matches=state.matches,
        )

    conv.rerender(app.active_filters, search_ctx=search_ctx)


def update_search_bar(app) -> None:
    """Update the search bar widget display and toggle Footer visibility."""
    SearchPhase = cc_dump.tui.search.SearchPhase
    bar = app._get_search_bar()
    footer = app._get_footer()

    if bar is not None:
        bar.update_display(app._search_state)

    # Footer hidden when search is active, visible when inactive
    search_active = app._search_state.phase != SearchPhase.INACTIVE
    if footer is not None:
        footer.display = not search_active
