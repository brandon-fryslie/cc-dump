from cc_dump.ai.scope_token_helpers import (
    build_message_context_lines,
    estimate_tokens_from_text,
    normalize_message_content,
)


def test_normalize_message_content_extracts_text_blocks_only():
    value = normalize_message_content(
        [
            {"type": "text", "text": "alpha"},
            {"type": "image", "source": "..."},
            {"type": "text", "text": "beta"},
        ]
    )
    assert value == "alpha beta"


def test_normalize_message_content_applies_truncation():
    value = normalize_message_content("x" * 10, truncate_content_at=4)
    assert value == "xxxx..."


def test_build_message_context_lines_applies_template():
    lines = build_message_context_lines(
        [{"role": "assistant", "content": "hello"}],
        line_template="[{role}] {content}",
    )
    assert lines == ["[assistant] hello"]


def test_estimate_tokens_from_text_matches_core_policy():
    assert estimate_tokens_from_text("") == 1
    assert estimate_tokens_from_text("abcd") == 1
    assert estimate_tokens_from_text("abcde") == 1
