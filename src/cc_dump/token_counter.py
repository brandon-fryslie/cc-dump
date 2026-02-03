"""Token counting using tiktoken local tokenizer.

Pure utility module with zero dependencies on other cc_dump modules.
Uses cl100k_base encoding (GPT-4 tokenizer) which provides ~95% accuracy
for Claude models.
"""

import tiktoken

# Cache encoding instance for reuse
_ENCODING = None


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken.

    Args:
        text: The text to tokenize
        model: Encoding to use (default: cl100k_base for GPT-4/Claude approximation)

    Returns:
        Number of tokens. Returns 0 for empty strings.
    """
    if not text:
        return 0

    global _ENCODING
    if _ENCODING is None:
        _ENCODING = tiktoken.get_encoding("cl100k_base")

    return len(_ENCODING.encode(text))
