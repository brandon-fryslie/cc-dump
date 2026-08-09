"""Behavioral tests for the quality gate's TUI coercion-helper ban.

The gate forbids `cc_dump.core.coerce` usage inside `src/cc_dump/tui` so that TUI
code narrows types explicitly at the seam. These tests assert *what the rule flags*
(the contract), not how it scans — a different implementation of the same contract
must still pass.

// [LAW:behavior-not-structure] Assert the accept/reject contract, not the scan mechanism.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_GATE_PATH = REPO_ROOT / "scripts" / "quality_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("quality_gate", _GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass introspects sys.modules[cls.__module__]; register before executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


@pytest.mark.parametrize(
    "source",
    [
        "from cc_dump.core.coerce import coerce_int\n",
        "import cc_dump.core.coerce\n",
        "value = coerce_int(raw)\n",
        "value = coerce_non_negative_int(raw, default=0)\n",
    ],
)
def test_flags_forbidden_coerce_usage(tmp_path: Path, source: str) -> None:
    (tmp_path / "offender.py").write_text(source, encoding="utf-8")
    result = gate.collect_forbidden_tui_coerce_usage(tui_dir=tmp_path, repo_root=tmp_path)
    assert result == [f"offender.py:1:{source.strip()}"]


@pytest.mark.parametrize(
    "source",
    [
        # Underscore-prefixed method: no word boundary before `coerce`, so it is
        # NOT a forbidden `coerce_...(` call. This is why the live TUI tree passes.
        "def _coerce_non_negative_int(raw):\n    return int(raw)\n",
        "value = self._coerce_non_negative_int(raw)\n",
        "# coercion happens elsewhere\n",
        "coerce = 5\n",
        "from cc_dump.core.other import helper\n",
    ],
)
def test_ignores_lookalikes(tmp_path: Path, source: str) -> None:
    (tmp_path / "clean.py").write_text(source, encoding="utf-8")
    assert gate.collect_forbidden_tui_coerce_usage(tui_dir=tmp_path, repo_root=tmp_path) == []


def test_reports_sorted_across_files(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("import cc_dump.core.coerce\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("value = coerce_int(raw)\n", encoding="utf-8")
    result = gate.collect_forbidden_tui_coerce_usage(tui_dir=tmp_path, repo_root=tmp_path)
    assert result == [
        "a.py:1:value = coerce_int(raw)",
        "b.py:1:import cc_dump.core.coerce",
    ]


def test_live_tui_tree_is_coerce_free() -> None:
    """The rule's premise: current src/cc_dump/tui already narrows types explicitly."""
    assert gate.collect_forbidden_tui_coerce_usage() == []
