# CLI Interface Specification

**Status:** draft
**Scope:** Complete CLI interface — entry points, flags, subcommands, environment variables, exit codes, startup sequence.

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
python -m cc_dump          # equivalent to cc-dump
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

- Arguments after `--` are appended to the config's `extra_args` option for this invocation only (not persisted).
- All standard cc-dump flags can appear between `<config-name>` and `--`.

```
cc-dump run claude                           # launch with "claude" config
cc-dump run claude --port 5000               # pin proxy port
cc-dump run claude -- --dangerously-bypass-permissions
cc-dump run haiku --port 5000 -- --continue
```

If `<config-name>` does not match a saved config, the process exits with code 2 and prints available config names to stderr.

`cc-dump run -h` and `cc-dump run --help` print subcommand usage and exit 0.

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
| `--record` | `str` | `None` | HAR recording output directory. Default dir: `~/.local/share/cc-dump/recordings/`. If a `.har` path is given, its parent directory is used |
| `--no-record` | `bool` | `False` | Disable HAR recording entirely |
| `--replay` | `str` | `None` | Replay a recorded session from a `.har` file path |
| `--continue` | `bool` | `False` | Replay most recent recording then continue in live proxy mode |
| `--resume` | `str?` | `None` | Replay a recording then continue live. No argument = latest recording. Optional path to specific `.har` file |

### Recording Administration

These flags execute a one-shot command and exit (no TUI, no proxy).

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--list-recordings` | `bool` | `False` | List known HAR recordings and exit |
| `--cleanup-recordings` | `int?` | `None` | Delete older recordings, keeping newest N (default: 20), and exit |
| `--cleanup-dry-run` | `bool` | `False` | Preview cleanup without deleting. Only meaningful with `--cleanup-recordings` |

### Optional Provider Proxies

For each optional provider (currently `openai` and `copilot`), the following flags are dynamically generated from the provider registry:

| Flag pattern | Type | Default | Description |
|---|---|---|---|
| `--<key>-port` | `int` | `0` | Bind port for this provider's proxy. `0` = OS-assigned |
| `--<key>-target` | `str` | Provider-specific default | Upstream URL for this provider |
| `--no-<key>` | `bool` | `False` | Disable this provider's proxy server entirely |

Current optional providers:

| Key | Display Name | Proxy Mode | Default Target | Env Var |
|-----|-------------|------------|----------------|---------|
| `openai` | OpenAI | reverse | `https://api.openai.com/v1` | `OPENAI_BASE_URL` |
| `copilot` | Copilot | forward | `https://api.githubcopilot.com` | `COPILOT_PROXY_URL` |

### Forward Proxy TLS

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--forward-proxy-ca-dir` | `str` | `None` | Directory for forward proxy CA key/cert. CLI default is `None`; actual default (`~/.cc-dump/forward-proxy-ca/`) is provided by the CA class when the CLI value is `None` |

This is only relevant when at least one active provider uses forward proxy mode (currently `copilot`). The CA is created on first use and its cert path is passed to launched tools via `NODE_EXTRA_CA_CERTS`.

---

## Environment Variables

### Provider Target URLs

These override the `--target` / `--<key>-target` defaults. They are read once at argument parsing time and become the argparse default for their respective flag.

| Variable | Affects | Default when unset |
|----------|---------|-------------------|
| `ANTHROPIC_BASE_URL` | `--target` (default provider) | `https://api.anthropic.com` |
| `OPENAI_BASE_URL` | `--openai-target` | `https://api.openai.com/v1` |
| `COPILOT_PROXY_URL` | `--copilot-target` | `https://api.githubcopilot.com` |

### Logging

| Variable | Purpose | Default |
|----------|---------|---------|
| `CC_DUMP_LOG_LEVEL` | Log level for `cc_dump` logger hierarchy | `INFO` |
| `CC_DUMP_LOG_FILE` | Explicit log file path | `~/.local/share/cc-dump/logs/cc-dump-<timestamp>-<pid>.log` |
| `CC_DUMP_LOG_DIR` | Directory for auto-generated log files (ignored when `CC_DUMP_LOG_FILE` is set) | `~/.local/share/cc-dump/logs` |

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

---

## Startup Sequence

The `main()` function follows this sequence:

### 1. Parse `run` subcommand

Before argparse runs, `_detect_run_subcommand` extracts the optional `run <config-name>` prefix and any `-- tool-extra-args` from `sys.argv[1:]`. The remaining flags are passed to argparse.

### 2. Build and parse CLI arguments

The argument parser is built dynamically from the provider registry. Each optional provider contributes `--<key>-port`, `--<key>-target`, and `--no-<key>` flags. Provider target defaults incorporate environment variable overrides at parse time.

### 3. Validate `run` config name

If `run` was specified, the named config is looked up in `settings.json`. Unknown names exit with code 2.

### 4. Configure logging

`cc_dump.io.logging_setup.configure()` sets up the `cc_dump` logger hierarchy with:
- A stderr handler (filtered to exclude in-app-only records)
- A rotating file handler (20MB max, 5 backups)

Level and path are derived from environment variables (see above).

### 5. Initialize color palette

`cc_dump.core.palette.init_palette()` sets up the color scheme before any rendering code runs.

### 6. Handle recording admin commands (early exit)

If `--list-recordings` or `--cleanup-recordings` was passed, execute the command, print output, and return. No proxy, no TUI.

**Note:** The stderr tee is NOT installed before these early exits. Steps 3-6 can return without ever installing the stderr tee.

### 7. Install stderr tee

`cc_dump.io.stderr_tee.install()` captures stderr output for later display in the TUI's error log. This runs after early-exit paths (recording admin commands, run validation) so those paths do not have stderr capture.

