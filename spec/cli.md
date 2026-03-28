# CLI Interface Specification

## Why This Exists

Claude Code is opaque. Users cannot see the system prompts, tool definitions, token usage, or caching behavior behind their conversations. cc-dump makes all of this visible by sitting between the user's tool and the API provider. The CLI is the entry point for all of this: it configures and starts the proxy, manages recordings, and optionally auto-launches the monitored tool via tmux.

The CLI must be zero-configuration by default (bind to a random port, start recording, show the TUI) while supporting power-user workflows (replay sessions, manage recordings, auto-launch named configs with extra args).

---

## Entry Points

Two console scripts are registered in `pyproject.toml`:

| Script | Module | Purpose |
|--------|--------|---------|
| `cc-dump` | `cc_dump.cli:main` | Primary entry point: proxy + TUI |
| `cc-dump-serve` | `cc_dump.serve:main` | Browser-based TUI via textual-serve |

Both can also be invoked as modules:

```
python -m cc_dump          # equivalent to cc-dump (invokes cc_dump.__main__)
uv run cc-dump             # via uv
just run [args]            # via justfile
```

---

## Command Grammar

```
cc-dump [FLAGS...]
cc-dump run <config-name> [FLAGS...] [-- tool-extra-args...]
cc-dump --list-recordings
cc-dump --cleanup-recordings [N] [--cleanup-dry-run]
```

### `run` Subcommand

`cc-dump run <config-name>` starts cc-dump and immediately auto-launches the named launch configuration (defined in `settings.json`). The config supplies the launcher, command, model, shell wrapper, and options.

- Arguments after `--` are appended to the config's `extra_args` option for this invocation only (not persisted). The merge uses `shlex.join` on the extra args and concatenates with any existing `extra_args` value.
- All standard cc-dump flags can appear between `<config-name>` and `--`.

```
cc-dump run claude                           # launch with "claude" config
cc-dump run claude --port 5000               # pin proxy port
cc-dump run claude -- --dangerously-bypass-permissions
cc-dump run haiku --port 5000 -- --continue
```

If `<config-name>` does not match a saved config, the process prints available config names to stderr and exits with code 2.

`cc-dump run` with no config name, `cc-dump run -h`, and `cc-dump run --help` all print subcommand usage to stdout and exit 0.

#### Run subcommand parsing

`_detect_run_subcommand` runs before argparse. It extracts three components from `sys.argv[1:]`:
1. Config name (first positional after `run`)
2. cc-dump flags (everything between config name and `--`)
3. Tool extra args (everything after `--`)

The cc-dump flags are passed to argparse. The config name and extra args are carried separately and applied later.

---

## Flags

### Network

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--host` | `str` | `127.0.0.1` | Bind address for proxy servers |
| `--port` | `int` | `0` | Bind port for default (Anthropic) proxy. `0` = OS-assigned |
| `--target` | `str` | `$ANTHROPIC_BASE_URL` or `https://api.anthropic.com` | Upstream API URL for default reverse proxy |

### Recording

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--record` | `str` | `None` | HAR recording output directory. Default dir: `~/.local/share/cc-dump/recordings/`. If a `.har` path is given, its parent directory is used. If an existing directory is given, it is used directly. Otherwise, the value is treated as a directory path |
| `--no-record` | `bool` | `False` | Disable HAR recording entirely |
| `--replay` | `str` | `None` | Replay a recorded session from a `.har` file path |
| `--continue` | `bool` | `False` | Find the latest recording, set it as `--replay`, and print "Continuing from: <path>". The proxy runs live simultaneously |
| `--resume` | `str?` | `None` | Find a recording to replay. No argument = latest recording. Optional path to specific `.har` file. Prints "Resuming from: <path>" |

#### `--continue` vs `--resume`

Both flags set `args.replay` to a recording path and leave the live proxy running. They are functionally identical — the proxy always starts regardless. The only differences are:

1. **Print message:** `--resume` prints `"🔄 Resuming from: <path>"`, `--continue` prints `"🔄 Continuing from: <path>"`.
2. **Argument:** `--resume` accepts an optional path argument; `--continue` always uses the latest recording.
3. **Processing order:** `--resume` is applied first. If both are specified, `--continue` overwrites `args.replay` with the latest recording.

If no recording is found, both print a message to stdout and return (exit code 0).

### Recording Administration

These flags execute a one-shot command and exit (no TUI, no proxy).

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--list-recordings` | `bool` | `False` | List known HAR recordings and exit |
| `--cleanup-recordings` | `int?` | `None` | Delete older recordings, keeping newest N (default: 20), and exit |
| `--cleanup-dry-run` | `bool` | `False` | Preview cleanup without deleting. Only meaningful with `--cleanup-recordings` |

