# 12-Item Structural Refactor Execution Plan

Date: 2026-03-04

## Goal
Execute 12 structural refactors in strict order to enforce:
- pure data processing separated from side effects
- side effects pushed to edges
- composable pure functions
- SnarFX reactive local UI rendering for non-performance-critical paths
- reduced extraneous abstractions

## Commit Order
0. docs: add 12-item structural refactor execution plan
1. refactor: decouple view_store from tui error types
2. refactor: drive workbench results from canonical view-store projection
3. refactor: centralize side-channel fallback and error policy in dispatcher
4. refactor: share pure QA preparation between estimate and submit flows
5. refactor: move keys/debug panel visibility to canonical store-driven path
6. refactor: adopt snarfx local reactive rendering for remaining non-critical widgets
7. refactor: separate proxy planning/parsing logic from edge effects
8. refactor: make SSE sink failures explicit while preserving fan-out isolation
9. refactor: remove redundant app wrapper indirection around side-channel flows
10. refactor: centralize coercion helpers and table-drive settings consumer bindings
11. cleanup: remove obsolete update_search_bar compatibility shim
12. refactor: separate session listing presentation from io data access

## Per-Commit Validations
1. `uv run pytest tests/test_exception_handling.py tests/test_view_store_reaction_binding.py tests/test_ui_state_resume.py -q`
   `uv run mypy src/cc_dump/app/view_store.py src/cc_dump/tui/view_store_bridge.py`
2. `uv run pytest tests/test_workbench_results_state.py tests/test_workbench_results_view.py tests/test_textual_panels.py -q`
3. `uv run pytest tests/test_side_channel.py -q`
   `uv run mypy src/cc_dump/ai/data_dispatcher.py`
4. `uv run pytest tests/test_textual_panels.py -k qa -q`
   `uv run pytest tests/test_side_channel_panel.py -q`
5. `uv run pytest tests/test_input_modes.py tests/test_textual_panels.py tests/test_ui_state_resume.py -q`
6. `uv run pytest tests/test_cycle_selector.py tests/test_search.py tests/test_search_controller_shortcuts.py tests/test_textual_panels.py tests/test_input_modes.py -q`
7. `uv run pytest tests/test_proxy_connect.py tests/test_request_envelope.py tests/test_response_assembler.py -q`
8. `uv run pytest tests/test_d6u_smoke_checks.py tests/test_request_envelope.py -q`
9. `uv run pytest tests/test_textual_panels.py tests/test_workbench_results_view.py tests/test_input_modes.py -q`
10. `uv run pytest tests/test_settings_store.py tests/test_side_channel.py -q`
    `uv run mypy src/cc_dump/app/settings_store.py src/cc_dump/ai/side_channel.py src/cc_dump/app/view_store.py`
11. `uv run pytest tests/test_search.py tests/test_search_controller_shortcuts.py -q`
12. `uv run pytest tests/test_cli_run.py tests/test_dump_command.py -q`

## Acceptance Matrix
- No `app -> tui` import coupling in `src/cc_dump/app/*`
- Workbench UI state has one canonical source-of-truth
- Dispatcher fallback/guardrail/error mapping is single-enforced
- QA estimate/submit share one pure preparation pipeline
- Keys/debug panel visibility is canonical in view-store and persisted across resume/hot-reload
- Settings/Search/Keys/CycleSelector use SnarFX local reactive rendering
- Proxy flow separates pure planning from side-effect orchestration
- SSE sink failures are explicit and observable
- Obsolete wrappers/shims removed
- Session listing presentation moved to CLI boundary

## Final Gate
After commit 12:
- `uv run python scripts/quality_gate.py check`
- `uv run pytest`
- `uv run mypy src`
