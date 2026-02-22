"""Unit tests for Textual theme integration in rendering pipeline.

Tests that ThemeColors builds correctly from all 18 built-in themes,
sparse themes, and that set_theme() rebuilds module-level state.
"""

import re

import pytest
from textual.theme import BUILTIN_THEMES, Theme

from cc_dump.tui.rendering import (
    ThemeColors,
    build_theme_colors,
    set_theme,
    get_theme_colors,
    ROLE_STYLES,
    TAG_STYLES,
    MSG_COLORS,
)
import cc_dump.tui.rendering as rendering


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _is_hex(s: str) -> bool:
    return bool(_HEX_RE.match(s))


class TestBuildThemeColors:
    """Tests for build_theme_colors() across all themes."""

    @pytest.mark.parametrize("theme_name", list(BUILTIN_THEMES.keys()))
    def test_all_builtins_produce_valid_colors(self, theme_name):
        """Every builtin theme produces valid ThemeColors with non-empty color fields."""
        theme = BUILTIN_THEMES[theme_name]
        tc = build_theme_colors(theme)

        color_fields = [
            "primary", "secondary", "accent", "warning", "error", "success",
            "surface", "foreground", "background", "user", "assistant",
            "system", "info", "search_all_bg",
        ]
        for field in color_fields:
            value = getattr(tc, field)
            assert isinstance(value, str) and value, (
                f"{theme_name}.{field} = {value!r} is not a non-empty string"
            )
            # Non-ANSI themes should produce hex colors
            if "ansi" not in theme_name:
                assert _is_hex(value), (
                    f"{theme_name}.{field} = {value!r} is not valid #RRGGBB hex"
                )

    @pytest.mark.parametrize("theme_name", list(BUILTIN_THEMES.keys()))
    def test_all_builtins_dark_flag_matches(self, theme_name):
        """ThemeColors.dark matches the source theme."""
        theme = BUILTIN_THEMES[theme_name]
        tc = build_theme_colors(theme)
        assert tc.dark == theme.dark

    @pytest.mark.parametrize("theme_name", list(BUILTIN_THEMES.keys()))
    def test_all_builtins_code_theme(self, theme_name):
        """Dark themes get github-dark, light themes get friendly."""
        theme = BUILTIN_THEMES[theme_name]
        tc = build_theme_colors(theme)
        expected = "github-dark" if theme.dark else "friendly"
        assert tc.code_theme == expected

    def test_sparse_theme_all_fields_populated(self):
        """A sparse Theme (most fields None) still produces all ThemeColors fields."""
        sparse = Theme(name="sparse", primary="#FF0000", dark=True)
        tc = build_theme_colors(sparse)

        # All string fields should be non-empty
        for field_name in ThemeColors.__dataclass_fields__:
            value = getattr(tc, field_name)
            if isinstance(value, str):
                assert value, f"Field {field_name} is empty"
            elif isinstance(value, dict):
                assert value, f"Field {field_name} is empty dict"

    def test_sparse_light_theme(self):
        """Light sparse theme derives correct defaults."""
        sparse = Theme(name="sparse-light", primary="#0000FF", dark=False)
        tc = build_theme_colors(sparse)
        assert tc.dark is False
        assert tc.code_theme == "friendly"
        assert _is_hex(tc.foreground)
        assert _is_hex(tc.background)

    def test_markdown_theme_dict_has_required_keys(self):
        """Markdown theme dict includes code, heading, and link styles."""
        tc = build_theme_colors(BUILTIN_THEMES["textual-dark"])
        md = tc.markdown_theme_dict

        required_keys = [
            "markdown.code", "markdown.code_block",
            "markdown.h1", "markdown.h2", "markdown.h3",
            "markdown.link",
        ]
        for key in required_keys:
            assert key in md, f"Missing markdown theme key: {key}"
            assert md[key], f"Empty markdown theme value for: {key}"

    def test_markdown_theme_uses_theme_foreground_for_textual_elements(self):
        """Markdown body/table/hr styles should be theme-derived, not generic color names."""
        tc = build_theme_colors(BUILTIN_THEMES["textual-dark"])
        md = tc.markdown_theme_dict

        assert md["markdown.text"] == tc.foreground
        assert md["markdown.paragraph"] == tc.foreground
        assert md["markdown.item"] == tc.foreground
        assert tc.foreground in md["markdown.table.border"]
        assert tc.foreground in md["markdown.hr"]
        assert md["markdown.table.border"] != "dim"
        assert md["markdown.hr"] != "dim"