`--list-recordings` output is rendered by `cli_presentation.render_recordings_list()` — a pure function that formats a table with columns: SESSION, PROVIDER, CREATED, ENTRIES, SIZE, FILE. Note: the SESSION column always shows `"(flat)"` because `session_name` is never populated in the recording metadata.

`--cleanup-recordings` output is formatted inline in `_handle_recording_admin_commands()` and includes the mode (dry run or cleanup), count of removed/kept recordings, bytes freed, and removed file paths.

### Optional Provider Proxies

For each optional provider (currently `openai` and `copilot`), the following flags are dynamically generated from the provider registry (`providers.optional_proxy_provider_specs()`):

| Flag pattern | Type | Default | Description |
|---|---|---|---|
| `--<key>-port` | `int` | `0` | Bind port for this provider's proxy. `0` = OS-assigned |
| `--<key>-target` | `str` | Provider-specific default | Upstream URL for this provider |
| `--no-<key>` | `bool` | `False` | Disable this provider's proxy server entirely |

Current optional providers:

| Key | Display Name | Proxy Mode | Default Target | Env Var for Target | Env Var Affects Default? |
|-----|-------------|------------|----------------|---------------------|------------------------|
| `openai` | OpenAI | reverse | `https://api.openai.com/v1` | `OPENAI_BASE_URL` | Yes |
| `copilot` | Copilot | forward | `https://api.githubcopilot.com` | `COPILOT_PROXY_URL` | No (forward proxy targets ignore env override) |

**Note on env var target defaults:** Only reverse-proxy providers read their `base_url_env` as the argparse default for `--<key>-target`. Forward-proxy providers always use `spec.default_target` as the argparse default, because the target for forward proxies is determined by the CONNECT tunnel, not the CLI flag.

### Forward Proxy TLS

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--forward-proxy-ca-dir` | `str` | `None` | Directory for forward proxy CA key/cert. CLI default is `None`; actual default (`~/.cc-dump/forward-proxy-ca/`) is provided by the `ForwardProxyCertificateAuthority` class when the CLI value is `None` |

This is only relevant when at least one active provider uses forward proxy mode (currently `copilot`). The CA is created on first use and its cert path is passed to launched tools via `NODE_EXTRA_CA_CERTS`.

---

## Environment Variables

### Provider Target URLs

These override the `--target` / `--<key>-target` defaults for reverse-proxy providers only. They are read once at argument parsing time and become the argparse default for their respective flag.

| Variable | Affects | Default when unset |
|----------|---------|-------------------|
| `ANTHROPIC_BASE_URL` | `--target` (default provider) | `https://api.anthropic.com` |
| `OPENAI_BASE_URL` | `--openai-target` | `https://api.openai.com/v1` |

`COPILOT_PROXY_URL` is declared in the provider spec (`base_url_env`) but is **not** read as a CLI default because copilot uses forward proxy mode. It may be relevant to the launched tool's own environment.

### Logging

