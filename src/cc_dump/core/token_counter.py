"""Compatibility wrapper for legacy token-counter imports.

// [LAW:one-source-of-truth] Canonical estimated token policy is
// core.analysis.estimate_tokens; this wrapper delegates to it.
"""

from cc_dump.core.analysis import estimate_tokens

_DEFAULT_MODEL = "cl100k_base"


def count_tokens(text: str, model: str = _DEFAULT_MODEL) -> int:
    """Return the canonical estimated token count for text.

    Args:
        text: The text to tokenize
        model: Compatibility parameter; only ``cl100k_base`` is accepted.

    Returns:
        Number of estimated tokens. Returns 0 for empty strings.
    """
    # [LAW:single-enforcer] Model compatibility validation is enforced at this
    # boundary so callers cannot silently assume alternate encodings are used.
    if model != _DEFAULT_MODEL:
        raise ValueError(f"unsupported token counter model: {model!r}; expected {_DEFAULT_MODEL!r}")
    if not text:
        return 0
    return estimate_tokens(text)
