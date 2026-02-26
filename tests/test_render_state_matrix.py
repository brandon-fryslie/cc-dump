"""Behavioral state-matrix tests for block rendering.

Verifies that high-impact blocks produce distinct output across SC/SE/FC/FE.
"""

from io import StringIO

from rich.console import Console
from textual.theme import BUILTIN_THEMES

from cc_dump.core.formatting import (
    Category,
    ConfigContentBlock,
    ErrorBlock,
    HeaderBlock,
    HookOutputBlock,
    HttpHeadersBlock,
    ImageBlock,
    MessageBlock,
    MetadataBlock,
    MetadataSection,
    NewlineBlock,
    NewSessionBlock,
    ResponseMetadataSection,
    SeparatorBlock,
    SkillDefChild,
    StopReasonBlock,
    StreamInfoBlock,
    StreamToolUseBlock,
    SystemSection,
    TextContentBlock,
    TextDeltaBlock,
    ThinkingBlock,
    ToolDefBlock,
    TurnBudgetBlock,
    ToolDefsSection,
    ToolResultBlock,
    ToolUseSummaryBlock,
    ToolUseBlock,
    TrackedContentBlock,
    UnknownTypeBlock,
    ProxyErrorBlock,
    AgentDefChild,
    VisState,
)
from cc_dump.core.analysis import TurnBudget
from cc_dump.tui.rendering import (
    BLOCK_RENDERERS,
    BLOCK_STATE_RENDERERS,
    RENDERERS,
    TRUNCATION_LIMITS,
    render_turn_to_strips,
    set_theme,
)


SUMMARY_COLLAPSED = VisState(True, False, False)
SUMMARY_EXPANDED = VisState(True, False, True)
FULL_COLLAPSED = VisState(True, True, False)
FULL_EXPANDED = VisState(True, True, True)


def _render_plain(block, category: str, vis: VisState, width: int = 120) -> tuple[str, int]:
    console = Console(width=width, force_terminal=True)
    strips, _, _ = render_turn_to_strips([block], {category: vis}, console, width=width)
    lines = ["".join(seg.text for seg in strip._segments) for strip in strips]
    return "\n".join(lines), len(lines)


def _renderable_plain(renderable) -> str:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    console.print(renderable)
    return buf.getvalue()


def setup_module() -> None:
    set_theme(BUILTIN_THEMES["textual-dark"])


def test_truncation_limits_match_visibility_policy():
    assert TRUNCATION_LIMITS[VisState(False, False, False)] == 0
    assert TRUNCATION_LIMITS[VisState(False, False, True)] == 0
    assert TRUNCATION_LIMITS[VisState(False, True, False)] == 0
    assert TRUNCATION_LIMITS[VisState(False, True, True)] == 0
    assert TRUNCATION_LIMITS[SUMMARY_COLLAPSED] == 3
    assert TRUNCATION_LIMITS[SUMMARY_EXPANDED] == 8
    assert TRUNCATION_LIMITS[FULL_COLLAPSED] == 5
    assert TRUNCATION_LIMITS[FULL_EXPANDED] is None


def test_content_block_renderer_registry_has_four_distinct_visible_states():
    content_block_types = [
        "TextContentBlock",
        "TextDeltaBlock",
        "ToolUseBlock",
        "ToolResultBlock",
        "ToolUseSummaryBlock",
        "ToolDefBlock",
        "SkillDefChild",
        "AgentDefChild",
        "TrackedContentBlock",
        "ThinkingBlock",
        "ConfigContentBlock",
        "HookOutputBlock",
        "MetadataBlock",
        "HttpHeadersBlock",
        "TurnBudgetBlock",
        "ErrorBlock",
        "ProxyErrorBlock",
        "ImageBlock",
        "StreamInfoBlock",
        "StreamToolUseBlock",
        "StopReasonBlock",
    ]
    visible_states = [
        SUMMARY_COLLAPSED,
        SUMMARY_EXPANDED,
        FULL_COLLAPSED,
        FULL_EXPANDED,
    ]

    for type_name in content_block_types:
        base = BLOCK_RENDERERS[type_name]
        names = []
        for vis in visible_states:
            key = (type_name, vis.visible, vis.full, vis.expanded)
            names.append(BLOCK_STATE_RENDERERS.get(key, base).__name__)
        assert len(set(names)) == 4, f"{type_name} should map SC/SE/FC/FE to distinct renderers: {names}"


def test_all_block_types_have_four_distinct_visible_state_renderers():
    visible_states = [
        SUMMARY_COLLAPSED,
        SUMMARY_EXPANDED,
        FULL_COLLAPSED,
        FULL_EXPANDED,
    ]

    for type_name, base in BLOCK_RENDERERS.items():
        names = []
        for vis in visible_states:
            key = (type_name, vis.visible, vis.full, vis.expanded)
            names.append(BLOCK_STATE_RENDERERS.get(key, base).__name__)
        assert len(set(names)) == 4, f"{type_name} should map SC/SE/FC/FE to distinct renderers: {names}"