| Variable | Purpose | Default |
|----------|---------|---------|
| `CC_DUMP_LOG_LEVEL` | Log level for `cc_dump` logger hierarchy (parsed via `logging.getLevelName`) | `INFO` |
| `CC_DUMP_LOG_FILE` | Explicit log file path | `~/.local/share/cc-dump/logs/cc-dump-<YYYYMMDD-HHMMSS>-<pid>.log` |
| `CC_DUMP_LOG_DIR` | Directory for auto-generated log files (ignored when `CC_DUMP_LOG_FILE` is set) | `~/.local/share/cc-dump/logs` |

Log file uses `RotatingFileHandler` with 20MB max size and 5 backups.

### Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `XDG_CONFIG_HOME` | Base directory for `settings.json` | `~/.config` |

Settings file location: `$XDG_CONFIG_HOME/cc-dump/settings.json`

### Tmux Detection

| Variable | Purpose |
|----------|---------|
| `TMUX` | Presence indicates cc-dump is running inside tmux. When absent, tmux integration is disabled |

### Proxy Environment (set for launched tools)

These are not read by cc-dump itself; they are set in the environment of tools launched via tmux integration. Documented here because they are part of the CLI contract.

**Reverse proxy providers** (anthropic, openai):

| Variable | Value |
|----------|-------|
| `ANTHROPIC_BASE_URL` | `http://<host>:<port>` (anthropic provider) |
| `OPENAI_BASE_URL` | `http://<host>:<port>` (openai provider) |

**Forward proxy providers** (copilot):

| Variable | Value |
|----------|-------|
| `HTTP_PROXY` | `http://<host>:<port>` |
| `HTTPS_PROXY` | `http://<host>:<port>` |
| `NODE_EXTRA_CA_CERTS` | Path to CA cert (when forward proxy CA is active) |

The env var mapping is derived from `ProviderEndpoint.proxy_mode` by `providers._provider_proxy_env_items()`. Reverse-mode endpoints set the provider's `base_url_env`. Forward-mode endpoints set `HTTP_PROXY`/`HTTPS_PROXY` and optionally `NODE_EXTRA_CA_CERTS`.

---

## Startup Sequence

The `main()` function in `cli.py` follows this sequence:

### 1. Parse `run` subcommand

Before argparse runs, `_detect_run_subcommand` extracts the optional `run <config-name>` prefix and any `-- tool-extra-args` from `sys.argv[1:]`. The remaining flags are passed to argparse.

### 2. Build and parse CLI arguments

The argument parser is built dynamically from the provider registry. Each optional provider contributes `--<key>-port`, `--<key>-target`, and `--no-<key>` flags. Reverse-proxy provider target defaults incorporate environment variable overrides at parse time; forward-proxy providers use their static `default_target`.

### 3. Validate `run` config name

If `run` was specified, the named config is looked up in `settings.json` via `launch_config.load_configs()`. Unknown names print available configs to stderr and exit with code 2.

### 4. Install stderr tee

`cc_dump.io.stderr_tee.install()` captures stderr output for later display in the TUI's error log. This runs before logging configuration, so all stderr output from this point forward is captured. Idempotent.

### 5. Configure logging

`cc_dump.io.logging_setup.configure()` sets up the `cc_dump` logger hierarchy with:
- A stderr handler (filtered to exclude in-app-only records via the `cc_dump_in_app` attribute)
- A rotating file handler (20MB max, 5 backups)

Level and path are derived from environment variables (see above). Third-party loggers are capped at WARNING. Python warnings are captured. Idempotent.

### 6. Initialize color palette

`cc_dump.core.palette.init_palette()` sets up the color scheme before any rendering code runs.

### 7. Handle recording admin commands (early exit)

If `--list-recordings` or `--cleanup-recordings` was passed, execute the command, print output, and return. No proxy, no TUI.

### 8. Resolve `--resume` and `--continue`

Both flags resolve to a `--replay` path. Applied in order:
1. `_apply_resume_argument`: `--resume` (no arg) finds the latest recording; `--resume <path>` uses the given path. Prints to stdout.
2. `_apply_continue_argument`: `--continue` finds the latest recording. Prints to stdout.

