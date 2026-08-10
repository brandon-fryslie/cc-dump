# Complexity Audit: cc-dump — Radical Simplification (Cut Lens)

**Date:** 2026-08-09
**Scope:** 89 source files, 30,086 LOC in `src/cc_dump`
**Framing:** The declared core is exactly two things — (1) real-time visualization of Claude Code's traffic, and (2) launching claude. Everything else is a removal candidate. This audit measures *what disappears if a feature is cut*, not how to refactor it in place. Six parallel tracing agents each measured one candidate's full removal blast radius.

---

## Owner constraints (2026-08-09, post-review — these OVERRIDE the ranked list below)

The owner reviewed the first pass and locked the following as **core — DO NOT CUT**:
- **Hot-reload** — kept.
- **SnarfX** — kept; it is the intended observable backbone, meant to be deeply integrated.
- **Search** — kept.
- **The visibility system** (hide/show different data types at detail levels) — core; kept in full.

Consequence: pure feature-deletion, with these protected, totals only **~6,000 LOC (~20% of source)** — see "Revised picture" below. Radical simplification therefore must come from **collapsing accidental complexity inside features that stay**, not from deleting capabilities. Findings #2, #4, #6, #8 below are retained for the record but are NOT actionable as cuts.

## Revised picture (what is actually actionable)