def test_core_content_blocks_respect_state_line_budgets():
    cases = [
        (
            "TextContentBlock",
            TextContentBlock(
                content="\n".join(f"line {i}" for i in range(1, 60)),
                category=Category.ASSISTANT,
            ),
            "assistant",
        ),
        (
            "ToolUseBlock",
            ToolUseBlock(
                name="Bash",
                input_size=20,
                msg_color_idx=0,
                detail="git status",
                description="Run shell commands in a controlled environment.",
                tool_input={"command": "git status\npwd\nls -la\nwhoami\nenv"},
            ),
            "tools",
        ),
        (
            "ToolResultBlock",
            ToolResultBlock(
                size=30,
                tool_name="Read",
                msg_color_idx=0,
                content="\n".join(f"res {i}" for i in range(1, 60)),
            ),
            "tools",
        ),
        (
            "TrackedContentBlock",
            TrackedContentBlock(
                status="changed",
                tag_id="sp-1",
                content="\n".join(f"tracked {i}" for i in range(1, 60)),
                old_content="\n".join(f"old {i}" for i in range(1, 60)),
                new_content="\n".join(f"new {i}" for i in range(1, 60)),
            ),
            "system",
        ),
        (
            "ThinkingBlock",
            ThinkingBlock(content="\n".join(f"thought {i}" for i in range(1, 60))),
            "thinking",
        ),
        (
            "ConfigContentBlock",
            ConfigContentBlock(
                source="CLAUDE.md",
                content="\n".join(f"cfg {i}" for i in range(1, 60)),
                category=Category.USER,
            ),
            "user",
        ),
        (
            "HookOutputBlock",
            HookOutputBlock(
                hook_name="system-reminder",
                content="\n".join(f"hook {i}" for i in range(1, 60)),
                category=Category.USER,
            ),
            "user",
        ),
        (
            "TextDeltaBlock",
            TextDeltaBlock(
                content="\n".join(f"delta {i}" for i in range(1, 60)),
                category=Category.ASSISTANT,
            ),
            "assistant",
        ),
        (
            "ToolUseSummaryBlock",
            ToolUseSummaryBlock(
                tool_counts={f"Tool{i}": i for i in range(1, 12)},
                total=sum(range(1, 12)),
            ),
            "tools",
        ),
    ]

    for name, block, category in cases:
        _, sc_lines = _render_plain(block, category, SUMMARY_COLLAPSED, width=180)
        _, se_lines = _render_plain(block, category, SUMMARY_EXPANDED, width=180)
        _, fc_lines = _render_plain(block, category, FULL_COLLAPSED, width=180)
        assert sc_lines <= 3, f"{name} summary-collapsed should be <=3 lines, got {sc_lines}"
        assert se_lines <= 8, f"{name} summary-expanded should be <=8 lines, got {se_lines}"
        assert fc_lines <= 5, f"{name} full-collapsed should be <=5 lines, got {fc_lines}"


def test_auxiliary_content_blocks_respect_state_line_budgets():
    cases = [
        (
            "MetadataBlock",
            MetadataBlock(
                model="claude-sonnet",
                max_tokens="8192",
                stream=True,
                tool_count=4,
                user_hash="abcdef123456",
                account_id="112233445566",
                session_id="998877665544",
            ),
            "metadata",
        ),
        (
            "HttpHeadersBlock",
            HttpHeadersBlock(
                headers={f"x-header-{i}": f"value-{i}" for i in range(1, 20)},
                header_type="response",
                status_code=200,
            ),
            "metadata",
        ),
        (
            "TurnBudgetBlock",
            TurnBudgetBlock(
                budget=TurnBudget(
                    total_est=120000,
                    system_tokens_est=20000,
                    tool_defs_tokens_est=15000,
                    user_text_tokens_est=28000,
                    assistant_text_tokens_est=22000,
                    tool_use_tokens_est=18000,
                    tool_result_tokens_est=17000,
                    actual_input_tokens=1200,
                    actual_cache_read_tokens=800,
                ),
                tool_result_by_name={"Read": 3000, "Bash": 2200, "Grep": 1400},
            ),
            "metadata",
        ),
        (
            "ToolUseSummaryBlock",
            ToolUseSummaryBlock(
                tool_counts={f"Tool{i}": i for i in range(1, 12)},
                total=sum(range(1, 12)),
            ),
            "tools",
        ),
        (
            "ToolDefBlock",
            ToolDefBlock(
                name="Read",
                token_estimate=500,
                description="Read file contents from disk with optional offset and limit.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["file_path"],
                },
            ),
            "tools",
        ),
        (
            "SkillDefChild",
            SkillDefChild(
                name="review-pr",
                description="Review pull requests and identify regressions.",
                plugin_source="do",
            ),
            "tools",
        ),
        (
            "AgentDefChild",
            AgentDefChild(
                name="researcher",
                description="Gather context and synthesize technical findings.",
                available_tools="All tools",
            ),
            "tools",
        ),
        (
            "ErrorBlock",
            ErrorBlock(code=429, reason="rate_limit", category=Category.METADATA),
            "metadata",
        ),
        (
            "ProxyErrorBlock",
            ProxyErrorBlock(error="timeout", category=Category.METADATA),
            "metadata",
        ),
        (
            "ImageBlock",
            ImageBlock(media_type="image/png", category=Category.USER),
            "user",
        ),
        (
            "StreamInfoBlock",
            StreamInfoBlock(model="claude-sonnet-4-5-20250929"),
            "metadata",
        ),
        (
            "StreamToolUseBlock",
            StreamToolUseBlock(name="Read"),
            "tools",
        ),
        (
            "StopReasonBlock",
            StopReasonBlock(reason="end_turn"),
            "metadata",
        ),
    ]

    for name, block, category in cases:
        _, sc_lines = _render_plain(block, category, SUMMARY_COLLAPSED, width=180)
        _, se_lines = _render_plain(block, category, SUMMARY_EXPANDED, width=180)
        _, fc_lines = _render_plain(block, category, FULL_COLLAPSED, width=180)
        assert sc_lines <= 3, f"{name} summary-collapsed should be <=3 lines, got {sc_lines}"
        assert se_lines <= 8, f"{name} summary-expanded should be <=8 lines, got {se_lines}"
        assert fc_lines <= 5, f"{name} full-collapsed should be <=5 lines, got {fc_lines}"