If no recording is found, prints a message to stdout and returns (exit code 0).

### 9. Load replay data

If `--replay` is set (directly or via resume/continue), load and parse the HAR file via `har_replayer.load_har()`. Prints entry count. On parse failure, prints error and returns (exit code 0).

### 10. Start proxy servers

`_build_proxy_runtime()` creates a `ProxyRuntime` containing all active provider bindings:

1. Determine active providers: default provider + optional providers not disabled by `--no-<key>`
2. Create forward proxy CA if any active provider uses forward proxy mode
3. For each active provider:
   a. Create a `ProxyHandler` subclass via `make_handler_class()` parameterized with provider key, target, and event queue
   b. Bind a `ThreadingHTTPServer` to the configured host/port
   c. Start serving in a daemon thread
   d. Build `ProviderEndpoint` metadata from the actual bound port

Print startup banner with endpoint details and usage hints for each provider.

### 11. Wire event pipeline

1. Create `EventRouter` with the shared event queue
2. Add `AnalyticsStore` as a `DirectSubscriber` (processes events inline before fan-out)
3. Add a `QueueSubscriber` for the TUI display
4. Create `HARRecordingSubscriber` for each active provider (unless `--no-record`), each filtering to its provider key
5. (Router is not started yet — started in step 14)

### 12. Create settings store and build tmux controller

1. Create `SettingsStore` (reactive, hot-reloadable)
2. If running inside tmux and `libtmux` is installed:
   - Load the active launch config from `settings.json`
   - Build a `LaunchProfile` with the resolved command, process names, and proxy environment
   - Create a `TmuxController` with launch capability
3. Print tmux status (enabled/disabled and why)

### 13. Set up request pipeline

Create a `RequestPipeline` with interceptors (currently: sentinel interceptor for tmux state tracking). Assign the shared pipeline to all provider handler classes.

### 14. Start event router

`router.start()` begins draining the event queue on its own thread.

### 15. Create stores

- `ViewStore` (reactive, hot-reloadable)
- `DomainStore` (owns FormattedBlock trees, persists across hot-reload)

### 16. Wire settings store reactions

Build base store context (tmux controller, settings store, view store) and wire reactions on the settings store.

### 17. Initialize hot-reload watcher

`cc_dump.app.hot_reload.init()` starts watching the package directory for file changes.

### 18. Launch TUI

Create `CcDumpApp` with all runtime state and call `app.run()`. This blocks until the user quits.

If `run` subcommand was used with extra args, the auto-launch config name and extra args are passed to the app for deferred launch.

### 19. Shutdown

After `app.run()` returns (in a `finally` block), `_shutdown_runtime()` executes:

1. Dump buffered error log via `logger.error` (TUI is gone, terminal is restored)
2. Clean up tmux state (`tmux_ctrl.cleanup()` — the method is intentionally empty/no-op)
3. Gracefully shut down each proxy server: spawn a daemon thread to call `server.shutdown()`, join with 3-second timeout, then force `server_close()` regardless
4. Stop the event router (`router.stop()`)
5. Close all HAR recorders (`recorder.close()`)
6. Print resume command: mask SIGINT (`signal.SIG_IGN`), log "To resume: ..." with the port and resume path via `logger.info()` (not printed to stdout), restore SIGINT (`signal.SIG_DFL`)

The resume path is derived from `_resume_path()`: the primary HAR recording path if it exists on disk, otherwise the replay input path if it exists.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Normal exit: TUI quit, recording admin command completed, no-recordings-found for resume/continue, replay load failure, or `run --help` |
| `1` | Unhandled exception (Python default behavior) |
| `2` | `run` subcommand with unknown config name (explicit `sys.exit(2)`) |

The recording admin commands (`--list-recordings`, `--cleanup-recordings`) and the `--resume`/`--continue` "no recordings found" path all return normally (exit code 0) via `return` in `main()`, not via `sys.exit`.

