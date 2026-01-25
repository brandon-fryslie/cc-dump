"""Pytest configuration and shared fixtures for cc-dump hot-reload tests."""

import os
import random
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from ptydriver import PtyProcess


@pytest.fixture
def cc_dump_path():
    """Return absolute path to cc-dump package directory."""
    return Path(__file__).parent.parent / "src" / "cc_dump"


@pytest.fixture
def formatting_py(cc_dump_path):
    """Return path to formatting.py."""
    return cc_dump_path / "formatting.py"


@pytest.fixture
def proxy_py(cc_dump_path):
    """Return path to proxy.py."""
    return cc_dump_path / "proxy.py"


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
            # Wait a moment for filesystem to settle
            time.sleep(0.1)

    yield _backup

    # Cleanup any remaining backups
    for original, backup in backed_up:
        if os.path.exists(backup):
            shutil.move(backup, original)


@pytest.fixture
def start_cc_dump():
    """Factory fixture to start cc-dump TUI and return PtyProcess."""
    processes = []

    def _start(port=None, timeout=10):
        """Start cc-dump on specified port and wait for it to be ready.

        Args:
            port: Port number to use (None = random port between 10000-60000)
            timeout: Timeout in seconds for startup
        """
        if port is None:
            # Use a random port to avoid conflicts
            port = random.randint(10000, 60000)

        # Use uv run to execute in the project's virtual environment
        proc = PtyProcess(["uv", "run", "cc-dump", "--port", str(port), "--no-db"], timeout=timeout)
        processes.append(proc)

        # Wait for TUI to initialize - look for header or footer
        # The TUI displays various elements, we just need to see it's running
        try:
            # Wait a bit for initial startup
            time.sleep(1.5)

            # Check if process is alive
            if not proc.is_alive():
                content = proc.get_content()
                raise RuntimeError(f"cc-dump failed to start. Error output:\n{content}")

            # Try to find some recognizable content
            content = proc.get_content()
            # Textual apps may show various elements, just verify we have output
            if not content or len(content.strip()) < 10:
                raise RuntimeError(f"cc-dump started but no TUI content visible. Output:\n{content}")

        except Exception as e:
            if proc.is_alive():
                proc.terminate()
            raise

        # Give it a moment to fully stabilize
        time.sleep(0.3)
        return proc

    yield _start

    # Cleanup: quit all processes
    for proc in processes:
        if proc.is_alive():
            try:
                proc.send("q", press_enter=False)
                time.sleep(0.3)
                if proc.is_alive():
                    proc.terminate()
            except Exception:
                pass


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
        time.sleep(0.2)

        yield filepath

    finally:
        # Restore original
        shutil.move(backup_path, filepath)
        time.sleep(0.1)
