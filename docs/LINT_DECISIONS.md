# Lint Decisions

Why the ruff configuration in `pyproject.toml` looks the way it does. Read this before
changing `[tool.ruff.lint]` or "cleaning up" an ignore — each entry here is a deliberate
decision with a rationale, not leftover debt.

## Ruff and radon are pinned exactly

`ruff==0.16.0` and `radon==6.0.1` are pinned in `[dependency-groups] dev` and locked in
`uv.lock`. The quality gate (`scripts/quality_gate.py`) invokes them via `uv run ruff` /
`uv run radon` — **not** `uv run --with ruff`, which would re-resolve the latest PyPI
release on every run.

This matters because the lint job is a **required, merge-blocking** status check. An
unpinned linter is a clock with no hands: ruff's *default* ruleset grew from ~122 rules
(E/F only, in 0.14.x) to ~830 rules in 0.16.0, so an unchanged `src/` that reported 0
diagnostics under one machine's ruff suddenly reported ~500 under CI's newer ruff. Pinning
makes "0 lint errors" a reproducible fact instead of an accident of release timing. Bumping
either tool is now a deliberate, reviewable change that re-runs the gate on purpose.

## `ignore = ["BLE001"]` — blind-except is disabled on purpose

`BLE001` flags every `except Exception`. In this codebase that rule fights a deliberate,
pervasive architectural pattern, so it is disabled globally.

cc-dump is a live monitoring proxy plus TUI. Its core product promise is **never crash the
thing you are monitoring**. It delivers that by isolating failures at boundaries and
*reporting* them (`[LAW:effects-at-boundaries]`, `[LAW:single-enforcer]`): SSE sink
dispatch, tmux/libtmux calls, hot-reload of arbitrary reloaded module code, per-connection
proxy handlers, and replay/event processing each wrap their work in `except Exception` that
logs (or recovers into a known state) and continues. Catching `Exception` is the *correct
contract* at these boundaries — the entire point is to contain **any** failure, including
exception types a hand-written narrow tuple could never anticipate. Narrowing them would let
one unforeseen exception crash the live proxy mid-session, which is strictly worse than a
logged warning.

Every one of the 44 sites that triggered BLE001 was audited: all log or transition to a
defined state; none swallow silently.

**This does not mean silent swallows are allowed.** A genuinely silent `except: pass` is a
different smell caught by a *different, still-enabled* rule — `S110` (try-except-pass). All
`S110` sites were fixed for real: narrowed to the specific expected exception via
`contextlib.suppress(<Type>)` where the failure is a known no-op (e.g. `OSError` on a socket
close during teardown, `ThemeStackError` when popping an empty theme stack), or converted
from `pass` to a `logger.debug/warning(...)` so the failure is observable.

If you are tempted to re-enable BLE001, you must first replace the boundary-isolation design
— don't just narrow 44 catch sites and hope you enumerated every exception each boundary can
see.

## `per-file-ignores` — scoped exceptions where a rule doesn't fit a pattern

Scoped ignores are preferred over global ones: the rule stays enforced everywhere else.

- **`src/cc_dump/pipeline/har_recorder.py = ["SIM115"]`** — `SIM115` wants file `open()`
  calls wrapped in a `with` block. `HarRecorder` owns a single streaming HAR file handle for
  its entire lifetime (opened in lazy-init, appended to across many events, closed in
  `close()`). That is a legitimate long-lived resource holder, like a logging `FileHandler`,
  where a lexical `with` does not apply. SIM115 stays enforced in every other file.

## What was NOT done

- No `# noqa` comments were added. Every diagnostic was either fixed for real or resolved by
  one of the documented, deliberate configuration decisions above.
- The 0-tolerance lint baseline (`.quality_gate/lint_baseline.json`, empty) was **not**
  widened. The goal is 0 lint diagnostics across `src/` and `tests/`, and that is what the
  gate enforces.
