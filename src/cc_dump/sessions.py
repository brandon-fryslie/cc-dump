"""Session management for HAR recordings.

Provides listing, metadata extraction, and utility functions for managing
recorded HAR files in the recordings directory.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_recordings_dir() -> str:
    """Get the default recordings directory path.

    Returns:
        Absolute path to ~/.local/share/cc-dump/recordings/
    """
    return os.path.expanduser("~/.local/share/cc-dump/recordings")


def list_recordings(recordings_dir: Optional[str] = None) -> list[dict]:
    """List available recordings with metadata.

    Args:
        recordings_dir: Directory to search (default: ~/.local/share/cc-dump/recordings)

    Returns:
        List of recording metadata dicts, sorted by filename (chronological):
        [
            {
                "path": "/path/to/recording-xyz.har",
                "filename": "recording-xyz.har",
                "session_id": "xyz",
                "session_name": "my-session",  # NEW: session subdirectory name
                "created": "2026-02-03T14:30:00",
                "entry_count": 42,
                "size_bytes": 102400,
            },
            ...
        ]
    """
    if recordings_dir is None:
        recordings_dir = get_recordings_dir()

    recordings = []
    recordings_path = Path(recordings_dir)

    # Return empty list if directory doesn't exist
    if not recordings_path.exists():
        return recordings

    # [LAW:dataflow-not-control-flow] Search both session subdirectories and flat structure
    # Collect all .har files from:
    # 1. Session subdirectories (recordings/*/recording-*.har)
    # 2. Flat directory (recordings/recording-*.har) - backwards compatibility
    har_files = []

    # Session subdirectories
    for session_dir in recordings_path.iterdir():
        if session_dir.is_dir():
            har_files.extend((path, session_dir.name) for path in session_dir.glob("*.har"))

    # Flat directory (backwards compatibility)
    har_files.extend((path, None) for path in recordings_path.glob("*.har"))

    # Process all found .har files
    for path, session_name in sorted(har_files, key=lambda x: x[0]):
        try:
            # Extract session_id from filename (recording-<session_id>.har)
            session_id = None
            if path.stem.startswith("recording-"):
                session_id = path.stem[len("recording-") :]

            # Load HAR to get entry count and creation time
            with open(path, "r", encoding="utf-8") as f:
                har = json.load(f)

            entries = har.get("log", {}).get("entries", [])
            entry_count = len(entries)

            # Get creation time from first entry or file mtime
            created = None
            if entries and "startedDateTime" in entries[0]:
                created = entries[0]["startedDateTime"]
            else:
                # Fallback to file modification time
                mtime = path.stat().st_mtime
                created = datetime.fromtimestamp(mtime).isoformat()

            recordings.append(
                {
                    "path": str(path),
                    "filename": path.name,
                    "session_id": session_id,
                    "session_name": session_name,  # None for flat structure files
                    "created": created,
                    "entry_count": entry_count,
                    "size_bytes": path.stat().st_size,
                }
            )

        except (json.JSONDecodeError, OSError, KeyError) as e:
            # Skip malformed files, but continue processing others
            import sys

            sys.stderr.write(f"[sessions] Warning: skipping {path.name}: {e}\n")
            sys.stderr.flush()
            continue

    return recordings


def get_latest_recording(recordings_dir: Optional[str] = None) -> Optional[str]:
    """Get the path to the most recent recording.

    Args:
        recordings_dir: Directory to search (default: ~/.local/share/cc-dump/recordings)

    Returns:
        Absolute path to the latest recording, or None if no recordings exist
    """
    recordings = list_recordings(recordings_dir)
    if not recordings:
        return None

    # Sort by created timestamp and return the latest
    recordings.sort(key=lambda r: r["created"])
    return recordings[-1]["path"]


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string like "1.2 MB" or "512 KB"
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def print_recordings_list(recordings: list[dict]) -> None:
    """Print a formatted list of recordings.

    Args:
        recordings: List of recording metadata dicts from list_recordings()
    """
    if not recordings:
        print("No recordings found.")
        return

    print(f"Found {len(recordings)} recording(s):\n")

    # Print table header
    print(f"{'SESSION':<20} {'CREATED':<22} {'ENTRIES':<10} {'SIZE':<12} {'FILE':<50}")
    print("-" * 114)

    # Print each recording
    for rec in recordings:
        # Format timestamp (just date and time, drop timezone info for brevity)
        created = rec["created"]
        if "T" in created:
            created = (
                created.split("T")[0]
                + " "
                + created.split("T")[1].split("+")[0].split(".")[0]
            )

        size_str = format_size(rec["size_bytes"])
        filename = rec["filename"]
        session_name = rec.get("session_name") or "(flat)"

        print(f"{session_name:<20} {created:<22} {rec['entry_count']:<10} {size_str:<12} {filename:<50}")

    print()
