"""Tests to verify footer renders correctly without literal markup tags."""

import pytest

from tests.conftest import settle, wait_for_content

pytestmark = pytest.mark.pty


def _get_footer_content(proc):
    """Wait for and return content with footer visible."""
    return wait_for_content(
        proc,
        lambda c: any(word in c.lower() for word in ["metadata", "tools", "system", "quit"]),
        timeout=5,
    )


class TestFooterMarkupRendering:
    """Test that footer does NOT show literal [bold] tags — shared process."""

    def test_footer_actually_renders_content(self, class_proc):
        """CRITICAL: Footer must actually display binding text."""
        proc = class_proc
        content = _get_footer_content(proc)

        required_words = ["tools", "system", "metadata", "thinking"]
        found = [word for word in required_words if word in content.lower()]

        assert len(found) > 0, \
            f"Footer is NOT rendering any content! Expected to find at least one of {required_words}.\nContent:\n{content}"

    def test_footer_does_not_duplicate_key_letters(self, class_proc):
        """CRITICAL: Footer must NOT show duplicate key letters like 'h h|eaders'."""
        proc = class_proc
        content = _get_footer_content(proc)

        lines = [line.strip() for line in content.split('\n') if line.strip()]
        footer_lines = [
            line for line in lines
            if any(word in line.lower() for word in ['tools', 'system', 'metadata', 'thinking'])
        ]

        assert len(footer_lines) > 0, \
            f"Could not find footer in output.\nAll lines:\n" + "\n".join(lines[-5:])

        footer_text = ' '.join(footer_lines).lower()

        duplicate_patterns = [
            (" 1 1", "user"),
            (" 2 2", "assistant"),
            (" 3 3", "tools"),
            (" 4 4", "system"),
            (" 5 5", "metadata"),
            (" 6 6", "thinking"),
        ]

        for pattern, binding_name in duplicate_patterns:
            if binding_name in footer_text:
                assert pattern not in footer_text, \
                    f"Footer is showing duplicate key letter! Found '{pattern.strip()}' before '{binding_name}':\n{footer_text}"

    def test_footer_does_not_contain_literal_bold_tags(self, class_proc):
        """CRITICAL: Footer must NOT display literal '[bold]' or '[/bold]' text."""
        proc = class_proc
        content = _get_footer_content(proc)

        assert "bold" not in content.lower(), \
            f"Footer is displaying literal markup tags! Output contains 'bold':\n{content}"

        assert "[bold]" not in content, \
            f"Footer is displaying literal [bold] tags:\n{content}"

        assert "[/bold]" not in content, \
            f"Footer is displaying literal [/bold] tags:\n{content}"

    def test_footer_shows_binding_keys(self, class_proc):
        """Footer should show the keybinding letters."""
        proc = class_proc
        content = _get_footer_content(proc)

        lower_content = content.lower()
        assert any(x in lower_content for x in ["tool", "system", "metadata"]), \
            f"Footer should show binding descriptions. Content:\n{content}"

    def test_footer_shows_multiple_bindings(self, class_proc):
        """Footer should show multiple keybinding descriptions."""
        proc = class_proc
        content = _get_footer_content(proc)

        lower_content = content.lower()
        expected_features = ["tools", "system", "metadata", "thinking", "user", "assistant", "cost", "timeline"]
        found = [feat for feat in expected_features if feat in lower_content]

        assert len(found) >= 3, \
            f"Footer should show some bindings. Found: {found}, Expected: {expected_features}\nContent:\n{content}"

    def test_footer_shows_keybinding_letters_in_words(self, class_proc):
        """Footer should show full words like 'headers', 'tools', not just single letters."""
        proc = class_proc
        content = _get_footer_content(proc)

        full_words = ["tools", "system", "metadata", "thinking"]
        lower_content = content.lower()

        found_words = [word for word in full_words if word in lower_content]

        assert len(found_words) >= 2, \
            f"Footer should show full binding words, not just letters. Found: {found_words}\nContent:\n{content}"

    def test_footer_shows_log_path_when_idle(self, class_proc):
        """Stream row shows log file path when no streams are active."""
        proc = class_proc
        content = _get_footer_content(proc)
        assert "log:" in content.lower(), f"Expected 'log:' row. Content:\n{content}"
