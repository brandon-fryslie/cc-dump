"""Pytest configuration and shared fixtures for cc-dump hot-reload tests."""

import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from ptydriver import PtyProcess


# ---------------------------------------------------------------------------
# Theme initialization — populate rendering globals before any tests run
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _init_theme():
    """Initialize rendering module globals so unit tests see populated dicts."""
    from textual.theme import BUILTIN_THEMES
    from cc_dump.tui.rendering import set_theme
    set_theme(BUILTIN_THEMES["textual-dark"])


# ---------------------------------------------------------------------------
# Smart wait helpers — replace fixed time.sleep() across test files
# ---------------------------------------------------------------------------

def settle(proc, duration=0.05):
    """Minimal delay after keystroke to let event loop process."""
    time.sleep(duration)
    assert proc.is_alive(), "Process died after keystroke"


def wait_for_content(proc, predicate=None, timeout=3, interval=0.05):
    """Poll until content matches predicate or timeout.

    Args:
        proc: PtyProcess to poll
        predicate: Optional callable(content) -> bool. If None, waits for
                   any non-trivial content (>=10 chars).
        timeout: Max seconds to wait
        interval: Polling interval in seconds

    Returns:
        The content string at the time of match or timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        content = proc.get_content()
        if predicate is None:
            if content and len(content.strip()) >= 10:
                return content
        elif predicate(content):
            return content
        time.sleep(interval)
    return proc.get_content()


# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cc_dump_path():
    """Return absolute path to cc-dump package directory."""
    return Path(__file__).parent.parent / "src" / "cc_dump"



# ---------------------------------------------------------------------------
# File backup/modify helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def backup_file():
    """Context manager to backup and restore a file after modification."""
    backed_up = []

    @contextmanager
    def _backup(filepath):
        """Backup file, yield for modification, then restore."""
        backup_path = filepath + ".backup"
        shutil.copy2(filepath, backup_path)
        backed_up.append((filepath, backup_path))
        try:
            yield filepath
        finally:
            # Restore original file
            shutil.move(backup_path, filepath)
            time.sleep(0.05)

    yield _backup

    # Cleanup any remaining backups
    for original, backup in backed_up:
        if os.path.exists(backup):
            shutil.move(backup, original)


@contextmanager
def modify_file(filepath, modification_fn):
    """Context manager to temporarily modify a file.

    Args:
        filepath: Path to file to modify
        modification_fn: Function that takes file content and returns modified content
    """
    backup_path = str(filepath) + ".temp_backup"
    shutil.copy2(filepath, backup_path)

    try:
        # Read, modify, write
        with open(filepath, "r") as f:
            original_content = f.read()

        modified_content = modification_fn(original_content)

        with open(filepath, "w") as f:
            f.write(modified_content)

        # Wait for filesystem to register the change
        time.sleep(0.05)

        yield filepath

    finally:
        # Restore original
        shutil.move(backup_path, filepath)
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# Internal process launcher (shared by function- and class-scoped fixtures)
# ---------------------------------------------------------------------------

def _launch_cc_dump(port=0, timeout=10):
    """Launch cc-dump and wait for TUI to be ready. Returns (proc, port).

    Uses port 0 by default — the OS assigns a free port, eliminating
    collisions when xdist runs multiple workers in parallel.
    """
    # // [LAW:dataflow-not-control-flow] coalesce None→0 rather than branching
    cmd = ["uv", "run", "cc-dump", "--port", str(port or 0)]

    proc = PtyProcess(cmd, timeout=timeout)

    # Wait for TUI to fully initialize — fast polling at 0.05s.
    # Two-phase: first wait for any content, then wait for footer to render.
    try:
        deadline = time.monotonic() + timeout
        content = ""
        while time.monotonic() < deadline:
            time.sleep(0.05)

            if not proc.is_alive():
                content = proc.get_content()
                raise RuntimeError(f"cc-dump failed to start. Error output:\n{content}")

            content = proc.get_content()
            # Footer keywords indicate the TUI is fully rendered
            if content and any(
                kw in content.lower()
                for kw in ("metadata", "tools", "system", "quit")
            ):
                break
        else:
            raise RuntimeError(
                f"cc-dump started but TUI not fully rendered after {timeout}s. Output:\n{content}"
            )

    except Exception:
        if proc.is_alive():
            proc.terminate()
        raise

    # Extract actual port from startup output (handles port 0 → OS-assigned)
    match = re.search(r"Listening on: http://[\w.]+:(\d+)", content)
    if match:
        port = int(match.group(1))

    return proc, port


def _teardown_proc(proc):
    """Gracefully quit a cc-dump process."""
    if proc.is_alive():
        try:
            proc.send("q", press_enter=False)
            time.sleep(0.1)
            if proc.is_alive():
                proc.terminate()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Function-scoped fixture (original behavior, one process per test)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Class-scoped fixtures (one process shared across all tests in a class)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="class")
def class_proc():
    """One cc-dump process shared across all tests in a class (no port needed)."""
    proc, _port = _launch_cc_dump()
    yield proc
    _teardown_proc(proc)


# ---------------------------------------------------------------------------
# Misc fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_state():
    """Fresh state dict for content tracking."""
    return {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
    }