---

## `cc-dump-serve` Entry Point

A minimal wrapper around `textual-serve`. Starts a web server at `localhost:8000` that spawns independent `cc-dump` instances for each browser session.

No CLI flags are exposed. Host (`localhost`), port (`8000`), and title (`"cc-dump - Claude Code API Monitor"`) are hardcoded in `serve.py`.

```
cc-dump-serve
# or: just web
# or: uv run cc-dump-serve
```

The server prints a startup banner and blocks on `server.serve()` until interrupted.

---

## File Locations

| Purpose | Path |
|---------|------|
| Settings | `$XDG_CONFIG_HOME/cc-dump/settings.json` (default: `~/.config/cc-dump/settings.json`) |
| Recordings | `~/.local/share/cc-dump/recordings/` |
| Logs | `$CC_DUMP_LOG_DIR/cc-dump-<YYYYMMDD-HHMMSS>-<pid>.log` (default dir: `~/.local/share/cc-dump/logs/`) |
| Forward proxy CA | `~/.cc-dump/forward-proxy-ca/` (or `--forward-proxy-ca-dir`) |

### Recording filename format

```
ccdump-<provider>-<timestamp>-<hash>.har
```

- `<provider>`: provider key (e.g., `anthropic`, `openai`, `copilot`)
- `<timestamp>`: `YYYYMMDD-HHMMSSZ` in UTC (note: uppercase `Z` suffix — a literal character in the format string `strftime("%Y%m%d-%H%M%SZ")`, not a strftime directive)
- `<hash>`: 8-character hex prefix of SHA1 computed from `<provider>:<timestamp>:<pid>:<uuid4_hex>`

One HAR file is created per active provider per session. Files are created lazily on first API call, not at startup.

The recording output directory is resolved by `_recordings_output_dir()`:
1. No `--record` flag: `~/.local/share/cc-dump/recordings/`
2. `--record <existing-directory>`: the directory itself
3. `--record <path>.har`: parent directory of the path
4. `--record <other-path>`: the path treated as a directory

---

## Interaction Between Flags

- `--replay`, `--continue`, and `--resume` all write to `args.replay`. Processing order: `--resume` first, `--continue` second. If both are specified, `--continue` wins (it runs second and overwrites). A directly-specified `--replay` value will be overwritten by either.
- The proxy servers start unconditionally — `--replay` does not suppress the live proxy. All three replay-related flags result in replay + live proxy.
- `--no-record` suppresses HAR recording. Without it, recording is always active.
- `--record` controls the output directory, not whether recording happens.
- `--cleanup-dry-run` is only meaningful alongside `--cleanup-recordings`.
- `--list-recordings` and `--cleanup-recordings` are early-exit commands that skip the proxy/TUI entirely.
- `--forward-proxy-ca-dir` is only used when at least one active provider has `proxy_type == "forward"`. The `ForwardProxyCertificateAuthority` class is only imported in that case (lazy import).

---

## Launch Configuration System

The `run` subcommand uses a launch configuration system that bridges CLI invocation to tmux-integrated tool launching.

### Config Lookup

`launch_config.load_configs()` loads from `settings.json`, normalizes, deduplicates names, and ensures default configs exist for all registered launchers.

### Registered Launchers

Defined in `launcher_registry.py`:

| Key | Display Name | Default Command | Supports `--model` | Supports `--resume` | Provider |
|-----|-------------|-----------------|--------------------|--------------------|----------|
| `claude` | Claude | `claude` | Yes | Yes | `anthropic` |
| `copilot` | Copilot | `copilot` | No | No | `copilot` |

### Extra Args Merging

When `cc-dump run <config> -- <extra-args>` is used, `launch_config.config_with_extra_args()` creates a transient (never persisted) copy of the config with the extra args appended to the `extra_args` option. Existing `extra_args` from the saved config are preserved and the CLI args are concatenated after them.
