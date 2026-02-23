from unittest.mock import MagicMock, patch

from cc_dump.ai.action_items import ActionSourceLink, ActionWorkItem
from cc_dump.ai.action_items_beads import create_beads_issue_for_item


def _sample_item() -> ActionWorkItem:
    return ActionWorkItem(
        item_id="act_1",
        kind="action",
        text="Implement acceptance workflow",
        confidence=0.8,
        owner="bmf",
        due_hint="soon",
        source_links=[ActionSourceLink(request_id="req-1", message_index=2)],
        status="accepted",
        beads_issue_id="",
        created_at="2026-02-22T00:00:00+00:00",
    )


def test_create_beads_issue_for_item_returns_issue_id():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "✓ Created issue: cc-dump-abc.1\n"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        issue_id = create_beads_issue_for_item(_sample_item())

    assert issue_id == "cc-dump-abc.1"
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[:2] == ["bd", "create"]


def test_create_beads_issue_for_item_returns_empty_on_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "error"

    with patch("subprocess.run", return_value=mock_result):
        issue_id = create_beads_issue_for_item(_sample_item())

    assert issue_id == ""
