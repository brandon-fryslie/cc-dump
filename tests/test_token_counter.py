"""Tests for token_counter module."""

import pytest
from cc_dump.core.token_counter import count_tokens


def test_count_tokens_empty_string():
    """Empty string returns 0 tokens."""
    assert count_tokens("") == 0


def test_count_tokens_simple_text():
    """Simple text returns reasonable token count."""
    text = "Hello, world!"
    tokens = count_tokens(text)
    assert tokens > 0
    # "Hello, world!" is ~3-4 tokens in cl100k_base
    assert 2 <= tokens <= 6


def test_count_tokens_longer_text():
    """Longer text returns proportionally more tokens."""
    short = "Hello"
    long = "Hello " * 100  # Repeat 100 times
    short_tokens = count_tokens(short)
    long_tokens = count_tokens(long)
    # Long text should have significantly more tokens
    assert long_tokens > short_tokens * 50


def test_count_tokens_json():
    """JSON content is tokenized correctly."""
    json_text = '{"key": "value", "number": 42, "array": [1, 2, 3]}'
    tokens = count_tokens(json_text)
    assert tokens > 0
    # JSON with brackets/braces/quotes adds tokens
    assert 10 <= tokens <= 30


def test_count_tokens_large_text():
    """Large texts are handled correctly."""
    # Generate a large text with varied content
    # Use different words to avoid compression
    large_text = " ".join(f"word{i}" for i in range(2000))
    tokens = count_tokens(large_text)
    assert tokens > 0
    # Each wordN becomes multiple tokens (word + number), so ~4000-6000 tokens
    assert 3000 <= tokens <= 7000


def test_count_tokens_caching():
    """Encoding is cached and reused across calls."""
    # Multiple calls should work without issues (verifies caching doesn't break)
    text = "test caching"
    tokens1 = count_tokens(text)
    tokens2 = count_tokens(text)
    assert tokens1 == tokens2
    assert tokens1 > 0


def test_count_tokens_unicode():
    """Unicode characters are handled correctly."""
    text = "Hello 世界 🌍"
    tokens = count_tokens(text)
    assert tokens > 0
    # Unicode characters typically use more tokens
    assert 3 <= tokens <= 15


def test_count_tokens_code():
    """Code snippets are tokenized correctly."""
    code = """
def hello_world():
    print("Hello, world!")
    return 42
"""
    tokens = count_tokens(code)
    assert tokens > 0
    # Code with syntax has specific tokenization
    assert 10 <= tokens <= 30
