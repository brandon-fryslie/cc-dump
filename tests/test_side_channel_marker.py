from cc_dump.ai.side_channel_marker import (
    SideChannelMarker,
    encode_marker,
    extract_marker,
    prepend_marker,
    strip_marker_from_body,
)


def test_encode_and_extract_marker_from_string_content():
    marker = SideChannelMarker(
        run_id="abc123",
        purpose="block_summary",
        source_provider="anthropic",
    )
    body = {
        "messages": [
            {"role": "user", "content": prepend_marker("hello", marker)},
        ]
    }
    parsed = extract_marker(body)
    assert parsed is not None
    assert parsed.run_id == "abc123"
    assert parsed.purpose == "block_summary"
    assert parsed.source_provider == "anthropic"
    assert parsed.prompt_version == "v1"
    assert parsed.policy_version == ""


def test_strip_marker_from_body_removes_prefix_line():
    marker = SideChannelMarker(
        run_id="abc123",
        purpose="block_summary",
        source_provider="anthropic",
    )
    body = {
        "messages": [
            {"role": "assistant", "content": "ignore"},
            {"role": "user", "content": prepend_marker("real prompt", marker)},
        ]
    }
    stripped = strip_marker_from_body(body)
    assert stripped["messages"][-1]["content"] == "real prompt"


def test_extract_marker_from_block_content():
    marker = SideChannelMarker(
        run_id="abc123",
        purpose="action_extraction",
        source_provider="openai",
    )
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prepend_marker("prompt", marker)},
                ],
            }
        ]
    }
    parsed = extract_marker(body)
    assert parsed is not None
    assert parsed.purpose == "action_extraction"
    assert parsed.source_provider == "openai"


def test_encode_marker_has_expected_delimiters():
    marker = SideChannelMarker(run_id="x", purpose="block_summary")
    encoded = encode_marker(marker)
    assert encoded.startswith("<<CC_DUMP_SIDE_CHANNEL:")
    assert encoded.endswith(">>")
    assert '"prompt_version":"v1"' in encoded
    assert '"policy_version":""' in encoded


def test_extract_marker_normalizes_unknown_purpose_to_utility_custom():
    body = {
        "messages": [
            {
                "role": "user",
                "content": '<<CC_DUMP_SIDE_CHANNEL:{"run_id":"abc","purpose":"unknown_x","source_session_id":"s1"}>>\nhello',
            }
        ]
    }
    parsed = extract_marker(body)
    assert parsed is not None
    assert parsed.purpose == "utility_custom"


def test_extract_marker_reads_policy_version():
    body = {
        "messages": [
            {
                "role": "user",
                "content": (
                    '<<CC_DUMP_SIDE_CHANNEL:{"run_id":"abc","purpose":"block_summary",'
                    '"source_session_id":"s1","prompt_version":"v1",'
                    '"policy_version":"redaction-v1"}>>\nhello'
                ),
            }
        ]
    }
    parsed = extract_marker(body)
    assert parsed is not None
    assert parsed.policy_version == "redaction-v1"
