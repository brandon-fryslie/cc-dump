"""Search controller — all search interaction logic.

// [LAW:one-way-deps] Depends on search, formatting, rendering. No upward deps.
// [LAW:locality-or-seam] All search logic here — app.py keeps thin delegates.
// [LAW:single-enforcer] _force_vis is the sole runtime visibility override for search.

Not hot-reloadable (accesses app state and widgets).
"""

import cc_dump.formatting
import cc_dump.tui.search
from cc_dump.tui.category_config import CATEGORY_CONFIG


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

    # Backspace
    if key == "backspace":
        if state.cursor_pos > 0:
            state.query = (
                state.query[: state.cursor_pos - 1] + state.query[state.cursor_pos :]
            )
            state.cursor_pos -= 1
            update_search_bar(app)
            if state.modes & SearchMode.INCREMENTAL:
                schedule_incremental_search(app)
        return

    # Delete
    if key == "delete":
        if state.cursor_pos < len(state.query):
            state.query = (
                state.query[: state.cursor_pos] + state.query[state.cursor_pos + 1 :]
            )
            update_search_bar(app)
            if state.modes & SearchMode.INCREMENTAL:
                schedule_incremental_search(app)
        return

    # Cursor movement
    if key == "left":
        if state.cursor_pos > 0:
            state.cursor_pos -= 1
            update_search_bar(app)
        return

    if key == "right":
        if state.cursor_pos < len(state.query):
            state.cursor_pos += 1
            update_search_bar(app)
        return

    if key == "home":
        state.cursor_pos = 0
        update_search_bar(app)
        return

    if key == "end":
        state.cursor_pos = len(state.query)
        update_search_bar(app)
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
    if key == "n" or key == "enter":
        navigate_next(app)
        return True

    if key == "N":
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

    state.matches = cc_dump.tui.search.find_all_matches(conv._turns, pattern)
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

    # Nearest preceding RoleBlock for role context
    for i in range(match.block_index - 1, -1, -1):
        if type(td.blocks[i]).__name__ == "RoleBlock":
            force_indices.add(i)
            break

    # // [LAW:one-source-of-truth] force_vis in ViewOverrides only
    for i in force_indices:
        if conv is not None:
            conv._view_overrides.get_block(td.blocks[i].block_id).force_vis = cc_dump.formatting.ALWAYS_VISIBLE
            conv._view_overrides._search_block_ids.add(td.blocks[i].block_id)
        state.expanded_blocks.append((match.turn_index, i, td.blocks[i].block_id))

    # Also force-vis the actual matched child block when it differs from
    # the container (i.e., the match is inside a child, not the container itself)
    matched_block = match.block
    if matched_block is not None and matched_block is not td.blocks[match.block_index]:
        if conv is not None:
            conv._view_overrides.get_block(matched_block.block_id).force_vis = cc_dump.formatting.ALWAYS_VISIBLE
            conv._view_overrides._search_block_ids.add(matched_block.block_id)
        state.expanded_blocks.append((match.turn_index, match.block_index, matched_block.block_id))

    # Re-render with search context, ensure target is materialized
    search_rerender(app)
    conv.ensure_turn_rendered(match.turn_index)

    # Find flat scroll key by identity: walk td._flat_blocks to find the
    # actual block object, then use the corresponding block_strip_map key.
    scroll_key = match.block_index  # fallback: hierarchical index
    if matched_block is not None:
        bsm_keys = list(td.block_strip_map.keys())
        for i, flat_block in enumerate(td._flat_blocks):
            if flat_block is matched_block and i < len(bsm_keys):
                scroll_key = bsm_keys[i]
                break

    conv.scroll_to_block(match.turn_index, scroll_key)
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
