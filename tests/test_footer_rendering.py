"""Tests to verify footer renders correctly without literal markup tags."""

import pytest
import time


class TestFooterMarkupRendering:
    """Test that footer does NOT show literal [bold] tags."""

    def test_footer_actually_renders_content(self, start_cc_dump):
        """CRITICAL: Footer must actually display binding text."""
        proc = start_cc_dump()
        assert proc.is_alive()

        time.sleep(0.5)
        content = proc.get_content()

        # Debug: print actual content to see what's there
        print("\n=== ACTUAL FOOTER CONTENT ===")
        lines = content.split('\n')
        for i, line in enumerate(lines[-10:]):  # Last 10 lines
            print(f"Line {i}: {repr(line)}")
        print("=== END CONTENT ===\n")

        # Footer MUST contain at least one of these words
        required_words = ["headers", "tools", "system", "metadata"]
        found = [word for word in required_words if word in content.lower()]

        assert len(found) > 0, \
            f"Footer is NOT rendering any content! Expected to find at least one of {required_words}.\nContent:\n{content}"

    def test_footer_does_not_duplicate_key_letters(self, start_cc_dump):
        """CRITICAL: Footer must NOT show duplicate key letters like 'h h|eaders' or 'h headers'.

        Should show: 'headers tools system' (with letters in bold)
        NOT: 'h headers t tools s system'
        """
        proc = start_cc_dump()
        assert proc.is_alive()

        time.sleep(0.5)
        content = proc.get_content()

        # Extract just the footer line (last non-empty line typically)
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        # Footer is one of the last lines, look for lines with binding keywords
        footer_lines = [
            line for line in lines
            if any(word in line.lower() for word in ['headers', 'tools', 'system', 'metadata'])
        ]

        assert len(footer_lines) > 0, \
            f"Could not find footer in output. Looking for lines with 'headers', 'tools', 'system', or 'metadata'.\nAll lines:\n" + "\n".join(lines[-5:])

        footer_text = ' '.join(footer_lines).lower()

        # Look for duplicate key patterns in the footer specifically
        # Pattern: single letter followed by same letter starting a word
        # E.g., "h headers", "t tools", etc.
        duplicate_patterns = [
            (" h h", "headers"),
            (" t t", "tools"),
            (" s s", "system"),
            (" e e", "context"),
            (" m m", "metadata"),
            (" a a", "stats"),
            (" c c", "cost"),
            (" l l", "timeline"),
        ]

        for pattern, binding_name in duplicate_patterns:
            if binding_name in footer_text:
                assert pattern not in footer_text, \
                    f"Footer is showing duplicate key letter! Found '{pattern.strip()}' before '{binding_name}':\n{footer_text}"

    def test_footer_does_not_contain_literal_bold_tags(self, start_cc_dump):
        """CRITICAL: Footer must NOT display literal '[bold]' or '[/bold]' text."""
        proc = start_cc_dump()
        assert proc.is_alive()

        time.sleep(0.5)
        content = proc.get_content()

        # The word "bold" should NEVER appear in the output
        assert "bold" not in content.lower(), \
            f"Footer is displaying literal markup tags! Output contains 'bold':\n{content}"

        assert "[bold]" not in content, \
            f"Footer is displaying literal [bold] tags:\n{content}"

        assert "[/bold]" not in content, \
            f"Footer is displaying literal [/bold] tags:\n{content}"

    def test_footer_shows_binding_keys(self, start_cc_dump):
        """Footer should show the keybinding letters."""
        proc = start_cc_dump()
        assert proc.is_alive()

        time.sleep(0.5)
        content = proc.get_content()

        # Should see the actual binding descriptions
        # (exact format depends on rendering, but should have key info)
        lower_content = content.lower()
        assert any(x in lower_content for x in ["header", "tool", "system"]), \
            f"Footer should show binding descriptions. Content:\n{content}"

    def test_footer_shows_multiple_bindings(self, start_cc_dump):
        """Footer should show multiple keybinding descriptions."""
        proc = start_cc_dump()
        assert proc.is_alive()

        time.sleep(0.5)
        content = proc.get_content()

        # Should mention the key bindings somehow
        lower_content = content.lower()

        # Check that footer is displaying binding descriptions
        # Note: In narrow terminals, footer may be truncated, so we just verify it's working
        expected_features = ["headers", "tools", "system", "context", "metadata", "stats", "cost", "timeline"]
        found = [feat for feat in expected_features if feat in lower_content]

        # At least 3 bindings should be visible (footer is working)
        assert len(found) >= 3, \
            f"Footer should show some bindings. Found: {found}, Expected: {expected_features}\nContent:\n{content}"

    def test_footer_shows_keybinding_letters_in_words(self, start_cc_dump):
        """Footer should show full words like 'headers', 'tools', not just single letters."""
        proc = start_cc_dump()
        assert proc.is_alive()

        time.sleep(0.5)
        content = proc.get_content()

        # Look for full words, not just single letters
        full_words = ["headers", "tools", "system", "metadata"]
        lower_content = content.lower()

        found_words = [word for word in full_words if word in lower_content]

        assert len(found_words) >= 2, \
            f"Footer should show full binding words, not just letters. Found: {found_words}\nContent:\n{content}"
