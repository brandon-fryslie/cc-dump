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


def _provider_keys() -> set[str]:
    # [LAW:one-source-of-truth] Known provider keys come from provider registry.
    return {spec.key for spec in cc_dump.providers.all_provider_specs()}


def _provider_from_filename(path: Path, provider_keys: set[str]) -> str | None:
    stem = path.stem
    if not stem.startswith("ccdump-"):
        return None
    parts = stem.split("-", 3)
    if len(parts) < 4:
        return None
    # [LAW:one-source-of-truth] Provider identity in filename must match canonical provider keys.
    candidate = parts[1]
    return candidate if candidate in provider_keys else None


def _provider_from_metadata(entries: list[dict], provider_keys: set[str]) -> str | None:
    if not entries:
        return None
    metadata = entries[0].get("_cc_dump", {})
    if not isinstance(metadata, dict):
        return None
    candidate = metadata.get("provider")
    if not isinstance(candidate, str):
        return None
    normalized = candidate.strip().lower()
    return normalized if normalized in provider_keys else None


def _provider_from_request_url(entries: list[dict]) -> str | None:
    if not entries:
        return None
    request = entries[0].get("request", {})
    if not isinstance(request, dict):
        return None
    raw_url = request.get("url")
    if not isinstance(raw_url, str):
        return None
    url = raw_url.strip().lower()
    if not url:
        return None
    # [LAW:one-source-of-truth] URL marker matching uses provider registry metadata.
    for spec in cc_dump.providers.all_provider_specs():
        if any(marker in url for marker in spec.url_markers):
            return spec.key
    return None


def _provider_from_entries(entries: list[dict], provider_keys: set[str]) -> str | None:
    return _provider_from_metadata(entries, provider_keys) or _provider_from_request_url(entries)


def _entry_created_or_mtime(entries: list[dict], path: Path) -> str:
    if entries and "startedDateTime" in entries[0]:
        return str(entries[0]["startedDateTime"])
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _load_recording_info(
    path: Path,
    provider_keys: set[str],
) -> RecordingInfo:
    with open(path, "r", encoding="utf-8") as f:
        har = json.load(f)

    entries = har.get("log", {}).get("entries", [])
    return {
        "path": str(path),
        "filename": path.name,
        "provider": _provider_from_filename(path, provider_keys)
        or _provider_from_entries(entries, provider_keys),
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
    provider_keys = _provider_keys()

    # Process all found .har files
    for path in har_files:
        try:
            recordings.append(_load_recording_info(path, provider_keys))

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

    for rec in to_remove:
        har_path = Path(rec["path"])
        sidecar_path = Path(str(har_path) + ".ui.json")

        for candidate in (har_path, sidecar_path):
            if not candidate.exists():
                continue
            size = candidate.stat().st_size
            bytes_freed += size
            removed_paths.append(str(candidate))
            if not dry_run:
                candidate.unlink()

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
    print(f"{'PROVIDER':<12} {'CREATED':<22} {'ENTRIES':<10} {'SIZE':<12} {'FILE':<50}")
    print("-" * 112)

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
        provider = rec.get("provider") or "(mixed)"

        print(
            f"{provider:<12} {created:<22} {rec['entry_count']:<10} {size_str:<12} {filename:<50}"
        )

    print()
