"""Theme management for the TUI app.

// [LAW:one-way-deps] Depends on rendering module. No upward deps.
// [LAW:locality-or-seam] All theme logic here — app.py just delegates.

Not hot-reloadable (accesses app console and theme state).
"""

import cc_dump.tui.rendering
from rich.theme import Theme as RichTheme


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
            try:
                app.console.pop_theme()
            except Exception:
                pass
            app._markdown_theme_pushed = False
        return

    tc = cc_dump.tui.rendering.get_theme_colors()

    # Pop old markdown theme if we pushed one before
    if app._markdown_theme_pushed:
        try:
            app.console.pop_theme()
        except Exception:
            pass  # No theme to pop on first call
    app.console.push_theme(RichTheme(tc.markdown_theme_dict))
    app._markdown_theme_pushed = True