### 8. Resolve `--resume` and `--continue`

Both flags resolve to a `--replay` path via `_apply_resume_argument`:
- `--resume` (no arg): finds the latest recording
- `--resume <path>`: uses the given path
- `--continue`: finds the latest recording

Resolution prints emoji output to stdout (e.g., `"🔄 Resuming from: ..."` or `"🔄 Continuing from: ..."`).

If no recording is found, logs to `logger.info` (not print/stdout) and returns (no error exit code).

### 9. Load replay data

If `--replay` is set (directly or via resume/continue), load and parse the HAR file. On parse failure, print error and return.

### 10. Start proxy servers

For each active provider (default + optional providers not disabled by `--no-<key>`):
1. Create a `ProxyHandler` subclass parameterized with provider key, target, and event queue
2. Bind a `ThreadingHTTPServer` to the configured host/port
3. Start serving in a daemon thread
4. Build `ProviderEndpoint` metadata from the actual bound port

Print startup banner with endpoint details and usage hints for each provider.

### 11. Wire event pipeline

1. Create `EventRouter` with the shared event queue
2. Add `AnalyticsStore` as a `DirectSubscriber` (processes events inline before fan-out)
3. Add a `QueueSubscriber` for the TUI display
4. Create `HARRecordingSubscriber` for each active provider (unless `--no-record`)
5. Start the router's drain thread

### 12. Build tmux controller

If running inside tmux and `libtmux` is installed:
- Load the active launch config from `settings.json`
- Build a `LaunchProfile` with the resolved command, process names, and proxy environment
- Create a `TmuxController` with launch capability

Print tmux status (enabled/disabled and why).

### 13. Set up request pipeline

Create a `RequestPipeline` with interceptors (currently: sentinel interceptor for tmux state tracking). Assign the shared pipeline to all provider handler classes.

### 14. Create stores

- `SettingsStore` (reactive, hot-reloadable) with reactions wired
- `ViewStore` (reactive, hot-reloadable)
- `DomainStore` (owns FormattedBlock trees, persists across hot-reload)

### 15. Initialize hot-reload watcher

`cc_dump.app.hot_reload.init()` starts watching the package directory for file changes.

### 16. Launch TUI

Create `CcDumpApp` with all runtime state and call `app.run()`. This blocks until the user quits.

If `run` subcommand was used with extra args, the auto-launch config name and extra args are passed to the app for deferred launch.

### 17. Shutdown

After `app.run()` returns (in a `finally` block):
1. Dump buffered error log to stderr
2. Clean up tmux state (unzoom)
3. Gracefully shut down each proxy server (3-second timeout per binding, then force close)
4. Stop the event router
5. Close all HAR recorders
6. Print resume command (with SIGINT masked to prevent Ctrl+C from suppressing it)

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Normal exit: TUI quit, recording admin command completed, or `run --help` |
| `2` | `run` subcommand with unknown config name |
| [UNVERIFIED] Other codes | Unhandled exceptions propagate Python's default behavior (exit code 1) |

The recording admin commands (`--list-recordings`, `--cleanup-recordings`) and the `--resume`/`--continue` "no recordings found" path all return normally (exit code 0) rather than using `sys.exit`.

---

## `cc-dump-serve` Entry Point

A minimal wrapper around `textual-serve`. Starts a web server at `localhost:8000` that spawns independent `cc-dump` instances for each browser session.

No CLI flags are exposed. Host, port, and title are hardcoded.

```
cc-dump-serve
# or: just web
# or: uv run cc-dump-serve
```

---

## File Locations

| Purpose | Path |
|---------|------|
| Settings | `$XDG_CONFIG_HOME/cc-dump/settings.json` (default: `~/.config/cc-dump/settings.json`) |
| Recordings | `~/.local/share/cc-dump/recordings/` |
| Logs | `$CC_DUMP_LOG_DIR/cc-dump-<timestamp>-<pid>.log` (default dir: `~/.local/share/cc-dump/logs/`) |
| Forward proxy CA | `~/.cc-dump/forward-proxy-ca/` (or `--forward-proxy-ca-dir`) |

### Recording filename format

```
ccdump-<provider>-<timestamp>-<hash>.har
```

- `<provider>`: provider key (e.g., `anthropic`, `openai`, `copilot`)
- `<timestamp>`: `YYYYMMDD-HHMMSSz` in UTC
- `<hash>`: 8-character SHA1 derived from provider, timestamp, PID, and a UUID

One HAR file is created per active provider per session. Files are created lazily on first API call, not at startup.

---

## Interaction Between Flags

- `--replay` and `--continue` both set the replay path. `--continue` also leaves the live proxy running (replay + live). `--resume` also sets the replay path. The three are not mutually exclusive in argument parsing but `--continue` and `--resume` both write to the `args.replay` field.
- `--no-record` suppresses HAR recording. Without it, recording is always active.
- `--record` controls the output directory, not whether recording happens.
- `--cleanup-dry-run` is only meaningful alongside `--cleanup-recordings`.
- `--list-recordings` and `--cleanup-recordings` are early-exit commands that skip the proxy/TUI entirely.
- `--forward-proxy-ca-dir` is only used when at least one active provider has `proxy_type == "forward"`.

---

## Open Questions

- [UNVERIFIED] Whether `--continue` differs from `--resume` in proxy behavior (both set `args.replay`; the distinction may be purely in how the resume command is printed at shutdown).
- [UNVERIFIED] Whether `cc-dump-serve` should accept flags for host/port configuration.
- [UNVERIFIED] Exact behavior when `--replay` and `--continue` are both specified.