def test_container_blocks_keep_summary_views_bounded():
    metadata_section = MetadataSection(
        children=[
            MetadataBlock(
                model="claude-sonnet",
                max_tokens="8192",
                stream=True,
                tool_count=4,
                user_hash="abcdef123456",
                account_id="112233445566",
                session_id="998877665544",
            ),
            HttpHeadersBlock(
                headers={f"x-header-{i}": f"value-{i}" for i in range(1, 20)},
                header_type="response",
                status_code=200,
            ),
            TurnBudgetBlock(
                budget=TurnBudget(
                    total_est=120000,
                    system_tokens_est=20000,
                    tool_defs_tokens_est=15000,
                    user_text_tokens_est=28000,
                    assistant_text_tokens_est=22000,
                    tool_use_tokens_est=18000,
                    tool_result_tokens_est=17000,
                    actual_input_tokens=1200,
                    actual_cache_read_tokens=800,
                ),
                tool_result_by_name={"Read": 3000, "Bash": 2200, "Grep": 1400},
            ),
        ]
    )
    system_section = SystemSection(
        children=[
            TrackedContentBlock(status="new", tag_id="sp-1", content="\n".join(f"n{i}" for i in range(40))),
            TrackedContentBlock(
                status="changed",
                tag_id="sp-2",
                content="\n".join(f"c{i}" for i in range(40)),
                old_content="\n".join(f"old{i}" for i in range(40)),
                new_content="\n".join(f"new{i}" for i in range(40)),
            ),
            TrackedContentBlock(status="ref", tag_id="sp-3", content="same"),
        ]
    )
    tool_defs_section = ToolDefsSection(
        tool_count=8,
        total_tokens=6400,
        children=[
            ToolDefBlock(
                name=f"Tool{i}",
                token_estimate=800,
                description="tool description",
                input_schema={
                    "type": "object",
                    "properties": {f"p{j}": {"type": "string"} for j in range(6)},
                    "required": ["p0", "p1"],
                },
            )
            for i in range(8)
        ],
    )
    response_metadata = ResponseMetadataSection(
        children=[
            HeaderBlock(label="RESPONSE", header_type="response"),
            HttpHeadersBlock(
                headers={f"h{i}": f"v{i}" for i in range(1, 12)},
                header_type="response",
                status_code=204,
            ),
            StreamInfoBlock(model="claude-sonnet-4-5-20250929"),
        ]
    )
    message = MessageBlock(
        role="assistant",
        msg_index=9,
        timestamp="11:00:00",
        category=Category.ASSISTANT,
        agent_label="planner",
        agent_kind="subagent",
        children=[
            TextContentBlock(content="\n".join(f"line {i}" for i in range(60)), category=Category.ASSISTANT),
            ToolUseBlock(
                name="Bash",
                input_size=20,
                msg_color_idx=0,
                detail="git status",
                tool_input={"command": "git status\npwd\nls -la"},
            ),
            ToolResultBlock(
                size=20,
                tool_name="Bash",
                msg_color_idx=0,
                content="\n".join(f"out {i}" for i in range(20)),
            ),
        ],
    )

    cases = [
        ("MetadataSection", metadata_section, "metadata"),
        ("SystemSection", system_section, "system"),
        ("ToolDefsSection", tool_defs_section, "tools"),
        ("ResponseMetadataSection", response_metadata, "metadata"),
        ("MessageBlock", message, "assistant"),
    ]

    for name, block, category in cases:
        _, sc_lines = _render_plain(block, category, SUMMARY_COLLAPSED, width=180)
        _, se_lines = _render_plain(block, category, SUMMARY_EXPANDED, width=180)
        _, fc_lines = _render_plain(block, category, FULL_COLLAPSED, width=180)
        assert sc_lines <= 3, f"{name} summary-collapsed should be <=3 lines, got {sc_lines}"
        assert se_lines <= 8, f"{name} summary-expanded should be <=8 lines, got {se_lines}"
        assert fc_lines <= 5, f"{name} full-collapsed should be <=5 lines, got {fc_lines}"


def test_message_and_section_summary_expanded_hide_child_content():
    unique_text = "CHILD_UNIQUE_MARKER_123"
    message = MessageBlock(
        role="assistant",
        msg_index=4,
        timestamp="10:30:00",
        category=Category.ASSISTANT,
        children=[
            TextContentBlock(
                content=f"header line\n{unique_text}\nfooter line",
                category=Category.ASSISTANT,
            ),
            ToolUseBlock(
                name="Bash",
                input_size=3,
                msg_color_idx=0,
                tool_input={"command": f"echo {unique_text}"},
            ),
        ],
    )
    msg_se, _ = _render_plain(message, "assistant", SUMMARY_EXPANDED, width=180)
    msg_fe, _ = _render_plain(message, "assistant", FULL_EXPANDED, width=180)
    assert unique_text not in msg_se
    assert unique_text in msg_fe

    metadata_section = MetadataSection(
        children=[
            MetadataBlock(
                model=unique_text,
                max_tokens="4096",
                stream=True,
            ),
            HttpHeadersBlock(
                headers={"x-marker": unique_text},
                header_type="response",
                status_code=200,
            ),
        ]
    )
    sec_se, _ = _render_plain(metadata_section, "metadata", SUMMARY_EXPANDED, width=180)
    sec_fe, _ = _render_plain(metadata_section, "metadata", FULL_EXPANDED, width=180)
    assert unique_text not in sec_se
    assert unique_text in sec_fe


def test_container_full_collapsed_hides_child_content():
    unique_text = "FULL_CHILD_MARKER_456"
    message = MessageBlock(
        role="assistant",
        msg_index=5,
        timestamp="10:31:00",
        category=Category.ASSISTANT,
        children=[
            TextContentBlock(
                content=f"line one\n{unique_text}\nline three",
                category=Category.ASSISTANT,
            ),
            ToolResultBlock(
                size=3,
                tool_name="Read",
                msg_color_idx=0,
                content=unique_text,
            ),
        ],
    )
    msg_fc, _ = _render_plain(message, "assistant", FULL_COLLAPSED, width=180)
    msg_fe, _ = _render_plain(message, "assistant", FULL_EXPANDED, width=180)
    assert unique_text not in msg_fc
    assert unique_text in msg_fe

    system_section = SystemSection(
        children=[
            TrackedContentBlock(
                status="new",
                tag_id="sp-9",
                content=f"intro\n{unique_text}\noutro",
            )
        ]
    )
    sys_fc, _ = _render_plain(system_section, "system", FULL_COLLAPSED, width=180)
    sys_fe, _ = _render_plain(system_section, "system", FULL_EXPANDED, width=180)
    assert unique_text not in sys_fc
    assert unique_text in sys_fe


