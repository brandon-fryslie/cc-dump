"""HAR recording management utilities."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

import cc_dump.providers

logger = logging.getLogger(__name__)


class RecordingInfo(TypedDict):
    path: str
    filename: str
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


def _provider_from_entries(entries: list[dict]) -> str | None:
    if not entries:
        return None
    # [LAW:one-source-of-truth] HAR provider precedence is owned by providers module.
    return cc_dump.providers.detect_provider_from_har_entry(entries[0])


def _entry_created_or_mtime(entries: list[dict], path: Path) -> str:
    if entries and "startedDateTime" in entries[0]:
        return str(entries[0]["startedDateTime"])
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _load_recording_info(path: Path) -> RecordingInfo:
    with open(path, "r", encoding="utf-8") as f:
        har = json.load(f)

    entries = har.get("log", {}).get("entries", [])
    return {
        "path": str(path),
        "filename": path.name,
        "provider": _provider_from_entries(entries),
        "created": _entry_created_or_mtime(entries, path),
        "entry_count": len(entries),
        "size_bytes": path.stat().st_size,
    }


def list_recordings(recordings_dir: Optional[str] = None) -> list[RecordingInfo]:
    """List available recordings with metadata.

    Args:
        recordings_dir: Directory to search (default: ~/.local/share/cc-dump/recordings)

    Returns:
        List of recording metadata dicts, sorted by filename:
        [
            {
                "path": "/path/to/ccdump-anthropic-20260304-101530Z-a1b2c3d4.har",
                "filename": "ccdump-anthropic-20260304-101530Z-a1b2c3d4.har",
                "provider": "anthropic",
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

    # [LAW:one-source-of-truth] Canonical recording layout is flat under recordings root.
    har_files = sorted(path for path in recordings_path.glob("*.har") if path.is_file())

    # Process all found .har files
    for path in har_files:
        try:
            recordings.append(_load_recording_info(path))

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
    """Delete older HAR recordings, keeping newest N.

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

    for rec in to_remove:
        har_path = Path(rec["path"])
        if not har_path.exists():
            continue
        size = har_path.stat().st_size
        bytes_freed += size
        removed_paths.append(str(har_path))
        if not dry_run:
            har_path.unlink()

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
