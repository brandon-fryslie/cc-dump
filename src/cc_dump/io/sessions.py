"""Session management for HAR recordings.

Provides listing, metadata extraction, and utility functions for managing
recorded HAR files in the recordings directory.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)


class RecordingInfo(TypedDict):
    path: str
    filename: str
    session_id: str | None
    session_name: str | None
    provider: str | None
    created: str
    entry_count: int
    size_bytes: int


class CleanupResult(TypedDict):
    kept: int
    removed: int
    bytes_freed: int
    removed_paths: list[str]
    dry_run: bool


def get_recordings_dir() -> str:
    """Get the default recordings directory path.

    Returns:
        Absolute path to ~/.local/share/cc-dump/recordings/
    """
    return os.path.expanduser("~/.local/share/cc-dump/recordings")


def list_recordings(recordings_dir: Optional[str] = None) -> list[RecordingInfo]:
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

    recordings: list[RecordingInfo] = []
    recordings_path = Path(recordings_dir)

    # Return empty list if directory doesn't exist
    if not recordings_path.exists():
        return recordings

    # // [LAW:dataflow-not-control-flow] One recursive HAR scan supports old and new folder layouts.
    har_files = sorted(path for path in recordings_path.rglob("*.har") if path.is_file())

    def _infer_context(path: Path) -> tuple[str | None, str | None]:
        try:
            rel_parts = path.relative_to(recordings_path).parts
        except ValueError:
            return (None, None)
        if len(rel_parts) >= 3:
            # recordings/<session>/<provider>/<file>.har
            return (rel_parts[-3], rel_parts[-2])
        if len(rel_parts) == 2:
            # recordings/<session>/<file>.har
            return (rel_parts[-2], None)
        return (None, None)

    # Process all found .har files
    for path in har_files:
        try:
            session_name, provider = _infer_context(path)

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
                    "provider": provider,
                    "created": created,
                    "entry_count": entry_count,
                    "size_bytes": path.stat().st_size,
                }
            )

        except (json.JSONDecodeError, OSError, KeyError) as e:
            # Skip malformed files, but continue processing others
            logger.warning("skipping malformed recording %s: %s", path.name, e)
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


def cleanup_recordings(
    recordings_dir: Optional[str] = None,
    *,
    keep: int = 20,
    dry_run: bool = False,
) -> CleanupResult:
    """Delete older HAR recordings and UI sidecars, keeping newest N.

    Args:
        recordings_dir: Base recordings directory (default: ~/.local/share/cc-dump/recordings)
        keep: Number of newest recordings to keep
        dry_run: When True, report only (no filesystem changes)
    """
    if keep < 0:
        keep = 0
    if recordings_dir is None:
        recordings_dir = get_recordings_dir()

    recordings = list_recordings(recordings_dir)
    if not recordings:
        return {
            "kept": 0,
            "removed": 0,
            "bytes_freed": 0,
            "removed_paths": [],
            "dry_run": dry_run,
        }

    # Newest first by created timestamp.
    recordings.sort(key=lambda r: r["created"], reverse=True)
    survivors = recordings[:keep]
    to_remove = recordings[keep:]

    removed_paths: list[str] = []
    bytes_freed = 0
    touched_dirs: set[Path] = set()

    for rec in to_remove:
        har_path = Path(rec["path"])
        sidecar_path = Path(str(har_path) + ".ui.json")

        for candidate in (har_path, sidecar_path):
            if not candidate.exists():
                continue
            size = candidate.stat().st_size
            bytes_freed += size
            removed_paths.append(str(candidate))
            touched_dirs.add(candidate.parent)
            touched_dirs.add(candidate.parent.parent)
            if not dry_run:
                candidate.unlink()

    # Best-effort cleanup of now-empty session subdirectories.
    if not dry_run:
        root = Path(recordings_dir).resolve()
        for directory in sorted(touched_dirs, key=lambda p: len(p.parts), reverse=True):
            try:
                resolved = directory.resolve()
            except OSError:
                continue
            if resolved == root:
                continue
            try:
                directory.rmdir()
            except OSError:
                continue

    return {
        "kept": len(survivors),
        "removed": len(to_remove),
        "bytes_freed": bytes_freed,
        "removed_paths": removed_paths,
        "dry_run": dry_run,
    }


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


def print_recordings_list(recordings: list[RecordingInfo]) -> None:
    """Print a formatted list of recordings.

    Args:
        recordings: List of recording metadata dicts from list_recordings()
    """
    if not recordings:
        print("No recordings found.")
        return

    print(f"Found {len(recordings)} recording(s):\n")

    # Print table header
    print(
        f"{'SESSION':<20} {'PROVIDER':<12} {'CREATED':<22} {'ENTRIES':<10} {'SIZE':<12} {'FILE':<50}"
    )
    print("-" * 127)

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
        provider = rec.get("provider") or "(mixed)"

        print(
            f"{session_name:<20} {provider:<12} {created:<22} {rec['entry_count']:<10} {size_str:<12} {filename:<50}"
        )

    print()