def test_text_content_state_matrix_is_distinct():
    code_lines = "\n".join(f"line {i}" for i in range(1, 31))
    content = f"```text\n{code_lines}\n```"
    block = TextContentBlock(content=content, category=Category.ASSISTANT)

    sc_text, sc_lines = _render_plain(block, "assistant", SUMMARY_COLLAPSED)
    se_text, se_lines = _render_plain(block, "assistant", SUMMARY_EXPANDED)
    fc_text, fc_lines = _render_plain(block, "assistant", FULL_COLLAPSED)
    fe_text, fe_lines = _render_plain(block, "assistant", FULL_EXPANDED)

    assert "(32 lines)" in sc_text
    assert "more lines" in se_text
    assert "[snippet]" in fc_text
    assert "line 7" not in fc_text
    assert "line 7" in fe_text
    assert sc_text != fc_text
    assert se_text != fe_text
    assert fc_text != fe_text
    assert fc_lines < fe_lines
    assert se_lines < fe_lines


def test_tool_use_state_matrix_is_distinct():
    block = ToolUseBlock(
        name="Bash",
        input_size=8,
        msg_color_idx=0,
        detail="git status",
        description="Run shell commands in a controlled environment.",
        tool_input={"command": "git status\npwd\nls -la"},
    )

    sc_text, _ = _render_plain(block, "tools", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "tools", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "tools", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "tools", FULL_EXPANDED)

    assert "[Use: Bash]" in sc_text
    assert "lines" not in sc_text
    assert "git status" in se_text
    assert "lines" in se_text
    assert "$ git status" in fc_text
    assert "pwd" not in fc_text
    assert "Run shell commands" in fe_text
    assert sc_text != fc_text
    assert se_text != fe_text


def test_tool_result_state_matrix_is_distinct():
    content = "\n".join(f"result line {i}" for i in range(1, 20))
    block = ToolResultBlock(
        size=19,
        tool_name="Read",
        detail="/tmp/example.py",
        msg_color_idx=0,
        content=content,
        tool_input={"file_path": "/tmp/example.py"},
    )

    sc_text, _ = _render_plain(block, "tools", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "tools", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "tools", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "tools", FULL_EXPANDED)

    assert "[Result]" in sc_text
    assert "Read" in se_text
    assert "result line 1" in se_text
    assert "Read" in fc_text
    assert "result line 10" not in fc_text
    assert "result line 10" in fe_text
    assert sc_text != fc_text
    assert se_text != fe_text


def test_http_headers_state_matrix_is_distinct():
    headers = {f"x-header-{i}": f"value-{i}" for i in range(1, 12)}
    block = HttpHeadersBlock(headers=headers, header_type="response", status_code=200)

    sc_text, _ = _render_plain(block, "metadata", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "metadata", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "metadata", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "metadata", FULL_EXPANDED)

    assert "11 headers" in sc_text
    assert "more headers" in se_text
    assert "[snippet]" in fc_text
    assert "x-header-11" not in fc_text
    assert "x-header-11" in fe_text
    assert sc_text != se_text
    assert fc_text != fe_text


def test_header_summary_collapsed_omits_timestamp():
    block = HeaderBlock(
        header_type="request",
        label="REQUEST 7",
        timestamp="2026-02-22 10:45:00",
    )

    sc_text, _ = _render_plain(block, "metadata", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "metadata", SUMMARY_EXPANDED)

    assert "REQUEST 7" in sc_text
    assert "10:45:00" not in sc_text
    assert "10:45:00" in se_text
    assert sc_text != se_text


def test_header_full_collapsed_and_expanded_are_distinct():
    block = HeaderBlock(
        header_type="request",
        label="REQUEST 7",
        request_num=7,
        timestamp="2026-02-22 10:45:00",
    )
    fc_text, _ = _render_plain(block, "metadata", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "metadata", FULL_EXPANDED)
    assert "REQUEST 7" in fc_text
    assert "type: request" in fe_text
    assert "request: 7" in fe_text
    assert fc_text != fe_text


def test_structural_markers_state_matrix_are_distinct():
    separator = SeparatorBlock(style="heavy", category=Category.METADATA)
    sep_sc, _ = _render_plain(separator, "metadata", SUMMARY_COLLAPSED)
    sep_se, _ = _render_plain(separator, "metadata", SUMMARY_EXPANDED)
    sep_fc, _ = _render_plain(separator, "metadata", FULL_COLLAPSED)
    sep_fe, _ = _render_plain(separator, "metadata", FULL_EXPANDED)
    assert sep_sc.count("─") < sep_se.count("─")
    assert sep_se.count("─") < sep_fc.count("─")
    assert sep_fc.count("─") < sep_fe.count("─")
    assert sep_sc != sep_fe

    session_id = "session-alpha-1234567890"
    new_session = NewSessionBlock(session_id=session_id, category=Category.METADATA)
    ns_sc, _ = _render_plain(new_session, "metadata", SUMMARY_COLLAPSED)
    ns_se, _ = _render_plain(new_session, "metadata", SUMMARY_EXPANDED)
    ns_fc, _ = _render_plain(new_session, "metadata", FULL_COLLAPSED)
    ns_fe, _ = _render_plain(new_session, "metadata", FULL_EXPANDED)
    assert "NEW SESSION" in ns_sc
    assert "═" not in ns_sc
    assert session_id[:16] in ns_se
    assert session_id not in ns_se
    assert "═" in ns_fc
    assert session_id[:16] in ns_fc
    assert session_id in ns_fe
    assert ns_sc != ns_se
    assert ns_fc != ns_fe

    unknown = UnknownTypeBlock(block_type="custom-widget", category=Category.USER)
    uk_sc, _ = _render_plain(unknown, "user", SUMMARY_COLLAPSED)
    uk_se, _ = _render_plain(unknown, "user", SUMMARY_EXPANDED)
    uk_fc, _ = _render_plain(unknown, "user", FULL_COLLAPSED)
    uk_fe, _ = _render_plain(unknown, "user", FULL_EXPANDED)
    assert "[unknown block]" in uk_sc
    assert "custom-widget" not in uk_sc
    assert "custom-widget" in uk_se
    assert "unsupported content type" in uk_se
    assert "[custom-widget]" in uk_fc
    assert "no renderer registered" in uk_fe
    assert uk_sc != uk_se
    assert uk_fc != uk_fe


