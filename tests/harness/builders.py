"""Shared builders for replay data in Textual tests."""


def make_replay_entry(
    content="Hello world",
    response_text="Response from assistant",
    system_prompt=None,
    model="claude-sonnet-4-5-20250929",
    provider="anthropic",
):
    """Create a single replay entry.

    Args:
        content: User message content
        response_text: Assistant response text
        system_prompt: Optional system prompt text (or list of text blocks)
        model: Model identifier
        provider: API provider identifier

    Returns:
        Tuple: (req_headers, req_body, resp_status, resp_headers, complete_message, provider)
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

    return (
        {"content-type": "application/json"},  # req_headers
        req_body,
        200,  # resp_status
        {"content-type": "application/json"},  # resp_headers
        complete_message,
        provider,
    )


def make_replay_data(n=1, **kwargs):
    """Create a list of N replay entries with numbered messages.

    Args:
        n: Number of replay entries to create
        **kwargs: Arguments passed to make_replay_entry() for customization

    Returns:
        List of replay entry tuples
    """
    entries = []
    for i in range(n):
        # Override content/response_text with numbered versions if not provided
        entry_kwargs = kwargs.copy()
        if "content" not in entry_kwargs:
            entry_kwargs["content"] = f"Message {i}"
        if "response_text" not in entry_kwargs:
            entry_kwargs["response_text"] = f"Response {i}"

        # Create entry with unique message ID
        entry = make_replay_entry(**entry_kwargs)
        # Update message ID to be unique
        req_headers, req_body, resp_status, resp_headers, complete_message, prov = entry
        complete_message = complete_message.copy()
        complete_message["id"] = f"msg_{i}"
        entries.append((req_headers, req_body, resp_status, resp_headers, complete_message, prov))

    return entries
