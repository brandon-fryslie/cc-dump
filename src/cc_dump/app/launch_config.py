"""Launch configuration model for tmux-integrated CLI launchers.

Manages named run configurations with per-tool command/flags.
Configs are persisted in settings.json.

This module is RELOADABLE — pure data + persistence, no widget deps.

// [LAW:one-source-of-truth] command + launcher selection live in LaunchConfig.
"""

from __future__ import annotations

import shlex
import os
from dataclasses import dataclass, asdict, field
from typing import Literal

import cc_dump.app.launcher_registry
import cc_dump.io.settings


SHELL_OPTIONS = ("", "bash", "zsh")
"""Valid values for LaunchConfig.shell. Empty string = no shell wrapper."""


@dataclass
class LaunchConfig:
    """A named run configuration for launching a CLI tool."""

    name: str = cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY
    launcher: str = cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY
    command: str = ""         # executable command; empty => launcher default
    model: str = ""           # e.g. "haiku", "opus" — empty = no --model flag
    shell: str = ""           # "", "bash", or "zsh" — wraps in shell -c "source rc; cmd"
    options: dict[str, str | bool] = field(default_factory=dict)

    @property
    def resolved_command(self) -> str:
        """Return configured command or launcher default."""
        spec = cc_dump.app.launcher_registry.get_launcher_spec(self.launcher)
        cmd = str(self.command or "").strip()
        return cmd or spec.default_command


@dataclass(frozen=True)
class LaunchOptionDef:
    """Declarative schema and CLI mapping for one launch option.

    // [LAW:one-type-per-behavior] One option definition type for all tools.
    """

    key: str
    label: str
    description: str
    kind: Literal["text", "bool"]
    default: str | bool
    cli_mode: Literal["raw", "flag", "resume"] = "flag"
    cli_flag: str = ""


# // [LAW:one-source-of-truth] Launch option schema is centralized here.
_COMMON_OPTION_DEFS: tuple[LaunchOptionDef, ...] = (
    LaunchOptionDef(
        key="extra_args",
        label="Extra Args",
        description="Appended to command",
        kind="text",
        default="",
        cli_mode="raw",
    ),
)

_LAUNCHER_OPTION_DEFS: dict[str, tuple[LaunchOptionDef, ...]] = {
    "claude": (
        LaunchOptionDef(
            key="auto_resume",
            label="Auto Resume",
            description="Pass --resume <session_id>",
            kind="bool",
            default=True,
            cli_mode="resume",
            cli_flag="--resume",
        ),
        LaunchOptionDef(
            key="bypass",
            label="Bypass Permissions",
            description="Pass --dangerously-bypass-permissions",
            kind="bool",
            default=False,
            cli_mode="flag",
            cli_flag="--dangerously-bypass-permissions",
        ),
        LaunchOptionDef(
            key="continue",
            label="Continue",
            description="Pass --continue",
            kind="bool",
            default=False,
            cli_mode="flag",
            cli_flag="--continue",
        ),
    ),
    "copilot": (
        LaunchOptionDef(
            key="yolo",
            label="YOLO",
            description="Pass --yolo",
            kind="bool",
            default=False,
            cli_mode="flag",
            cli_flag="--yolo",
        ),
    ),
}

_ALL_OPTION_DEFS: tuple[LaunchOptionDef, ...] = _COMMON_OPTION_DEFS + tuple(
    opt for opts in _LAUNCHER_OPTION_DEFS.values() for opt in opts
)
_OPTION_DEFS_BY_KEY: dict[str, LaunchOptionDef] = {opt.key: opt for opt in _ALL_OPTION_DEFS}


def launcher_option_defs(launcher: str) -> tuple[LaunchOptionDef, ...]:
    normalized = cc_dump.app.launcher_registry.normalize_launcher_key(launcher)
    return _COMMON_OPTION_DEFS + _LAUNCHER_OPTION_DEFS.get(normalized, ())


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    if value is None:
        return default
    return bool(value)


def normalize_options(options: dict | None) -> dict[str, str | bool]:
    """Normalize persisted option values into canonical, typed values."""
    raw = options if isinstance(options, dict) else {}
    normalized: dict[str, str | bool] = {}
    for option in _ALL_OPTION_DEFS:
        value = raw.get(option.key, option.default)
        if option.kind == "bool":
            normalized[option.key] = _coerce_bool(value, bool(option.default))
        else:
            normalized[option.key] = str(value or "")
    return normalized


