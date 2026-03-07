"""Settings file I/O for cc-dump.

Manages a general-purpose JSON settings file at XDG_CONFIG_HOME/cc-dump/settings.json.
Built-in filterset defaults and theme/settings persistence.

This module is a STABLE BOUNDARY — not hot-reloadable.
Import as: import cc_dump.io.settings
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from cc_dump.core.formatting import VisState


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


def merge_setting(current_data: dict, key: str, value) -> dict:
    """Return a new settings dict with a single key updated."""
    data = dict(current_data)
    data[key] = value
    return data


def load_setting(key: str, default=None):
    """Load a single setting by key. Returns default if absent."""
    return load_settings().get(key, default)


def save_setting(key: str, value) -> None:
    """Save a single setting by key (merge into existing settings)."""
    data = merge_setting(load_settings(), key, value)
    save_settings(data)


# [LAW:one-source-of-truth] Built-in filterset defaults.
_H = VisState(False, False, False)   # hidden
_SC = VisState(True, False, False)   # summary, collapsed
_SE = VisState(True, False, True)    # summary, expanded
_FC = VisState(True, True, False)    # full, collapsed
_FE = VisState(True, True, True)     # full, expanded

def _fs(user, assistant, tools, system, metadata, thinking):
    return {"user": user, "assistant": assistant, "tools": tools,
            "system": system, "metadata": metadata, "thinking": thinking}

DEFAULT_FILTERSETS: dict[str, dict[str, VisState]] = {
    "1": _fs(_FE, _FE, _SC, _SC, _H,  _SC),    # Conversation
    "2": _fs(_SC, _SC, _SC, _SC, _SC, _SC),     # Overview
    "4": _fs(_SC, _SC, _FE, _H,  _H,  _H),     # Tools
    "5": _fs(_SC, _SC, _H,  _FE, _FE, _H),     # System
    "6": _fs(_SC, _SC, _SC, _H,  _FE, _H),     # Cost
    "7": _fs(_FE, _FE, _FE, _FE, _FE, _FE),    # Full Debug
    "8": _fs(_H,  _FE, _H,  _H,  _H,  _H),     # Assistant
    "9": _fs(_SC, _SC, _SC, _H,  _H,  _H),     # Minimal
}


def get_filterset(slot: str) -> Optional[dict[str, VisState]]:
    """Return the built-in filterset for a slot."""
    # [LAW:one-source-of-truth] Filterset slots are defined only by built-in defaults.
    return DEFAULT_FILTERSETS.get(slot)