**Safe feature cuts (~6,000 LOC, no capability lost):**
- Multi-provider / non-Anthropic (#1): ~2,900
- Launch-config **editor UI** — not launching claude (#3): ~1,550
- Theme **engine** → one curated theme (#5): ~1,000 + 647 doc lines
- Dead analytics query methods (#9): ~221
- Dev-only chrome panels (debug-settings, keys-help; subset of #7): ~300

**Consolidation (not deletion):** the real-time traffic path (`domain_store`, `analytics_store`, `event_handlers`) currently bypasses snarfx and uses manual `_refresh_*` calls, while the chrome layer is reactive — two update models. If snarfx is to be as core as intended, converge the traffic path onto it and delete the manual refresh plumbing (verify streaming perf first).

**The big prize — implementation collapse in the render layer (capability-preserving, refactor + characterization tests):** keep the entire visibility/search feature set; replace the 86 per-state renderer functions + 94-entry override table in `rendering_impl.py` with generic base-renderer + truncation. Hypothesis, validate with a spike: ~1,500–2,000 LOC removable with zero capability loss. See #2 for the mechanism.

---

## Original bottom line (SUPERSEDED — assumed hot-reload/visibility were cuttable)

A realistic radical simplification removes on the order of **~11,000 LOC** while keeping both core functions — but this assumed hot-reload, snarfx, and the visibility SUMMARY level were on the table. The owner has since protected all three. Retained below for the reasoning and the LOC measurements, not the recommendations.

---

## The cut list, ranked by (LOC removed × distance from core)

| # | Cut | Removable source LOC | Conflicts w/ product decision? | Risk |
|---|-----|----------------------|-------------------------------|------|
| 1 | Multi-provider / non-Anthropic (Copilot, OpenAI, forward-proxy TLS, format translation) | ~2,900 | No | Low |
| 2 | Visibility SUMMARY level (collapse 5 states → 2) | ~1,800–2,400 | **Yes** (declared "core UX model") | High |
| 3 | Launch-config over-generalization (multi-profile CRUD editor) | ~1,550–1,650 | Partial (launching claude stays) | Medium |
| 4 | Hot-reload system | ~1,520 (+~2,800 w/ tests+docs) | **Yes** (declared "core dev workflow") | Medium |
| 5 | Theme engine → one curated theme | ~1,000 + 647 doc lines | No | Low |
| 6 | SnarfX reactive framework | ~1,100 (dependency) + 18-file surface | No | Medium |
| 7 | Peripheral panels + panel_sync framework | ~600–800 | No | Low |
| 8 | Search over-build → basic find | ~600–850 | Partial (search stays, trimmed) | Medium |
| 9 | Dead analytics query methods | ~221 | No | Zero |
| 10 | Per-block/region override machinery | ~300–450 | Partial | Medium |

Numbers overlap where noted below; the ~11k net figure accounts for that.

---

## Detailed findings

### 1. Multi-provider / non-Anthropic support — ~2,900 LOC, safe, biggest clean win

cc-dump only ever needs to proxy `api.anthropic.com`, but ~10% of the tree exists to parameterize over OpenAI/Copilot and translate formats.

- **Deletes outright:** `pipeline/copilot_translate.py` (1,051 — Anthropic↔OpenAI/Copilot translation) and `pipeline/forward_proxy_tls.py` (180 — CA + per-host TLS minting for CONNECT interception).
- **Collapses to a hardcoded Anthropic path:** `providers.py` (~300 of 353), `proxy.py` (~300), `response_assembler.py` (206 — the `OpenAiChatResponseAssembler` half), `formatting_impl.py` (~250), `cli.py` (~150), `proxy_call.py` (~120), `tui/provider_registry.py` (~90), plus ~295 across app/session/analytics/har/launcher/sessions touch-sites.
- **18 provider/mode conditional branches** across proxy/proxy_call/formatting/cli become dead or constant-folded.
- **Abstractions that vanish:** `ProviderSpec` (15-field record), `ProviderEndpointMap`, the `provider_states` dict keying, `Provider`/`ProviderRegistry`, the `make_handler_class` per-provider factory, `ProviderProxyBinding`/`ProxyRuntime`, and five keyed dispatch tables that each degenerate to a single row.
- **Boundary payoff:** `providers.py` is currently imported by ~13 modules (proxy, formatting, TUI, HAR, CLI) — a shared-vocabulary coupling seam. The `provider` string threaded through every event envelope, and the `upstream_format` concern leaking from CLI into the proxy's translation layer, both disappear. `ProxyHandler` becomes a pure reverse proxy.

**Value question for you:** do you use cc-dump to watch Copilot/Codex traffic? If not, this is the single best cut — large, safe, and it un-forks five subsystems.

### 2. Visibility SUMMARY level — ~1,800–2,400 LOC, conflicts with product decision

This is why `rendering_impl.py` is 4,271 lines. Visibility is a `VisState(visible, full, expanded)` triple; the user cycles a category through **5 states** (Hidden → Summary-Collapsed → Summary-Expanded → Full-Collapsed → Full-Expanded). That produces **4 distinct visible renderings per block type**, implemented as:

- `BLOCK_STATE_RENDERERS` — **94 per-(type, visible, full, expanded) override entries**.
- **86 of 150 `_render_*` functions (57%)** are state variants (`*_summary_collapsed`, `*_full_expanded`, etc.).
- The genuinely-core code — the recursive tree walker and render entry — is only ~650 LOC.

Dropping the SUMMARY level entirely, keeping **collapsed (one-line summary) + expanded (full, generically truncated via the 31 base `BLOCK_RENDERERS`)**, deletes most of the 86 variant functions and the 94-entry table. `docs/PRODUCT_DECISIONS.md` declares the 3-level model "the core UX model," so this reopens a product decision — but it is the largest complexity sink in the display layer, and a reader of traffic overwhelmingly wants collapsed-vs-full.

### 3. Launch-config over-generalization — ~1,550–1,650 LOC, launching claude stays

"Launch claude" is core; the current implementation generalized it into a configurable multi-launcher, multi-profile CRUD system.

- **`launch_config_panel.py` (866 LOC) deletes entirely** — it is a full TUI editor for creating/editing/deleting configs and contains *zero* launch logic (its "Launch" button just posts a message).
- **`launch_config.py`:** ~340–370 of 452 is the data model for arbitrary named profiles, cross-tool option schemas, list persistence, and active-name selection. A single hardcoded "launch claude with `ANTHROPIC_BASE_URL` set" needs ~60–90.
- **`launcher_registry.py`:** registers 3 launchers (claude, copilot, codex); ~70–80 of 95 removable.
- **`tmux_controller.py` (488) is mostly core and stays** — the prior audit's dual `_launch_env`/`_port` fallback is already gone. Only ~40–70 LOC of generalized plumbing simplifies; note `set_launch_command`/`set_launch_env`/`set_process_names` are effectively dead (only tests call them).
- **Coupling removed** from `app.py` (~90–110 — command-palette preset loop, config cache, auto-launch name resolution, four panel message handlers), `view_store`, `panel_sync`, footer, and the `run <config-name>` CLI machinery.

Low conflict: you keep launching claude (via a flag or a trivial `run`), you lose the profile editor.

### 4. Hot-reload — ~1,520 source (~2,800 with tests+docs), the keystone

Developer-only; not traffic visualization and not launching claude. It imposes a **codebase-wide tax**:

- **Deletes outright:** `app/hot_reload.py` (325), `tui/hot_reload_controller.py` (604), `tui/protocols.py` (136 — the `HotSwappable` contract exists only to police reload), a stub (17). Plus `test_hot_reload.py` (981) and `HOT_RELOAD_ARCHITECTURE.md` (303).
- **The import tax:** CLAUDE.md mandates stable modules use `import cc_dump.module` (never `from … import …`) to avoid stale references. **41 files** carry this style (150 fully-qualified statements), paid at *every call site*. Removing reload lets all 41 revert to normal imports and shortens every qualified call. The ~90 LOC alias-refresh subsystem (`_refresh_top_level_import_aliases` et al.) that patches stale imports after a reload is pure tax.
- **Scattered state-transfer hooks:** ~440 LOC of `get_state`/`restore_state` (28 methods across 10 files) so every widget/store can be recreated and rehydrated across a reload. Includes ~203 LOC in `analytics_store.py` (966–1169) and ~205 across the panels.
- **The 43-module hand-sorted `_RELOAD_ORDER`** and the stable-vs-reloadable classification discipline vanish.
- **Dependency drop:** `watchfiles` becomes unused.

The tax refund is the real prize: stores become plain `Store`s, widgets lose the serialization contract, and imports normalize across the whole codebase. Conflicts with `PRODUCT_DECISIONS.md` ("core dev workflow. Import discipline cost is accepted.") — your call, but the cost is far larger than that note implies.

### 5. Theme engine → one theme — ~1,000 LOC + 647 doc lines, safe

cc-dump defines **zero custom themes** — `cycle_theme` cycles Textual's *built-in* themes. But the home-grown adaptation layer is large: `core/palette.py` (467 — an HSL palette generator with golden-angle hue spacing and a 38-color ramp), `build_theme_colors()` (~111) mapping arbitrary themes to internal colors with ANSI special-casing, and three `docs/THEME_*.md` files (647 lines). Ship one hand-picked palette and delete the generator, cycling, markdown-theme push/pop, and the docs.

### 6. SnarfX reactive framework — ~1,100 LOC dependency, mostly unlocked by cutting hot-reload

The custom MobX-style library is over-engineered for this app, and both core functions already run without it: `domain_store.py` (the actual traffic model), `analytics_store.py`, and the `event_handlers` hot path are **plain Python + explicit `_refresh_*()` calls** — zero snarfx. SnarfX decorates only view/chrome state.

- **~24 of ~29 reaction sites (15 of 17 Observables)** are the shallow "one Observable, one reaction, re-render" pattern — behaviorally identical to a setter that calls `refresh()`. Replaceable mechanically, removing ~15 files' dependency.
- **Genuinely dependency-tracked:** exactly one place — `view_store.py`'s footer/chrome projection (7 `@computed` + fan-out), which suppresses redundant re-renders across ~26 inputs. Hand-rollable as one diff-and-refresh function, but a real (small) reimplementation.
- **Keep in some form:** ~50 lines of the `snarfx/textual.py` bridge (thread-marshal, `NoMatches` guard, teardown safety) — any background-thread refresh needs that.
- **Much of the snarfx-shaped complexity is hot-reload's:** `HotReloadStore`/`reconcile`, the `create()`/`setup_reactions()` split, `stx.pause()`, and the "store strings not enums because enum identity changes on reload" contortion all exist for reload survival. Cut #4 first and this shrinks dramatically.

### 7. Peripheral panels + panel_sync framework — ~600–800 LOC, low conflict

Cuttable: `debug_settings_panel.py` (152, dev-only toggles), `keys_panel.py` (88, keyboard help), and the `panel_sync.py` (310) data-driven panel-lifecycle *engine* — heavier than directly mounting the 2–3 panels that actually matter (stats, launch, session). Keep the stats/cost panel (core to traffic analysis).

### 8. Search → basic find — ~600–850 LOC, trim not remove

1,102 LOC across `search.py` + `search_controller.py` for what a reader uses as "find": a `SearchMode` IntFlag (case/word/**regex**/**incremental**), a bounded-LRU `SearchTextCache` with owner-based invalidation (~80), a 3-phase state machine, word-wise cursor motion, debounced incremental scheduling, and a multi-line `SearchBar` with mode/toggle/nav help. Basic case-insensitive find with next/prev is ~150–250 LOC. Note: the `navigate_next/prev/to_current` nav is thinner than its UI implies (prior-audit stub finding confirmed).

### 9. Dead analytics query methods — ~221 LOC, zero risk

`get_session_stats`, `get_latest_turn_stats`, `get_turn_timeline`, `get_turn_metrics_snapshot`, `get_tool_economics` are defined but called only from tests — no panel renders them. `get_dashboard_snapshot` (the one live consumer, read via the view store) does not call them internally. Delete now, independent of everything else. **Note:** the earlier premise of a "SQLite content-addressed blob store" is stale — that was already removed; analytics is pure in-memory.

### 10. Per-block/region override machinery — ~300–450 LOC, partial overlap with #2

`view_overrides.py` (224) plus `_render_region_parts` (~150) support per-individual-block and per-sub-region expand/collapse with per-kind heuristics (code-fence/XML/markdown default-expansion), on top of whole-category toggles. For reading traffic, whole-category toggles plus a single block-expand suffice. Largely subsumed if #2 lands.

---

## Dependency graph among the cuts (sequencing)

```
Cut #4 Hot-reload  ──unlocks──▶  #6 SnarfX shrinks (HotReloadStore/reconcile/pause gone)
                   ──unlocks──▶  ~440 LOC get_state/restore_state hooks deletable
                   ──unlocks──▶  41 files revert to normal imports (tax refund)
                   ──unlocks──▶  ~203 LOC analytics serialization deletable

Cut #2 Visibility  ──subsumes──▶ #10 per-block/region overrides

Cut #1 Provider    ── independent, largest clean win, un-forks 13 modules
Cut #3 Launch      ── independent (keeps launching claude)
Cut #5 Theme       ── independent
Cut #9 Dead queries── independent, zero risk, do immediately
```

**Recommended order (revised for owner constraints):**
1. **#9 dead analytics queries** — zero risk, immediate.
2. **#1 multi-provider** — biggest safe win (if you don't watch Copilot/Codex).
3. **#5 theme engine → one theme, #3 launch editor UI, dev-only chrome panels** — safe, no capability lost.
4. **Consolidation:** converge the traffic path onto snarfx, delete manual `_refresh_*` (verify streaming perf first).
5. **Render-layer implementation collapse (#2 mechanism, feature preserved):** spike on 2–3 block types to validate the generic-renderer + truncation hypothesis, then collapse the 86-variant matrix. Highest LOC prize inside the kept feature set; needs characterization tests.

Hot-reload (#4), snarfx removal (#6), search removal (#8), and cutting the visibility feature (#2 as a cut) are OFF the table per owner constraints.