def option_value(
    config: LaunchConfig,
    key: str,
) -> str | bool:
    option_def = _OPTION_DEFS_BY_KEY.get(key)
    if option_def is None:
        return ""
    normalized = normalize_options(config.options)
    return normalized.get(option_def.key, option_def.default)


def default_options() -> dict[str, str | bool]:
    return normalize_options({})


def default_config_for_launcher(launcher: str) -> LaunchConfig:
    normalized = cc_dump.app.launcher_registry.normalize_launcher_key(launcher)
    return LaunchConfig(
        name=normalized,
        launcher=normalized,
        command="",
        model="",
        shell="",
        options=default_options(),
    )


def default_configs() -> list[LaunchConfig]:
    return [
        default_config_for_launcher(spec.key)
        for spec in cc_dump.app.launcher_registry.all_launcher_specs()
    ]


@dataclass(frozen=True)
class LaunchProfile:
    """Runtime launch profile derived from config + provider endpoints.

    // [LAW:one-source-of-truth] tmux launcher inputs are computed once here.
    """

    launcher_key: str
    launcher_label: str
    command: str
    process_names: tuple[str, ...]
    environment: dict[str, str]


def _config_to_dict(config: LaunchConfig) -> dict:
    payload = asdict(config)
    payload["launcher"] = cc_dump.app.launcher_registry.normalize_launcher_key(
        payload.get("launcher", "")
    )
    payload["shell"] = payload.get("shell", "") if payload.get("shell", "") in SHELL_OPTIONS else ""
    payload["options"] = normalize_options(config.options)
    return payload


def _dict_to_config(d: dict) -> LaunchConfig:
    shell = d.get("shell", "")
    launcher = cc_dump.app.launcher_registry.normalize_launcher_key(
        d.get("launcher", cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY)
    )
    command = d.get("command", "")
    return LaunchConfig(
        name=str(d.get("name", launcher) or launcher),
        launcher=launcher,
        command=str(command or ""),
        model=d.get("model", ""),
        shell=shell if shell in SHELL_OPTIONS else "",
        options=normalize_options(d.get("options", {})),
    )


def _dedupe_config_names(configs: list[LaunchConfig]) -> list[LaunchConfig]:
    seen: dict[str, int] = {}
    deduped: list[LaunchConfig] = []
    for idx, config in enumerate(configs, start=1):
        base_name = str(config.name or "").strip() or "config-{}".format(idx)
        count = seen.get(base_name, 0) + 1
        seen[base_name] = count
        name = base_name if count == 1 else "{}-{}".format(base_name, count)
        deduped.append(
            LaunchConfig(
                name=name,
                launcher=cc_dump.app.launcher_registry.normalize_launcher_key(config.launcher),
                command=str(config.command or ""),
                model=str(config.model or ""),
                shell=config.shell if config.shell in SHELL_OPTIONS else "",
                options=normalize_options(config.options),
            )
        )
    return deduped


def _ensure_default_tool_configs(configs: list[LaunchConfig]) -> list[LaunchConfig]:
    by_name = {config.name: config for config in configs}
    for spec in cc_dump.app.launcher_registry.all_launcher_specs():
        # [LAW:one-source-of-truth] Canonical default preset per tool name.
        existing = by_name.get(spec.key)
        if existing is None:
            default_cfg = default_config_for_launcher(spec.key)
            configs.append(default_cfg)
            by_name[default_cfg.name] = default_cfg
            continue
        existing.launcher = spec.key
        existing.options = normalize_options(existing.options)
    return configs


def _normalize_configs(configs: list[LaunchConfig]) -> list[LaunchConfig]:
    deduped = _dedupe_config_names(configs)
    with_defaults = _ensure_default_tool_configs(deduped)
    return _dedupe_config_names(with_defaults)


def load_configs() -> list[LaunchConfig]:
    """Load launch configs from settings.json with per-tool default presets."""
    raw = cc_dump.io.settings.load_setting("launch_configs", None)
    # [LAW:dataflow-not-control-flow] Always return a list; empty/missing → default.
    configs = (
        [_dict_to_config(d) for d in raw if isinstance(d, dict)]
        if isinstance(raw, list) and raw
        else []
    )
    normalized = _normalize_configs(configs)
    return normalized or default_configs()