def test_newline_summary_collapsed_is_suppressed():
    block = NewlineBlock(category=Category.METADATA)

    sc_text, sc_lines = _render_plain(block, "metadata", SUMMARY_COLLAPSED)
    se_text, se_lines = _render_plain(block, "metadata", SUMMARY_EXPANDED)
    fc_text, fc_lines = _render_plain(block, "metadata", FULL_COLLAPSED)
    fe_text, fe_lines = _render_plain(block, "metadata", FULL_EXPANDED)

    assert sc_lines == 0
    assert sc_text == ""
    assert se_lines == 1
    assert fc_lines == 1
    assert fe_lines == 1
    assert se_text != fc_text
    assert fc_text != fe_text


def test_metadata_summary_states_are_distinct():
    block = MetadataBlock(
        model="claude-sonnet",
        max_tokens="8192",
        stream=True,
        tool_count=4,
        user_hash="abcdef123456",
        account_id="112233445566",
        session_id="998877665544",
    )

    sc_text, _ = _render_plain(block, "metadata", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "metadata", SUMMARY_EXPANDED)
    fe_text, _ = _render_plain(block, "metadata", FULL_EXPANDED)

    assert "model:" in sc_text
    assert "max_tokens" not in sc_text
    assert "max_tokens" in se_text
    assert "user:" in se_text
    assert "user_hash=abcdef123456" in fe_text
    assert "account_id=112233445566" in fe_text
    assert "session_id=998877665544" in fe_text
    assert "user_hash=abcdef123456" not in se_text
    assert sc_text != se_text
    assert se_text != fe_text


def test_tool_use_summary_block_state_matrix_is_distinct():
    block = ToolUseSummaryBlock(
        tool_counts={"Bash": 4, "Read": 2, "Grep": 1, "Glob": 1},
        total=8,
    )

    sc_text, _ = _render_plain(block, "tools", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "tools", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "tools", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "tools", FULL_EXPANDED)

    assert "used 8 tools" in sc_text
    assert "top: Bash 4x" in sc_text
    assert "(+1 more)" in se_text
    assert "- Bash: 4x" in fc_text
    assert "(50%)" in fe_text
    assert sc_text != se_text
    assert fc_text != fe_text


def test_message_block_state_matrix_is_distinct():
    block = MessageBlock(
        role="user",
        msg_index=2,
        timestamp="10:45:00",
        category=Category.USER,
        agent_label="planner",
        agent_kind="subagent",
        children=[
            TextContentBlock(content="hello", category=Category.USER),
            ToolUseBlock(name="Read", input_size=3, msg_color_idx=0),
            ToolResultBlock(size=1, tool_name="Read", msg_color_idx=0, content="ok"),
        ],
    )

    sc_text, _ = _render_plain(block, "user", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "user", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "user", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "user", FULL_EXPANDED)

    assert "USER [2]" in sc_text
    assert "10:45:00" not in sc_text
    assert "10:45:00" in se_text
    assert "planner" in se_text
    assert "summary blocks: 3" in se_text
    assert "blocks: 3" in fc_text
    assert "summary blocks: 3" not in fc_text
    assert "tools:2" in fc_text
    assert "blocks: 3" not in fe_text
    assert sc_text != se_text
    assert fc_text != fe_text


def test_section_headers_summary_expanded_are_enriched():
    metadata_section = MetadataSection(
        children=[
            MetadataBlock(model="claude", max_tokens="1000"),
            HttpHeadersBlock(headers={"content-type": "application/json"}),
            TurnBudgetBlock(budget=TurnBudget(total_est=1000)),
        ]
    )
    md_sc_text, _ = _render_plain(metadata_section, "metadata", SUMMARY_COLLAPSED)
    md_se_text, _ = _render_plain(metadata_section, "metadata", SUMMARY_EXPANDED)
    assert "METADATA" in md_sc_text
    assert "(3 blocks)" not in md_sc_text
    assert "(3 blocks)" in md_se_text

    system_section = SystemSection(
        children=[
            TrackedContentBlock(status="new", content="a"),
            TrackedContentBlock(status="changed", content="b"),
            TrackedContentBlock(status="ref", content="c"),
        ]
    )
    sys_sc_text, _ = _render_plain(system_section, "system", SUMMARY_COLLAPSED)
    sys_se_text, _ = _render_plain(system_section, "system", SUMMARY_EXPANDED)
    assert "SYSTEM" in sys_sc_text
    assert "status new:1 changed:1 ref:1" in sys_se_text

    tool_defs = ToolDefsSection(tool_count=5, total_tokens=4200, children=[])
    td_sc_text, _ = _render_plain(tool_defs, "tools", SUMMARY_COLLAPSED)
    td_se_text, _ = _render_plain(tool_defs, "tools", SUMMARY_EXPANDED)
    assert "5 tools" in td_sc_text
    assert "tokens" not in td_sc_text
    assert "tokens" in td_se_text

    response_metadata = ResponseMetadataSection(
        children=[
            HeaderBlock(label="RESPONSE", header_type="response"),
            HttpHeadersBlock(headers={"server": "x"}, header_type="response", status_code=201),
            StreamInfoBlock(model="claude-sonnet"),
        ]
    )
    rm_sc_text, _ = _render_plain(response_metadata, "metadata", SUMMARY_COLLAPSED)
    rm_se_text, _ = _render_plain(response_metadata, "metadata", SUMMARY_EXPANDED)
    assert "RESPONSE METADATA" in rm_sc_text
    assert "HTTP 201" in rm_se_text
    assert "(3 blocks)" in rm_se_text


