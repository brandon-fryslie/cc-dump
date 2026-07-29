"""Theme management for the TUI app.

// [LAW:one-way-deps] Depends on rendering module. No upward deps.
// [LAW:locality-or-seam] All theme logic here — app.py just delegates.

Hot-reloadable — imported as module object in app.py, stateless.
"""

import contextlib

from rich.theme import Theme as RichTheme, ThemeStackError

import cc_dump.tui.rendering


def cycle_theme(app, direction: int) -> None:
    """Cycle to the next (+1) or previous (-1) theme.

    // [LAW:dataflow-not-control-flow] Always computes sorted list and
    // sets app.theme; watch_theme() handles all downstream effects.
    // [LAW:one-type-per-behavior] One function for both directions.
    """
    names = sorted(app.available_themes.keys())
    current_index = names.index(app.theme)
    new_index = (current_index + direction) % len(names)
    new_name = names[new_index]
    app.theme = new_name
    if app._settings_store is not None:
        app._settings_store.set("theme", new_name)
    app.notify(f"Theme: {new_name}")


def apply_markdown_theme(app) -> None:
    """Push/replace markdown Rich theme on the console.

    Pops the old theme (if any) and pushes a fresh one from ThemeColors.
    Skips ANSI themes which use color names Rich can't parse.
    """
    # Skip markdown theme for ANSI-based Textual themes
    if "ansi" in app.theme.lower():
        if app._markdown_theme_pushed:
            # pop_theme() raises ThemeStackError if the stack is already at its base
            # (e.g. hot-reload state desync); that is a benign no-op here.
            with contextlib.suppress(ThemeStackError):
                app.console.pop_theme()
            app._markdown_theme_pushed = False
        return

    runtime = cc_dump.tui.rendering.get_runtime_from_owner(app)
    tc = cc_dump.tui.rendering.get_theme_colors(runtime=runtime)

    # Pop old markdown theme if we pushed one before
    if app._markdown_theme_pushed:
        # No theme to pop on first call (or after a hot-reload state desync).
        with contextlib.suppress(ThemeStackError):
            app.console.pop_theme()
    app.console.push_theme(RichTheme(tc.markdown_theme_dict))
    app._markdown_theme_pushed = True
