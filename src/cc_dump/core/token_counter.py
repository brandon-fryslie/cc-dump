"""Compatibility wrapper for legacy token-counter imports.

// [LAW:one-source-of-truth] Canonical estimated token policy is
// core.analysis.estimate_tokens; this wrapper delegates to it.
"""

from cc_dump.core.analysis import estimate_tokens


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Return the canonical estimated token count for text.

    Args:
        text: The text to tokenize
        model: Compatibility parameter; currently ignored.

    Returns:
        Number of estimated tokens. Returns 0 for empty strings.
    """
    _ = model
    if not text:
        return 0
    return estimate_tokens(text)
