# Proxy Plugin API

// [LAW:one-source-of-truth] This document is the canonical contract for pluggable proxy providers.

## Goals

- Provider complexity is isolated from core proxy pipeline code.
- Provider failures are contained and cannot crash `cc-dump`.
- Provider settings are declared by providers and rendered by `cc-dump` generically.
- Core `cc-dump` code does not depend on provider internals.

## Contract

Defined in `/Users/bmf/code/cc-dump/src/cc_dump/proxies/plugin_api.py`.

### `ProxySettingDescriptor`

Provider-declared setting metadata:

- `key`
- `label`
- `description`
- `kind`: `text | bool | select`
- `default`
- `options` (for `select`)
- `secret`
- `env_vars`

### `ProxyProviderDescriptor`

- `provider_id`
- `display_name`
- `settings` (tuple of `ProxySettingDescriptor`)

### `ProxyRequestContext`

Runtime context passed from core pipeline to plugin handler:

- `request_id`
- `request_path`
- `request_body`
- `method`
- `request_headers`
- `runtime_snapshot`
- `handler`
- `event_queue`
- `safe_headers`

### `ProxyProviderPlugin`

Required plugin API:

1. `descriptor` property
2. `handles_path(request_path) -> bool`
3. `expects_json_body(request_path) -> bool`
4. `handle_request(context) -> bool`

`handle_request` returns:

- `True`: plugin handled request/response lifecycle
- `False`: core pipeline should continue default upstream behavior

### Plugin module contract

Each plugin package must expose a factory in
`/Users/bmf/code/cc-dump/src/cc_dump/proxies/<provider>/plugin.py`:

- `create_plugin() -> ProxyProviderPlugin`

Registry discovery is file-system driven (`*/plugin.py`) and does not hardcode provider imports.

### Optional auth capability

`ProxyAuthCapablePlugin`:

- `run_auth_flow(force: bool) -> ProxyAuthResult`

## Core Integration Points

### Registry

`/Users/bmf/code/cc-dump/src/cc_dump/proxies/registry.py`

- Single registration point for provider descriptors and plugins
- Generic plugin discovery via `create_plugin()` factories
- Descriptor-driven env override application
- Provider lookup for runtime dispatch
- Import/factory failures are contained and exposed through `plugin_load_errors()`

### Runtime

`/Users/bmf/code/cc-dump/src/cc_dump/proxies/runtime.py`

- Stores one canonical provider + settings snapshot
- Exposes provider-agnostic setting accessors
- Computes active base URL generically

### Settings

- Schema assembly: `/Users/bmf/code/cc-dump/src/cc_dump/app/settings_store.py`
- UI field assembly: `/Users/bmf/code/cc-dump/src/cc_dump/tui/settings_panel.py`

Both consume provider descriptors; no provider-specific field wiring exists in core code.

### Proxy pipeline

`/Users/bmf/code/cc-dump/src/cc_dump/pipeline/proxy.py`

- Looks up active provider plugin by `provider_id`
- Delegates by contract only
- Wraps plugin invocation in hard exception boundary

// [LAW:single-enforcer] Plugin crash containment is enforced at this one dispatch boundary.

## Conformance

### `cc-dump` core conformance

- Uses registry/provider descriptor APIs for provider settings and env overrides.
- Uses plugin API (`handles_path`, `expects_json_body`, `handle_request`) for request handling.
- Contains plugin failures to isolated 502 responses.
- Contains plugin load-time failures in registry bootstrap (app still starts with healthy providers).

### Copilot plugin conformance

`/Users/bmf/code/cc-dump/src/cc_dump/proxies/copilot/plugin.py` implements:

- `descriptor`
- `handles_path`
- `expects_json_body`
- `handle_request`
- `run_auth_flow` (optional auth capability)
- `create_plugin` (required discovery factory)

## Verification

- Contract/registry tests:
  - `/Users/bmf/code/cc-dump/tests/test_proxy_registry.py`
  - `/Users/bmf/code/cc-dump/tests/test_proxy_plugin_boundary.py`
- Copilot route contract tests:
  - `/Users/bmf/code/cc-dump/tests/test_copilot_proxy_routes.py`
