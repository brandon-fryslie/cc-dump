"""Tests for the dump conversation command.

Tests that action_dump_conversation:
1. Creates a file with correct structure
2. Handles all 21 block types correctly
3. Shows proper notifications
4. Handles empty conversations
5. Optionally opens in $VISUAL on macOS
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tests.harness import run_app, make_replay_entry
import cc_dump.formatting as fmt
from cc_dump.analysis import TurnBudget


pytestmark = pytest.mark.textual


@pytest.fixture
def mock_notify():
    """Mock the app.notify method to capture notifications."""
    with patch("cc_dump.tui.app.CcDumpApp.notify") as mock:
        yield mock


@patch("subprocess.run")  # Prevent actual editor opening
async def test_dump_creates_file_and_notifies(mock_subprocess, mock_notify):
    """Full flow: replay data → dump → file exists → notifications correct."""
    mock_subprocess.return_value = Mock(returncode=0)

    replay_data = [
        make_replay_entry(
            content="Test user message",
            response_text="Test assistant response",
            system_prompt="Test system prompt",
        )
    ]

    async with run_app(replay_data=replay_data) as (pilot, app):
        # Verify we have conversation data
        conv = app._get_conv()
        assert conv is not None
        assert len(conv._turns) > 0

        # Call dump action
        app.action_dump_conversation()
        await pilot.pause()

        # Verify notification was called with correct message
        mock_notify.assert_called()

        # Check all notification calls for the "Exported to:" message
        # (there may be multiple calls if $VISUAL is set and editor opens)
        all_calls = [call[0][0] for call in mock_notify.call_args_list]
        export_call = [c for c in all_calls if "Exported to:" in c]
        assert len(export_call) == 1, f"Expected one 'Exported to:' call, got: {all_calls}"

        call_args = export_call[0]
        assert call_args.endswith(".txt")

        # Extract file path from notification
        file_path = call_args.split("Exported to: ")[1]
        assert os.path.exists(file_path)

        # Read and verify file structure
        content = Path(file_path).read_text()

        # Verify header
        assert "=" * 80 in content
        assert "CC-DUMP CONVERSATION EXPORT" in content

        # Verify turn structure
        assert "TURN 1" in content
        assert "─" * 80 in content

        # Clean up
        os.unlink(file_path)


async def test_dump_all_block_types():
    """Every block type produces expected text in dump file."""
    # Create base replay data with system prompt to get most block types
    replay_data = [
        make_replay_entry(
            content="Test message",
            response_text="Test response",
            system_prompt="System prompt content",
        )
    ]

    async with run_app(replay_data=replay_data) as (pilot, app):
        conv = app._get_conv()

        # Manually inject additional blocks to cover all 21 types
        # Get first turn and add blocks to it
        if conv._turns:
            turn = conv._turns[0]

            # Add blocks that aren't created by replay data
            # ToolUseBlock
            turn.blocks.append(fmt.ToolUseBlock(
                name="Read",
                tool_use_id="toolu_abc123",
                input_size=42,
                detail="/path/to/file.py"
            ))

            # ToolResultBlock
            turn.blocks.append(fmt.ToolResultBlock(
                tool_name="Read",
                tool_use_id="toolu_abc123",
                size=1024,
                detail="/path/to/file.py"
            ))

            # ToolResultBlock with error
            turn.blocks.append(fmt.ToolResultBlock(
                tool_name="Write",
                tool_use_id="toolu_def456",
                size=0,
                is_error=True,
                detail="File not found"
            ))

            # ToolUseSummaryBlock
            turn.blocks.append(fmt.ToolUseSummaryBlock(
                tool_counts={"Read": 3, "Write": 2},
                total=5,
                first_block_index=10
            ))

            # ImageBlock
            turn.blocks.append(fmt.ImageBlock(media_type="image/png"))

            # UnknownTypeBlock
            turn.blocks.append(fmt.UnknownTypeBlock(block_type="custom_block"))

            # StreamToolUseBlock
            turn.blocks.append(fmt.StreamToolUseBlock(name="Bash"))

            # ProxyErrorBlock
            turn.blocks.append(fmt.ProxyErrorBlock(error="Connection refused"))

            # ErrorBlock
            turn.blocks.append(fmt.ErrorBlock(code=401, reason="Unauthorized"))

            # StopReasonBlock
            turn.blocks.append(fmt.StopReasonBlock(reason="end_turn"))

            # TurnBudgetBlock with actual tokens
            budget = TurnBudget(
                actual_input_tokens=100,
                actual_output_tokens=50,
                actual_cache_creation_tokens=20,
                actual_cache_read_tokens=30,
                total_est=200
            )
            turn.blocks.append(fmt.TurnBudgetBlock(budget=budget))

            # StreamInfoBlock
            turn.blocks.append(fmt.StreamInfoBlock(model="claude-sonnet-4-5"))

            # TextDeltaBlock (only in streaming mode, manually add for test)
            turn.blocks.append(fmt.TextDeltaBlock(content="Streaming text delta"))

            # SeparatorBlock
            turn.blocks.append(fmt.SeparatorBlock(style="heavy"))

            # NewlineBlock
            turn.blocks.append(fmt.NewlineBlock())

        # Now dump and verify all block types
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            tmp_path = f.name

        try:
            # Directly call _write_block_text for each block type to test
            conv = app._get_conv()
            turn = conv._turns[0]

            with open(tmp_path, 'w') as f:
                f.write("=" * 80 + "\n")
                f.write("CC-DUMP CONVERSATION EXPORT\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"\n{'─' * 80}\n")
                f.write("TURN 1\n")
                f.write(f"{'─' * 80}\n\n")

                counter = [0]
                def _write_all(blocks):
                    for block in blocks:
                        app._write_block_text(f, block, counter[0])
                        f.write("\n")
                        counter[0] += 1
                        _write_all(getattr(block, "children", []))
                _write_all(turn.blocks)

            # Read back and verify
            content = Path(tmp_path).read_text()

            # Verify each block type's expected content
            assert "HeaderBlock" in content
            assert "REQUEST" in content or "RESPONSE" in content

            assert "MetadataBlock" in content
            assert "Model:" in content
            assert "Max tokens:" in content

            # Containers replaced flat label blocks
            assert "MetadataSection" in content
            assert "SystemSection" in content
            assert "SYSTEM" in content

            assert "TrackedContentBlock" in content
            assert "Status:" in content

            assert "MessageBlock" in content
            assert "USER [" in content or "ASSISTANT [" in content

            assert "TextContentBlock" in content

            assert "TextDeltaBlock" in content

            # These should NOT crash (the bugs we're fixing)
            assert "ToolUseBlock" in content
            assert "Tool: Read" in content
            assert "ID: toolu_abc123" in content

            assert "ToolResultBlock" in content
            # ToolResultBlock with error should show ERROR or Result
            assert ("ERROR (" in content or "Result size:" in content)

            assert "ToolUseSummaryBlock" in content
            assert "Tools:" in content or "Tool counts:" in content

            assert "ImageBlock" in content
            assert "Image:" in content or "Media type:" in content

            assert "UnknownTypeBlock" in content
            assert "Unknown" in content or "custom_block" in content

            assert "StreamToolUseBlock" in content
            assert "Bash" in content

            assert "ProxyErrorBlock" in content
            assert "Connection refused" in content

            assert "ErrorBlock" in content
            assert "401" in content
            assert "Unauthorized" in content

            assert "StopReasonBlock" in content
            assert "Stop reason:" in content
            assert "end_turn" in content

            assert "TurnBudgetBlock" in content
            assert "Input tokens:" in content or "actual_input_tokens" in content

            assert "StreamInfoBlock" in content
            assert "claude-sonnet-4-5" in content

            assert "SeparatorBlock" in content
            assert "NewlineBlock" in content

            assert "HttpHeadersBlock" in content

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


async def test_dump_empty_conversation_notifies_warning(mock_notify):
    """Empty conversation → warning notification, no file created."""
    async with run_app(replay_data=[]) as (pilot, app):
        # Verify no conversation data
        conv = app._get_conv()
        assert conv is None or not conv._turns

        # Call dump action
        app.action_dump_conversation()
        await pilot.pause()

        # Verify warning notification
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert "No conversation to dump" in call_args[0][0]
        assert call_args[1]["severity"] == "warning"


@patch("platform.system")
@patch("subprocess.run")
@patch.dict(os.environ, {"VISUAL": "vim"})
async def test_dump_visual_editor_macos(mock_subprocess, mock_platform, mock_notify):
    """On macOS with $VISUAL, subprocess.run is called correctly."""
    mock_platform.return_value = "Darwin"
    mock_subprocess.return_value = Mock(returncode=0)

    replay_data = [make_replay_entry()]

    async with run_app(replay_data=replay_data) as (pilot, app):
        app.action_dump_conversation()
        await pilot.pause()

        # Verify subprocess.run was called
        assert mock_subprocess.called
        call_args = mock_subprocess.call_args

        # Should be called with [editor, file_path]
        assert len(call_args[0][0]) == 2
        assert call_args[0][0][0] == "vim"
        assert call_args[0][0][1].endswith(".txt")

        # Should have timeout
        assert call_args[1]["timeout"] == 20


@patch("platform.system")
async def test_dump_no_visual_linux(mock_platform, mock_notify):
    """On Linux without $VISUAL, file is created but editor not opened."""
    mock_platform.return_value = "Linux"

    # Remove VISUAL from environment if present
    env_backup = os.environ.get("VISUAL")
    if "VISUAL" in os.environ:
        del os.environ["VISUAL"]

    try:
        replay_data = [make_replay_entry()]

        async with run_app(replay_data=replay_data) as (pilot, app):
            app.action_dump_conversation()
            await pilot.pause()

            # Should notify with file path
            mock_notify.assert_called()
            call_args = mock_notify.call_args[0][0]
            assert "Exported to:" in call_args
            assert not any("Opening" in str(call) for call in mock_notify.call_args_list)

    finally:
        # Restore VISUAL if it was set
        if env_backup:
            os.environ["VISUAL"] = env_backup


async def test_dump_handles_blocks_without_optional_fields():
    """Blocks with None/missing optional fields don't crash."""
    replay_data = [make_replay_entry()]

    async with run_app(replay_data=replay_data) as (pilot, app):
        conv = app._get_conv()

        # Add blocks with minimal fields
        if conv._turns:
            turn = conv._turns[0]

            # HeaderBlock without timestamp
            turn.blocks.append(fmt.HeaderBlock(label="TEST", timestamp=""))

            # MetadataBlock without optional fields
            turn.blocks.append(fmt.MetadataBlock(model="", max_tokens="", tool_count=0))

            # ToolUseBlock without detail
            turn.blocks.append(fmt.ToolUseBlock(
                name="Test",
                tool_use_id="test_id",
                detail=""
            ))

            # TrackedContentBlock with old/new content
            turn.blocks.append(fmt.TrackedContentBlock(
                status="changed",
                old_content="old",
                new_content="new"
            ))

        # Should not crash
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            tmp_path = f.name

        try:
            conv = app._get_conv()
            turn = conv._turns[0]

            with open(tmp_path, 'w') as f:
                for idx, block in enumerate(turn.blocks):
                    app._write_block_text(f, block, idx)
                    f.write("\n")

            # Just verify it doesn't crash and creates content
            content = Path(tmp_path).read_text()
            assert len(content) > 0

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