def test_stream_info_stop_reason_and_stream_tool_summary_states_are_distinct():
    info = StreamInfoBlock(model="claude-sonnet-4-5-20250929")
    info_sc_text, _ = _render_plain(info, "metadata", SUMMARY_COLLAPSED)
    info_se_text, _ = _render_plain(info, "metadata", SUMMARY_EXPANDED)
    info_fe_text, _ = _render_plain(info, "metadata", FULL_EXPANDED)
    assert "model:" in info_sc_text
    assert "claude-sonnet-4-5-20250929" not in info_sc_text
    assert "claude-sonnet-4-5-20250929" in info_se_text
    assert "stream metadata" in info_se_text
    assert info_se_text != info_fe_text

    stop = StopReasonBlock(reason="end_turn")
    stop_sc_text, _ = _render_plain(stop, "metadata", SUMMARY_COLLAPSED)
    stop_se_text, _ = _render_plain(stop, "metadata", SUMMARY_EXPANDED)
    stop_fc_text, _ = _render_plain(stop, "metadata", FULL_COLLAPSED)
    stop_fe_text, _ = _render_plain(stop, "metadata", FULL_EXPANDED)
    assert "stop: end_turn" in stop_sc_text
    assert "assistant completed turn" in stop_se_text
    assert "stop: end_turn" not in stop_fc_text
    assert "stop" in stop_fc_text
    assert "assistant completed turn" not in stop_fe_text
    assert stop_se_text != stop_sc_text
    assert stop_fc_text != stop_fe_text
    assert stop_se_text != stop_fe_text

    stream_use = StreamToolUseBlock(name="Read")
    su_sc_text, _ = _render_plain(stream_use, "tools", SUMMARY_COLLAPSED)
    su_se_text, _ = _render_plain(stream_use, "tools", SUMMARY_EXPANDED)
    su_fc_text, _ = _render_plain(stream_use, "tools", FULL_COLLAPSED)
    su_fe_text, _ = _render_plain(stream_use, "tools", FULL_EXPANDED)
    assert "[tool_use] Read" in su_sc_text
    assert "pending tool_result" in su_se_text
    assert "[tool_use] Read" not in su_fc_text
    assert "[tool_use]" in su_fc_text
    assert "pending tool_result" not in su_fe_text
    assert su_sc_text != su_se_text
    assert su_fc_text != su_fe_text
    assert su_se_text != su_fe_text

    info_fc_text, _ = _render_plain(info, "metadata", FULL_COLLAPSED)
    assert "claude-sonnet-4-5-20250929" not in info_fc_text
    assert info_fc_text != info_fe_text


def test_error_and_proxy_error_state_matrix_are_distinct():
    err = ErrorBlock(code=429, reason="rate_limit", category=Category.METADATA)
    err_sc, _ = _render_plain(err, "metadata", SUMMARY_COLLAPSED)
    err_se, _ = _render_plain(err, "metadata", SUMMARY_EXPANDED)
    err_fc, _ = _render_plain(err, "metadata", FULL_COLLAPSED)
    err_fe, _ = _render_plain(err, "metadata", FULL_EXPANDED)
    assert "[HTTP 429]" in err_sc
    assert "rate_limit" not in err_sc
    assert "rate_limit" in err_se
    assert "request failed" in err_se
    assert "[failed]" in err_fc
    assert "[failed]" not in err_fe
    assert err_sc != err_se
    assert err_fc != err_fe

    proxy = ProxyErrorBlock(error="timeout", category=Category.METADATA)
    px_sc, _ = _render_plain(proxy, "metadata", SUMMARY_COLLAPSED)
    px_se, _ = _render_plain(proxy, "metadata", SUMMARY_EXPANDED)
    px_fc, _ = _render_plain(proxy, "metadata", FULL_COLLAPSED)
    px_fe, _ = _render_plain(proxy, "metadata", FULL_EXPANDED)
    assert "[PROXY ERROR]" in px_sc
    assert "timeout" not in px_sc
    assert "timeout" in px_se
    assert "upstream transport failed" in px_se
    assert "[failed]" in px_fc
    assert "[failed]" not in px_fe
    assert px_sc != px_se
    assert px_fc != px_fe


def test_image_summary_states_are_distinct_from_full():
    block = ImageBlock(media_type="image/png", category=Category.USER)
    sc_text, _ = _render_plain(block, "user", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "user", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "user", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "user", FULL_EXPANDED)

    assert "[image]" in sc_text
    assert "image/png" not in sc_text
    assert "image/png" in se_text
    assert "image/png" not in fc_text
    assert "binary payload hidden" in se_text
    assert "binary payload hidden" not in fe_text
    assert sc_text != se_text
    assert fc_text != fe_text
    assert se_text != fe_text


