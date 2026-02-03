"""Tests for session management (HAR recording listing and metadata)."""

import json
import os
from pathlib import Path

import pytest

from cc_dump.sessions import (
    list_recordings,
    get_latest_recording,
    format_size,
    get_recordings_dir,
)


@pytest.fixture
def recordings_dir(tmp_path):
    """Create a temporary recordings directory."""
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    return recordings


def create_har_file(path: Path, entry_count: int = 1, session_id: str = "test") -> None:
    """Create a minimal HAR file for testing.

    Args:
        path: Path to write the HAR file
        entry_count: Number of entries to include
        session_id: Session ID (embedded in entries)
    """
    entries = []
    for i in range(entry_count):
        entries.append({
            "startedDateTime": f"2026-02-03T14:00:{i:02d}",
            "time": 100.0,
            "request": {
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
                "headers": [],
                "postData": {
                    "text": json.dumps({"model": "claude-3-opus", "messages": []}),
                },
            },
            "response": {
                "status": 200,
                "headers": [],
                "content": {
                    "text": json.dumps({
                        "id": f"msg_{i}",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Hello"}],
                    }),
                },
            },
        })

    har = {
        "log": {
            "version": "1.2",
            "creator": {"name": "cc-dump", "version": "0.2.0"},
            "entries": entries,
        }
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(har, f)


# Test: list_recordings returns empty list for non-existent directory


def test_list_recordings_empty_dir(tmp_path):
    """list_recordings returns empty list if directory doesn't exist."""
    non_existent = tmp_path / "does-not-exist"
    recordings = list_recordings(str(non_existent))
    assert recordings == []


# Test: list_recordings returns empty list for empty directory


def test_list_recordings_no_files(recordings_dir):
    """list_recordings returns empty list if no .har files in directory."""
    recordings = list_recordings(str(recordings_dir))
    assert recordings == []


# Test: list_recordings finds single recording


def test_list_recordings_single_file(recordings_dir):
    """list_recordings finds single HAR file."""
    har_path = recordings_dir / "recording-abc123.har"
    create_har_file(har_path, entry_count=5, session_id="abc123")

    recordings = list_recordings(str(recordings_dir))
    assert len(recordings) == 1
    assert recordings[0]["filename"] == "recording-abc123.har"
    assert recordings[0]["session_id"] == "abc123"
    assert recordings[0]["entry_count"] == 5
    assert recordings[0]["size_bytes"] > 0
    assert "2026-02-03" in recordings[0]["created"]


# Test: list_recordings finds multiple recordings


def test_list_recordings_multiple_files(recordings_dir):
    """list_recordings finds multiple HAR files, sorted by name."""
    har1 = recordings_dir / "recording-aaa.har"
    har2 = recordings_dir / "recording-zzz.har"
    har3 = recordings_dir / "recording-mmm.har"

    create_har_file(har1, entry_count=1)
    create_har_file(har2, entry_count=2)
    create_har_file(har3, entry_count=3)

    recordings = list_recordings(str(recordings_dir))
    assert len(recordings) == 3

    # Should be sorted by filename (alphabetical)
    assert recordings[0]["filename"] == "recording-aaa.har"
    assert recordings[1]["filename"] == "recording-mmm.har"
    assert recordings[2]["filename"] == "recording-zzz.har"


# Test: list_recordings skips malformed files


def test_list_recordings_skips_malformed(recordings_dir):
    """list_recordings skips malformed HAR files and continues."""
    good = recordings_dir / "recording-good.har"
    bad = recordings_dir / "recording-bad.har"

    create_har_file(good, entry_count=1)

    # Create invalid JSON file
    with open(bad, "w") as f:
        f.write("not valid json {")

    recordings = list_recordings(str(recordings_dir))
    assert len(recordings) == 1
    assert recordings[0]["filename"] == "recording-good.har"


# Test: list_recordings only includes .har files


def test_list_recordings_only_har_files(recordings_dir):
    """list_recordings only includes .har files, ignores others."""
    har = recordings_dir / "recording-abc.har"
    txt = recordings_dir / "notes.txt"
    json_file = recordings_dir / "data.json"

    create_har_file(har)
    txt.write_text("some notes")
    json_file.write_text('{"foo": "bar"}')

    recordings = list_recordings(str(recordings_dir))
    assert len(recordings) == 1
    assert recordings[0]["filename"] == "recording-abc.har"


# Test: get_latest_recording returns None for empty directory


def test_get_latest_recording_empty(tmp_path):
    """get_latest_recording returns None if no recordings exist."""
    non_existent = tmp_path / "empty"
    latest = get_latest_recording(str(non_existent))
    assert latest is None


# Test: get_latest_recording returns single recording


def test_get_latest_recording_single(recordings_dir):
    """get_latest_recording returns the only recording."""
    har = recordings_dir / "recording-xyz.har"
    create_har_file(har)

    latest = get_latest_recording(str(recordings_dir))
    assert latest == str(har)


# Test: get_latest_recording returns most recent by timestamp


def test_get_latest_recording_multiple(recordings_dir):
    """get_latest_recording returns the most recent by created timestamp."""
    har1 = recordings_dir / "recording-aaa.har"
    har2 = recordings_dir / "recording-bbb.har"
    har3 = recordings_dir / "recording-ccc.har"

    # Create with different timestamps in entries
    create_har_file(har1)
    create_har_file(har2)
    create_har_file(har3)

    # Modify the timestamps in the HAR files
    for idx, (path, timestamp) in enumerate([(har1, "2026-02-01T10:00:00"),
                                               (har2, "2026-02-03T10:00:00"),  # Latest
                                               (har3, "2026-02-02T10:00:00")]):
        with open(path, "r+") as f:
            har = json.load(f)
            har["log"]["entries"][0]["startedDateTime"] = timestamp
            f.seek(0)
            json.dump(har, f)
            f.truncate()

    latest = get_latest_recording(str(recordings_dir))
    assert latest == str(har2)  # bbb has the latest timestamp


# Test: format_size handles various sizes


def test_format_size_bytes():
    """format_size formats bytes correctly."""
    assert format_size(0) == "0 B"
    assert format_size(100) == "100 B"
    assert format_size(1023) == "1023 B"


def test_format_size_kilobytes():
    """format_size formats kilobytes correctly."""
    assert format_size(1024) == "1.0 KB"
    assert format_size(1536) == "1.5 KB"
    assert format_size(1024 * 100) == "100.0 KB"


def test_format_size_megabytes():
    """format_size formats megabytes correctly."""
    assert format_size(1024 * 1024) == "1.0 MB"
    assert format_size(1024 * 1024 * 2.5) == "2.5 MB"


def test_format_size_gigabytes():
    """format_size formats gigabytes correctly."""
    assert format_size(1024 * 1024 * 1024) == "1.0 GB"
    assert format_size(1024 * 1024 * 1024 * 3.2) == "3.2 GB"


# Test: get_recordings_dir returns expected path


def test_get_recordings_dir():
    """get_recordings_dir returns ~/.local/share/cc-dump/recordings/."""
    expected = os.path.expanduser("~/.local/share/cc-dump/recordings")
    assert get_recordings_dir() == expected


# Test: list_recordings handles HAR without session_id in filename


def test_list_recordings_custom_filename(recordings_dir):
    """list_recordings handles HAR files with non-standard names."""
    har = recordings_dir / "my-custom-recording.har"
    create_har_file(har)

    recordings = list_recordings(str(recordings_dir))
    assert len(recordings) == 1
    assert recordings[0]["filename"] == "my-custom-recording.har"
    assert recordings[0]["session_id"] is None  # Can't extract from filename


# Test: list_recordings handles HAR without startedDateTime


def test_list_recordings_no_timestamp(recordings_dir):
    """list_recordings falls back to file mtime if no startedDateTime."""
    har = recordings_dir / "recording-xyz.har"

    # Create HAR without startedDateTime
    har_data = {
        "log": {
            "version": "1.2",
            "creator": {"name": "cc-dump"},
            "entries": [{
                "request": {"postData": {"text": "{}"}},
                "response": {"content": {"text": '{"type": "message", "content": []}'}},
            }],
        }
    }

    with open(har, "w") as f:
        json.dump(har_data, f)

    recordings = list_recordings(str(recordings_dir))
    assert len(recordings) == 1
    # Should have a created timestamp from file mtime
    assert recordings[0]["created"] is not None
