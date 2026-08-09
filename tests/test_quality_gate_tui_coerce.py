"""Behavioral tests for the quality gate's TUI coercion-helper ban.

The gate forbids importing `cc_dump.core.coerce` inside `src/cc_dump/tui` so that
TUI code narrows types explicitly at the seam. Detection is import-based: the import
is the necessary gateway to the coerce helpers, so flagging it covers every call
site without scanning call sites at all. These tests assert *what the rule flags*
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
        # Every import form that grants access to the coerce helpers is flagged.
        "from cc_dump.core.coerce import coerce_int\n",
        "import cc_dump.core.coerce\n",
        "import cc_dump.core.coerce as c\n",
        # `from cc_dump.core import coerce` — module string is `cc_dump.core`, so it
        # would slip a naive `module == "cc_dump.core.coerce"` check; caught here.
        "from cc_dump.core import coerce\n",
        # Star imports that can pull the coerce module into scope.
        "from cc_dump.core.coerce import *\n",
        "from cc_dump.core import *\n",
    ],
)
def test_flags_forbidden_coerce_import(tmp_path: Path, source: str) -> None:
    (tmp_path / "offender.py").write_text(source, encoding="utf-8")
    result = gate.collect_forbidden_tui_coerce_usage(tui_dir=tmp_path, repo_root=tmp_path)
    assert result == [f"offender.py:1:{source.strip()}"]


@pytest.mark.parametrize(
    "source",
    [
        # Relative imports resolve against the file's package (cc_dump.tui) up to
        # cc_dump.core.coerce — the same target as the absolute forms.
        "from ..core.coerce import coerce_int\n",
        "from ..core import coerce\n",
    ],
)
def test_flags_relative_coerce_import(tmp_path: Path, source: str) -> None:
    tui = tmp_path / "src" / "cc_dump" / "tui"
    tui.mkdir(parents=True)
    (tui / "widget.py").write_text(source, encoding="utf-8")
    result = gate.collect_forbidden_tui_coerce_usage(tui_dir=tui, repo_root=tmp_path)
    assert result == [f"src/cc_dump/tui/widget.py:1:{source.strip()}"]


def test_ignores_unrelated_relative_import(tmp_path: Path) -> None:
    """A relative import of a sibling that is not the coerce module is not flagged."""
    tui = tmp_path / "src" / "cc_dump" / "tui"
    tui.mkdir(parents=True)
    (tui / "widget.py").write_text("from ..core import formatting\n", encoding="utf-8")
    assert gate.collect_forbidden_tui_coerce_usage(tui_dir=tui, repo_root=tmp_path) == []


def test_flags_the_import_not_the_call_site(tmp_path: Path) -> None:
    """A qualified coerce call is caught via its import, and only the import line."""
    (tmp_path / "multi.py").write_text(
        "from cc_dump.core import coerce\nvalue = coerce.coerce_int(raw)\n",
        encoding="utf-8",
    )
    result = gate.collect_forbidden_tui_coerce_usage(tui_dir=tmp_path, repo_root=tmp_path)
    assert result == ["multi.py:1:from cc_dump.core import coerce"]


@pytest.mark.parametrize(
    "source",
    [
        # Underscore-prefixed helper: a legitimate local narrower, no coerce import.
        "def _coerce_non_negative_int(raw):\n    return int(raw)\n",
        "value = self._coerce_non_negative_int(raw)\n",
        "coerce = 5\n",
        "from cc_dump.core.other import helper\n",
        # Parent-package import of a *different* name — not the coerce module.
        "from cc_dump.core import formatting\n",
        # A bare coerce-shaped call with no import is not a coerce-module dependency.
        "value = coerce_int(raw)\n",
        "handler = coerce_int\n",
    ],
)
def test_ignores_lookalikes(tmp_path: Path, source: str) -> None:
    (tmp_path / "clean.py").write_text(source, encoding="utf-8")
    assert gate.collect_forbidden_tui_coerce_usage(tui_dir=tmp_path, repo_root=tmp_path) == []


def test_ignores_local_coerce_method_without_import(tmp_path: Path) -> None:
    """A local `coerce_int` method on a widget (no coerce import) is not flagged.

    Guards the exact false positive a call-site scan would produce: `self.coerce_int`
    names a method, not the banned module helper.
    """
    (tmp_path / "widget.py").write_text(
        "class Widget:\n"
        "    def coerce_int(self, raw):\n"
        "        return int(raw)\n"
        "\n"
        "    def use(self, raw):\n"
        "        return self.coerce_int(raw)\n",
        encoding="utf-8",
    )
    assert gate.collect_forbidden_tui_coerce_usage(tui_dir=tmp_path, repo_root=tmp_path) == []


@pytest.mark.parametrize(
    "source",
    [
        # A coerce mention in text is never an import, so it is never a violation.
        "# Consider coerce_int(raw) but narrow explicitly instead\n",
        '"""Narrow explicitly rather than importing cc_dump.core.coerce."""\n',
        'x = "from cc_dump.core.coerce import coerce_int"\n',
        'label = f"coerce_int({value}) is banned"\n',
    ],
)
def test_ignores_coerce_in_comments_and_strings(tmp_path: Path, source: str) -> None:
    """A coerce mention in a comment/docstring/string literal is not an import.

    Regression guard for the code-vs-text distinction: a raw-text scan would flag
    these; an AST import scan correctly does not, because no import node exists.
    """
    (tmp_path / "documented.py").write_text(source, encoding="utf-8")
    assert gate.collect_forbidden_tui_coerce_usage(tui_dir=tmp_path, repo_root=tmp_path) == []


def test_reports_sorted_across_files(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("import cc_dump.core.coerce\n", encoding="utf-8")
    (tmp_path / "a.py").write_text(
        "from cc_dump.core.coerce import coerce_int\n", encoding="utf-8"
    )
    result = gate.collect_forbidden_tui_coerce_usage(tui_dir=tmp_path, repo_root=tmp_path)
    assert result == [
        "a.py:1:from cc_dump.core.coerce import coerce_int",
        "b.py:1:import cc_dump.core.coerce",
    ]


def test_live_tui_tree_is_coerce_free() -> None:
    """The rule's premise: current src/cc_dump/tui already narrows types explicitly."""
    assert gate.collect_forbidden_tui_coerce_usage() == []
