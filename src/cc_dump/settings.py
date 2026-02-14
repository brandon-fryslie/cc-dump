"""Settings file I/O for cc-dump.

Manages a general-purpose JSON settings file at XDG_CONFIG_HOME/cc-dump/settings.json.
Filterset persistence is one consumer; other settings can be added as top-level keys.

This module is a STABLE BOUNDARY — not hot-reloadable.
Import as: import cc_dump.settings
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from cc_dump.formatting import VisState


def get_config_path() -> Path:
    """Return path to settings file.

    Uses XDG_CONFIG_HOME (default ~/.config) / cc-dump / settings.json.
    """
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(config_home) / "cc-dump" / "settings.json"


def load_settings() -> dict:
    """Load settings from JSON file. Returns empty dict on missing/corrupt file."""
    path = get_config_path()
    # [LAW:dataflow-not-control-flow] Always attempt read; empty dict is the "no data" value.
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_settings(data: dict) -> None:
    """Atomic write of settings dict to JSON file.

    Creates parent directories if needed. Writes to temp file then renames
    to avoid partial writes on crash.
    """
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: write temp → rename
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_filtersets() -> dict[str, dict[str, list[bool]]]:
    """Extract filtersets key from settings. Returns empty dict if absent."""
    return load_settings().get("filtersets", {})


def save_filterset(slot: str, filters: dict[str, VisState]) -> None:
    """Merge one filterset slot into settings and save.

    Each category maps to [visible, full, expanded] triple.
    """
    data = load_settings()
    filtersets = data.get("filtersets", {})
    filtersets[slot] = {
        name: list(vs)
        for name, vs in filters.items()
    }
    data["filtersets"] = filtersets
    save_settings(data)


def save_theme(theme_name: str) -> None:
    """Persist theme choice to settings."""
    data = load_settings()
    data["theme"] = theme_name
    save_settings(data)


def load_theme() -> Optional[str]:
    """Load saved theme name, or None if unset."""
    return load_settings().get("theme")


def get_filterset(slot: str) -> Optional[dict[str, VisState]]:
    """Load a single filterset slot, returning dict[str, VisState] or None if unset."""
    filtersets = load_filtersets()
    raw = filtersets.get(slot)
    if raw is None:
        return None
    # Convert [bool, bool, bool] lists back to VisState
    return {
        name: VisState(*triple)
        for name, triple in raw.items()
        if isinstance(triple, list) and len(triple) == 3
    }