def test_section_full_collapsed_and_expanded_renderers_are_distinct():
    metadata_section = MetadataSection(
        children=[
            MetadataBlock(model="claude", max_tokens="1000"),
            HttpHeadersBlock(headers={"content-type": "application/json"}),
            TurnBudgetBlock(budget=TurnBudget(total_est=1000)),
        ]
    )
    md_fc = RENDERERS[("MetadataSection", True, True, False)](metadata_section)
    md_fe = RENDERERS[("MetadataSection", True, True, True)](metadata_section)
    assert md_fc is not None
    assert md_fe is not None
    md_fc_plain = _renderable_plain(md_fc)
    md_fe_plain = _renderable_plain(md_fe)
    assert "(3 blocks)" in md_fc_plain
    assert "Metadata" in md_fe_plain
    assert md_fc_plain != md_fe_plain

    system_section = SystemSection(
        children=[
            TrackedContentBlock(status="new", content="a"),
            TrackedContentBlock(status="changed", content="b"),
        ]
    )
    sys_fc = RENDERERS[("SystemSection", True, True, False)](system_section)
    sys_fe = RENDERERS[("SystemSection", True, True, True)](system_section)
    assert sys_fc is not None
    assert sys_fe is not None
    sys_fc_plain = _renderable_plain(sys_fc)
    sys_fe_plain = _renderable_plain(sys_fe)
    assert "(2 blocks)" in sys_fc_plain
    assert "status" in sys_fe_plain
    assert sys_fc_plain != sys_fe_plain

    tool_defs = ToolDefsSection(
        tool_count=3,
        total_tokens=4200,
        children=[
            ToolDefBlock(name="Bash"),
            ToolDefBlock(name="Read"),
            ToolDefBlock(name="Write"),
        ],
    )
    td_fc = RENDERERS[("ToolDefsSection", True, True, False)](tool_defs)
    td_fe = RENDERERS[("ToolDefsSection", True, True, True)](tool_defs)
    assert td_fc is not None
    assert td_fe is not None
    td_fc_plain = _renderable_plain(td_fc)
    td_fe_plain = _renderable_plain(td_fe)
    assert "tokens" in td_fc_plain
    assert "avg:" in td_fc_plain
    assert "Bash" in td_fe_plain
    assert td_fc_plain != td_fe_plain

    response_metadata = ResponseMetadataSection(
        children=[
            HeaderBlock(label="RESPONSE", header_type="response"),
            HttpHeadersBlock(headers={"server": "x"}, header_type="response", status_code=204),
            StreamInfoBlock(model="claude-sonnet"),
        ]
    )
    rm_fc = RENDERERS[("ResponseMetadataSection", True, True, False)](response_metadata)
    rm_fe = RENDERERS[("ResponseMetadataSection", True, True, True)](response_metadata)
    assert rm_fc is not None
    assert rm_fe is not None
    rm_fc_plain = _renderable_plain(rm_fc)
    rm_fe_plain = _renderable_plain(rm_fe)
    assert "(3 blocks)" in rm_fc_plain
    assert "HTTP 204" in rm_fe_plain
    assert rm_fc_plain != rm_fe_plain


def test_section_summary_expanded_and_full_expanded_are_distinct():
    metadata_section = MetadataSection(
        children=[
            MetadataBlock(model="claude", max_tokens="1000"),
            HttpHeadersBlock(headers={"content-type": "application/json"}),
            TurnBudgetBlock(budget=TurnBudget(total_est=1000)),
        ]
    )
    md_se, _ = _render_plain(metadata_section, "metadata", SUMMARY_EXPANDED)
    md_fe, _ = _render_plain(metadata_section, "metadata", FULL_EXPANDED)
    assert "METADATA" in md_se
    assert "METADATA" in md_fe
    assert "types:" not in md_se
    assert "types:" in md_fe
    assert md_se != md_fe

    system_section = SystemSection(
        children=[
            TrackedContentBlock(status="new", tag_id="sp-1", content="a"),
            TrackedContentBlock(status="changed", tag_id="sp-2", content="b"),
            TrackedContentBlock(status="ref", tag_id="sp-3", content="c"),
        ]
    )
    sys_se, _ = _render_plain(system_section, "system", SUMMARY_EXPANDED)
    sys_fe, _ = _render_plain(system_section, "system", FULL_EXPANDED)
    assert "status new:1 changed:1 ref:1" in sys_se
    assert "tags sp-1, sp-2, sp-3" in sys_fe
    assert sys_se != sys_fe

    response_metadata = ResponseMetadataSection(
        children=[
            HeaderBlock(label="RESPONSE", header_type="response"),
            HttpHeadersBlock(
                headers={"server": "x", "content-type": "application/json"},
                header_type="response",
                status_code=204,
            ),
            StreamInfoBlock(model="claude-sonnet"),
        ]
    )
    rm_se, _ = _render_plain(response_metadata, "metadata", SUMMARY_EXPANDED)
    rm_fe, _ = _render_plain(response_metadata, "metadata", FULL_EXPANDED)
    assert "HTTP 204" in rm_se
    assert "model: claude-sonnet" in rm_fe
    assert "headers: 2" in rm_fe
    assert rm_se != rm_fe


def test_tool_def_block_state_matrix_is_distinct():
    block = ToolDefBlock(
        name="Read",
        token_estimate=500,
        description="Read file contents from disk with optional offset and limit.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["file_path"],
        },
    )

    sc_text, _ = _render_plain(block, "tools", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "tools", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "tools", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "tools", FULL_EXPANDED)

    assert "Read" in sc_text
    assert "tokens" in sc_text
    assert "Read file contents" not in sc_text
    assert "Read file contents" in se_text
    assert "params: 3 (1 required)" in fc_text
    assert "parameters:" in fe_text
    assert "file_path*" in fe_text
    assert sc_text != se_text
    assert fc_text != fe_text


def test_named_def_child_state_matrix_is_distinct():
    skill = SkillDefChild(
        name="review-pr",
        description="Review pull requests and identify regressions with focused feedback.",
        plugin_source="do",
    )

    skill_sc, _ = _render_plain(skill, "tools", SUMMARY_COLLAPSED)
    skill_se, _ = _render_plain(skill, "tools", SUMMARY_EXPANDED)
    skill_fc, _ = _render_plain(skill, "tools", FULL_COLLAPSED)
    skill_fe, _ = _render_plain(skill, "tools", FULL_EXPANDED)

    assert "review-pr" in skill_sc
    assert "Review pull requests" not in skill_sc
    assert "Review pull requests" in skill_se
    assert "source: do" in skill_fc
    assert "source: do" in skill_fe
    assert skill_sc != skill_se
    assert skill_fc != skill_fe

    agent = AgentDefChild(
        name="researcher",
        description="Gather context and synthesize technical findings.",
        available_tools="All tools",
    )
    agent_sc, _ = _render_plain(agent, "tools", SUMMARY_COLLAPSED)
    agent_se, _ = _render_plain(agent, "tools", SUMMARY_EXPANDED)
    agent_fc, _ = _render_plain(agent, "tools", FULL_COLLAPSED)
    agent_fe, _ = _render_plain(agent, "tools", FULL_EXPANDED)

    assert "researcher" in agent_sc
    assert "Gather context" not in agent_sc
    assert "Gather context" in agent_se
    assert "tools: All tools" in agent_fc
    assert "tools: All tools" in agent_fe
    assert agent_sc != agent_se
    assert agent_fc != agent_fe


