"""UI state sidecar I/O for HAR recordings.

// [LAW:one-source-of-truth] HAR is canonical content; sidecar stores UI-only state.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone


def sidecar_path_for_har(har_path: str) -> str:
    """Return sidecar path for a HAR file path."""
    return f"{har_path}.ui.json"


def load_ui_state(har_path: str) -> dict | None:
    """Load sidecar UI state for a HAR path. Returns None when missing/invalid."""
    path = sidecar_path_for_har(har_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def save_ui_state(har_path: str, ui_state: dict) -> str:
    """Atomically persist sidecar UI state next to HAR file.

    Returns the written sidecar path.
    """
    path = sidecar_path_for_har(har_path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    payload = {
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "ui_state": ui_state,
    }

    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return path
