"""Settings file I/O for cc-dump.

Manages a general-purpose JSON settings file at XDG_CONFIG_HOME/cc-dump/settings.json.
Built-in filterset defaults and theme/settings persistence.

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


def load_setting(key: str, default=None):
    """Load a single setting by key. Returns default if absent."""
    return load_settings().get(key, default)


def save_setting(key: str, value) -> None:
    """Save a single setting by key (merge into existing settings)."""
    data = load_settings()
    data[key] = value
    save_settings(data)


def load_claude_command() -> str:
    """Load the configured Claude command for tmux integration."""
    return load_setting("claude_command", "claude")


def save_claude_command(command: str) -> None:
    """Save the Claude command for tmux integration."""
    save_setting("claude_command", command)


def load_auto_zoom_default() -> bool:
    """Load the configured auto-zoom default for tmux integration."""
    return bool(load_setting("auto_zoom_default", False))


def save_theme(theme_name: str) -> None:
    """Persist theme choice to settings."""
    data = load_settings()
    data["theme"] = theme_name
    save_settings(data)


def load_theme() -> Optional[str]:
    """Load saved theme name, or None if unset."""
    return load_settings().get("theme")


# [LAW:one-source-of-truth] Built-in filterset defaults.
_H = VisState(False, False, False)  # hidden
_SC = VisState(True, False, False)  # summary, collapsed
_FC = VisState(True, True, False)   # full, collapsed

def _fs(user, assistant, tools, system, metadata, thinking):
    return {"user": user, "assistant": assistant, "tools": tools,
            "system": system, "metadata": metadata, "thinking": thinking}

DEFAULT_FILTERSETS: dict[str, dict[str, VisState]] = {
    "1": _fs(_FC, _FC, _H,  _H,  _H,  _H),    # Conversation
    "2": _fs(_SC, _SC, _SC, _SC, _SC, _SC),     # Overview
    "4": _fs(_SC, _SC, _FC, _H,  _H,  _H),     # Tools
    "5": _fs(_SC, _SC, _H,  _FC, _FC, _H),      # System
    "6": _fs(_SC, _SC, _SC, _H,  _FC, _H),      # Cost
    "7": _fs(_FC, _FC, _FC, _FC, _FC, _FC),     # Full Debug
    "8": _fs(_H,  _FC, _H,  _H,  _H,  _H),     # Assistant
    "9": _fs(_SC, _SC, _SC, _H,  _H,  _H),      # Minimal
}


# [LAW:one-source-of-truth] Valid category keys derived from defaults
_VALID_CATEGORY_KEYS = frozenset(next(iter(DEFAULT_FILTERSETS.values())).keys())


def get_filterset(slot: str) -> Optional[dict[str, VisState]]:
    """Return built-in filterset for slot. Logs warning if stale saved data exists."""
    # Check for stale saved data and log clearly
    saved = load_settings().get("filtersets", {}).get(slot)
    if saved is not None:
        saved_keys = {k for k, v in saved.items() if isinstance(v, list) and len(v) == 3}
        if saved_keys != _VALID_CATEGORY_KEYS:
            import logging
            logging.getLogger(__name__).warning(
                "Ignoring stale filterset slot %s: expected keys %s, got %s",
                slot, sorted(_VALID_CATEGORY_KEYS), sorted(saved_keys),
            )
    # [LAW:one-source-of-truth] Always return built-in defaults
    return DEFAULT_FILTERSETS.get(slot)
