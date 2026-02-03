"""Shared formatting utilities used across rendering and panel modules.

This module is RELOADABLE and contains common display formatting functions.
"""


def fmt_tokens(n: int) -> str:
    """Format token count for compact display: 1.2k, 68.9k, etc."""
    if n >= 1000:
        return "{:.1f}k".format(n / 1000)
    return str(n)


def fmt_input_with_cache(input_tokens: int, cache_read_tokens: int) -> str:
    """Format input tokens with cache percentage if applicable.

    Args:
        input_tokens: Number of input tokens (non-cached)
        cache_read_tokens: Number of cache read tokens

    Returns:
        Formatted string like "1.2k (75%)" or "--" if no input
    """
    if input_tokens > 0:
        total_input = input_tokens + cache_read_tokens
        if cache_read_tokens > 0 and total_input > 0:
            cache_pct = 100 * cache_read_tokens / total_input
            return "{} ({:.0f}%)".format(fmt_tokens(input_tokens), cache_pct)
        else:
            return fmt_tokens(input_tokens)
    else:
        return "--"
