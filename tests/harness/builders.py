"""Shared builders for replay data in Textual tests."""

from dataclasses import replace

from cc_dump.pipeline.har_replayer import ReplayPair


def make_replay_entry(
    content="Hello world",
    response_text="Response from assistant",
    system_prompt=None,
    model="claude-sonnet-4-5-20250929",
    provider="anthropic",
) -> ReplayPair:
    """Create a single ReplayPair for use in tests.

    Args:
        content: User message content
        response_text: Assistant response text
        system_prompt: Optional system prompt text (or list of text blocks)
        model: Model identifier
        provider: API provider identifier
    """
    req_body = {
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": content}],
    }

    # Add system prompt if provided
    if system_prompt is not None:
        if isinstance(system_prompt, str):
            req_body["system"] = [{"type": "text", "text": system_prompt}]
        else:
            req_body["system"] = system_prompt

    complete_message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": response_text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }

    return ReplayPair(
        request_headers={"content-type": "application/json"},
        request_body=req_body,
        response_status=200,
        response_headers={"content-type": "application/json"},
        complete_message=complete_message,
        provider=provider,
    )


def make_replay_data(n=1, **kwargs) -> list[ReplayPair]:
    """Create a list of N ReplayPair entries with numbered messages.

    Args:
        n: Number of replay entries to create
        **kwargs: Arguments passed to make_replay_entry() for customization
    """
    entries: list[ReplayPair] = []
    for i in range(n):
        entry_kwargs = kwargs.copy()
        if "content" not in entry_kwargs:
            entry_kwargs["content"] = f"Message {i}"
        if "response_text" not in entry_kwargs:
            entry_kwargs["response_text"] = f"Response {i}"

        pair = make_replay_entry(**entry_kwargs)
        # Stamp a unique message id per entry.
        unique_message = {**pair.complete_message, "id": f"msg_{i}"}
        entries.append(replace(pair, complete_message=unique_message))

    return entries