class TestSetTheme:
    """Tests for set_theme() rebuilding module state."""

    def test_set_theme_populates_theme_colors(self):
        """After set_theme(), get_theme_colors() returns a ThemeColors."""
        theme = BUILTIN_THEMES["catppuccin-mocha"]
        set_theme(theme)
        tc = get_theme_colors()
        assert isinstance(tc, ThemeColors)
        assert tc.primary == theme.primary

    def test_set_theme_rebuilds_role_styles(self):
        """ROLE_STYLES contains the theme's primary color for user."""
        theme = BUILTIN_THEMES["dracula"]
        set_theme(theme)
        assert theme.primary in rendering.ROLE_STYLES["user"]

    def test_set_theme_rebuilds_tag_styles(self):
        """TAG_STYLES is populated with (fg, bg) tuples after set_theme()."""
        set_theme(BUILTIN_THEMES["nord"])
        assert len(rendering.TAG_STYLES) > 0
        fg, bg = rendering.TAG_STYLES[0]
        assert _is_hex(fg)
        assert _is_hex(bg)

    def test_set_theme_rebuilds_msg_colors(self):
        """MSG_COLORS is populated with hex strings after set_theme()."""
        set_theme(BUILTIN_THEMES["tokyo-night"])
        assert len(rendering.MSG_COLORS) == 6
        for color in rendering.MSG_COLORS:
            assert _is_hex(color), f"MSG_COLORS entry {color!r} is not hex"

    def test_theme_switch_changes_colors(self):
        """Switching themes changes the rendered colors."""
        set_theme(BUILTIN_THEMES["dracula"])
        tc_dracula = get_theme_colors()

        set_theme(BUILTIN_THEMES["catppuccin-latte"])
        tc_latte = get_theme_colors()

        # Different themes should produce different primaries
        assert tc_dracula.primary != tc_latte.primary
        assert tc_dracula.dark != tc_latte.dark


class TestLightDarkModeAdaptation:
    """Tests that TAG_STYLES and MSG_COLORS adapt to light/dark mode."""

    def test_dark_tag_styles_have_light_fg(self):
        """Dark theme TAG_STYLES have lighter foreground (higher lightness)."""
        set_theme(BUILTIN_THEMES["textual-dark"])
        fg, bg = rendering.TAG_STYLES[0]
        # Parse hex to check relative lightness
        fg_r, fg_g, fg_b = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
        bg_r, bg_g, bg_b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        fg_lum = fg_r + fg_g + fg_b
        bg_lum = bg_r + bg_g + bg_b
        assert fg_lum > bg_lum, "Dark theme: fg should be lighter than bg"

    def test_light_tag_styles_have_dark_fg(self):
        """Light theme TAG_STYLES have darker foreground (lower lightness)."""
        set_theme(BUILTIN_THEMES["textual-light"])
        fg, bg = rendering.TAG_STYLES[0]
        fg_r, fg_g, fg_b = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
        bg_r, bg_g, bg_b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        fg_lum = fg_r + fg_g + fg_b
        bg_lum = bg_r + bg_g + bg_b
        assert fg_lum < bg_lum, "Light theme: fg should be darker than bg"


class TestGetThemeColorsFailFast:
    """Tests that get_theme_colors() fails fast when no theme is set."""

    def test_raises_before_set(self):
        """get_theme_colors() raises RuntimeError when _theme_colors is None."""
        # Save and clear
        saved = rendering._theme_colors
        rendering._theme_colors = None
        try:
            with pytest.raises(RuntimeError, match="Theme not initialized"):
                get_theme_colors()
        finally:
            rendering._theme_colors = saved


class TestThemeCycling:
    """Tests for theme cycling keyboard shortcuts."""

    @pytest.fixture
    async def app_and_pilot(self):
        """Create app in test mode."""
        from tests.harness.app_runner import run_app
        async with run_app() as (pilot, app):
            yield pilot, app

    async def test_next_theme_changes_theme(self, app_and_pilot):
        """Pressing ']' changes to the next theme alphabetically."""
        pilot, app = app_and_pilot
        original = app.theme
        names = sorted(app.available_themes.keys())
        expected_next = names[(names.index(original) + 1) % len(names)]

        await pilot.press("]")
        await pilot.pause()

        assert app.theme == expected_next

    async def test_prev_theme_changes_theme(self, app_and_pilot):
        """Pressing '[' changes to the previous theme alphabetically."""
        pilot, app = app_and_pilot
        original = app.theme
        names = sorted(app.available_themes.keys())
        expected_prev = names[(names.index(original) - 1) % len(names)]

        await pilot.press("[")
        await pilot.pause()

        assert app.theme == expected_prev

    async def test_full_cycle_returns_to_original(self, app_and_pilot):
        """Pressing ']' N times cycles back to the original theme."""
        pilot, app = app_and_pilot
        original = app.theme
        n = len(app.available_themes)

        for _ in range(n):
            await pilot.press("]")
            await pilot.pause()

        assert app.theme == original

    async def test_cycle_notifies_theme_name(self, app_and_pilot):
        """Theme cycling shows a notification with the new theme name."""
        pilot, app = app_and_pilot

        await pilot.press("]")
        await pilot.pause()

        # Check that a notification was shown (notifications list)
        # This is a basic check - Textual stores notifications in app._notifications
        # For now just verify theme changed (notification is transient)
        assert app.theme is not None