def save_configs(configs: list[LaunchConfig]) -> list[LaunchConfig]:
    """Serialize configs to settings.json and return the normalized list.

    Returns the post-normalization list so callers can reconcile names
    (e.g. active_name) against possibly-deduped config names.
    """
    normalized = _normalize_configs(configs)
    cc_dump.io.settings.save_setting(
        "launch_configs", [_config_to_dict(c) for c in normalized]
    )
    return normalized


def load_active_name() -> str:
    """Load the name of the active launch config."""
    return cc_dump.io.settings.load_setting(
        "active_launch_config",
        cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY,
    )


def save_active_name(name: str) -> None:
    """Persist the active launch config name."""
    cc_dump.io.settings.save_setting("active_launch_config", name)


def get_active_config() -> LaunchConfig:
    """Look up active config by name. Falls back to first config."""
    configs = load_configs()
    active_name = load_active_name()
    # [LAW:dataflow-not-control-flow] Lookup table pattern; default to first.
    by_name = {c.name: c for c in configs}
    return by_name.get(active_name, configs[0])


def build_full_command(config: LaunchConfig, session_id: str = "") -> str:
    """Build the complete command string including shell wrapper if configured.

    // [LAW:one-source-of-truth] Sole place where command + args + shell wrapper are assembled.

    Args:
        config: Launch configuration with launcher, command, model, shell, options.
        session_id: Session ID used by resume-capable options.

    Returns:
        Complete command string ready for tmux. When shell is set, the command
        and all args are wrapped inside ``shell -c 'source ~/.<shell>rc; ...'``
        with proper shlex escaping.
    """
    spec = cc_dump.app.launcher_registry.get_launcher_spec(config.launcher)

    # Build the arg list
    args: list[str] = []
    if config.model and spec.supports_model_flag:
        args.extend(["--model", config.model])

    normalized_options = normalize_options(config.options)
    for option in launcher_option_defs(config.launcher):
        value = normalized_options.get(option.key, option.default)
        if option.cli_mode == "raw":
            text = str(value or "").strip()
            if text:
                args.append(text)
            continue
        if option.cli_mode == "resume":
            if bool(value) and session_id and spec.supports_resume_flag:
                args.extend([option.cli_flag, session_id])
            continue
        if bool(value):
            args.append(option.cli_flag)

    inner_command = " ".join([config.resolved_command] + args)

    # // [LAW:dataflow-not-control-flow] shell wrapping is a transformation of the
    # command value, not a branch that skips assembly.
    if not config.shell:
        return inner_command

    rc_file = "~/.{}rc".format(config.shell)
    inner_script = "source {}; {}".format(rc_file, inner_command)
    return "{} -c {}".format(config.shell, shlex.quote(inner_script))


def _derive_process_names(config: LaunchConfig) -> tuple[str, ...]:
    """Derive tmux process match set from command + launcher aliases.

    // [LAW:dataflow-not-control-flow] Process identity is derived data, not branching state.
    """
    spec = cc_dump.app.launcher_registry.get_launcher_spec(config.launcher)
    tokenized = shlex.split(config.resolved_command)
    primary = os.path.basename(tokenized[0]) if tokenized else ""
    values = [primary, *spec.process_names]
    # // [LAW:one-source-of-truth] Single dedupe pass defines the canonical match set.
    return tuple(dict.fromkeys(v for v in values if v))


def build_launch_profile(
    config: LaunchConfig,
    provider_endpoints: dict[str, dict[str, object]] | None = None,
    session_id: str = "",
) -> LaunchProfile:
    """Build runtime launch profile for tmux.

    Args:
        config: persisted launch configuration.
        provider_endpoints: proxy endpoint metadata keyed by provider.
        session_id: optional session id for resume-capable tools.
    """
    spec = cc_dump.app.launcher_registry.get_launcher_spec(config.launcher)
    return LaunchProfile(
        launcher_key=spec.key,
        launcher_label=spec.display_name,
        command=build_full_command(config, session_id=session_id),
        process_names=_derive_process_names(config),
        environment=cc_dump.app.launcher_registry.build_proxy_env(
            spec, provider_endpoints
        ),
    )
