"""Tests for token_counter module."""

from cc_dump.core.token_counter import count_tokens


def test_count_tokens_empty_string_returns_zero_for_compat():
    """Empty string preserves legacy counter behavior."""
    assert count_tokens("") == 0


def test_count_tokens_simple_text():
    """Simple text follows 4-char heuristic."""
    text = "Hello, world!"
    assert count_tokens(text) == len(text) // 4


def test_count_tokens_longer_text():
    """Longer text scales linearly with character count."""
    short = "Hello"
    long = "Hello " * 100  # Repeat 100 times
    short_tokens = count_tokens(short)
    long_tokens = count_tokens(long)
    assert short_tokens == len(short) // 4
    assert long_tokens == len(long) // 4
    assert long_tokens > short_tokens


def test_count_tokens_json():
    """JSON content is counted by character length."""
    json_text = '{"key": "value", "number": 42, "array": [1, 2, 3]}'
    assert count_tokens(json_text) == len(json_text) // 4


def test_count_tokens_large_text():
    """Large texts are handled correctly."""
    # Generate a large text with varied content
    # Use different words to avoid compression
    large_text = " ".join(f"word{i}" for i in range(2000))
    assert count_tokens(large_text) == len(large_text) // 4


def test_count_tokens_caching():
    """Multiple calls remain deterministic."""
    text = "test caching"
    tokens1 = count_tokens(text)
    tokens2 = count_tokens(text)
    assert tokens1 == tokens2
    assert tokens1 == len(text) // 4


def test_count_tokens_unicode():
    """Unicode strings are handled as Python character length."""
    text = "Hello 世界 🌍"
    assert count_tokens(text) == len(text) // 4


def test_count_tokens_code():
    """Code snippets follow the same heuristic policy."""
    code = """
def hello_world():
    print("Hello, world!")
    return 42
"""
    assert count_tokens(code) == len(code) // 4