def test_turn_budget_summary_expanded_differs_from_collapsed_and_full():
    budget = TurnBudget(
        total_est=120000,
        system_tokens_est=20000,
        tool_defs_tokens_est=15000,
        user_text_tokens_est=28000,
        assistant_text_tokens_est=22000,
        tool_use_tokens_est=18000,
        tool_result_tokens_est=17000,
        actual_input_tokens=1200,
        actual_cache_read_tokens=800,
    )
    block = TurnBudgetBlock(
        budget=budget,
        tool_result_by_name={"Read": 3000, "Bash": 2200, "Grep": 1400},
    )

    sc_text, _ = _render_plain(block, "metadata", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "metadata", SUMMARY_EXPANDED)
    fc_text, fc_lines = _render_plain(block, "metadata", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "metadata", FULL_EXPANDED)

    assert "Context:" in sc_text
    assert "cache:" not in sc_text
    assert "cache:" in se_text
    assert "top tools:" in se_text
    assert se_text != sc_text
    assert se_text != fe_text
    assert "tools:" in fc_text
    assert "cache:" not in fc_text
    assert "top tools:" not in fc_text
    assert fc_lines <= 2


def test_thinking_summary_expanded_shows_preview():
    content = "\n".join(f"thought line {i}" for i in range(1, 20))
    block = ThinkingBlock(content=content)

    sc_text, _ = _render_plain(block, "thinking", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "thinking", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "thinking", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "thinking", FULL_EXPANDED)

    assert "[thinking]" in sc_text
    assert "thought line 1" not in sc_text
    assert "thought line 1" in se_text
    assert "more lines" in se_text
    assert "[snippet]" in fc_text
    assert "thought line 5" not in fc_text
    assert se_text != sc_text
    assert fc_text != fe_text
    assert se_text != fe_text


def test_tracked_content_full_collapsed_uses_bounded_snippet():
    content = "\n".join(f"tracked line {i}" for i in range(1, 12))
    block = TrackedContentBlock(
        status="changed",
        tag_id="sp-42",
        content=content,
        old_content="old 1\nold 2",
        new_content=content,
    )

    sc_text, _ = _render_plain(block, "system", SUMMARY_COLLAPSED)
    fc_text, _ = _render_plain(block, "system", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "system", FULL_EXPANDED)

    assert "CHANGED" in sc_text
    assert "tracked line 1" not in sc_text
    assert "tracked line 1" in fc_text
    assert "[snippet]" in fc_text
    assert "tracked line 6" not in fc_text
    assert "tracked line 6" in fe_text
    assert fc_text != fe_text


def test_text_delta_state_matrix_is_distinct():
    content = "\n".join(f"delta line {i}" for i in range(1, 12))
    block = TextDeltaBlock(content=content, category=Category.ASSISTANT)

    sc_text, _ = _render_plain(block, "assistant", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(block, "assistant", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(block, "assistant", FULL_COLLAPSED)
    fe_text, _ = _render_plain(block, "assistant", FULL_EXPANDED)

    assert "[delta]" in sc_text
    assert "chars" in sc_text
    assert "delta line 1" not in sc_text
    assert "delta line 1" in se_text
    assert "more lines" in se_text
    assert "[snippet]" in fc_text
    assert "delta line 6" not in fc_text
    assert "delta line 6" in fe_text
    assert sc_text != se_text
    assert fc_text != fe_text


def test_config_and_hook_summary_expanded_are_distinct():
    long_config = "\n".join(f"config line {i}" for i in range(1, 18))
    config = ConfigContentBlock(
        source="CLAUDE.md",
        content=long_config,
        category=Category.USER,
    )
    sc_text, _ = _render_plain(config, "user", SUMMARY_COLLAPSED)
    se_text, _ = _render_plain(config, "user", SUMMARY_EXPANDED)
    fc_text, _ = _render_plain(config, "user", FULL_COLLAPSED)
    fe_text, _ = _render_plain(config, "user", FULL_EXPANDED)
    assert "config line 1" in sc_text
    assert "config line 2" in se_text
    assert "more lines" in se_text
    assert "[snippet]" in fc_text
    assert "config line 5" not in fc_text
    assert se_text != sc_text
    assert fc_text != fe_text
    assert se_text != fe_text

    long_hook = "\n".join(f"hook line {i}" for i in range(1, 18))
    hook = HookOutputBlock(
        hook_name="system-reminder",
        content=long_hook,
        category=Category.USER,
    )
    h_sc_text, _ = _render_plain(hook, "user", SUMMARY_COLLAPSED)
    h_se_text, _ = _render_plain(hook, "user", SUMMARY_EXPANDED)
    h_fc_text, _ = _render_plain(hook, "user", FULL_COLLAPSED)
    h_fe_text, _ = _render_plain(hook, "user", FULL_EXPANDED)
    assert "hook line 1" in h_sc_text
    assert "hook line 2" in h_se_text
    assert "more lines" in h_se_text
    assert "[snippet]" in h_fc_text
    assert "hook line 5" not in h_fc_text
    assert h_se_text != h_sc_text
    assert h_fc_text != h_fe_text
    assert h_se_text != h_fe_text


def test_full_collapsed_generic_limit_is_five_lines_plus_indicator():
    block_type = "x" * 500
    block = UnknownTypeBlock(block_type=block_type, category=Category.USER)

    fc_text, fc_lines = _render_plain(block, "user", FULL_COLLAPSED, width=40)

    # 5 content lines + 1 collapse indicator.
    assert fc_lines == 6
    assert "more lines" in fc_text
