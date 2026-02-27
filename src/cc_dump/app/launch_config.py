"""Launch configuration model for tmux-integrated CLI launchers.

Manages named run configurations with per-tool command/flags.
Configs are persisted in settings.json.

This module is RELOADABLE — pure data + persistence, no widget deps.

// [LAW:one-source-of-truth] command + launcher selection live in LaunchConfig.
"""

from __future__ import annotations

import shlex
import os
from dataclasses import dataclass, asdict

import cc_dump.app.launcher_registry
import cc_dump.io.settings


SHELL_OPTIONS = ("", "bash", "zsh")
"""Valid values for LaunchConfig.shell. Empty string = no shell wrapper."""


@dataclass
class LaunchConfig:
    """A named run configuration for launching a CLI tool."""

    name: str = "default"
    launcher: str = cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY
    command: str = ""         # executable command; empty => launcher default
    model: str = ""           # e.g. "haiku", "opus" — empty = no --model flag
    auto_resume: bool = True  # pass --resume <session_id> when relaunching
    # NOTE: --resume <id> (not --continue) because --continue always resumes
    # the most recent session, which breaks concurrent multi-session workflows.
    shell: str = ""           # "", "bash", or "zsh" — wraps in shell -c "source rc; cmd"
    extra_flags: str = ""     # freeform, appended to command

    @property
    def resolved_command(self) -> str:
        """Return configured command or launcher default."""
        spec = cc_dump.app.launcher_registry.get_launcher_spec(self.launcher)
        cmd = str(self.command or "").strip()
        return cmd or spec.default_command

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
    return asdict(config)


def _dict_to_config(d: dict) -> LaunchConfig:
    shell = d.get("shell", "")
    launcher = cc_dump.app.launcher_registry.normalize_launcher_key(
        d.get("launcher", cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY)
    )
    command = d.get("command", "")
    return LaunchConfig(
        name=d.get("name", "default"),
        launcher=launcher,
        command=str(command or ""),
        model=d.get("model", ""),
        auto_resume=bool(d.get("auto_resume", True)),
        shell=shell if shell in SHELL_OPTIONS else "",
        extra_flags=d.get("extra_flags", ""),
    )


def load_configs() -> list[LaunchConfig]:
    """Load launch configs from settings.json. Falls back to [default]."""
    raw = cc_dump.io.settings.load_setting("launch_configs", None)
    # [LAW:dataflow-not-control-flow] Always return a list; empty/missing → default.
    configs = [_dict_to_config(d) for d in raw] if isinstance(raw, list) and raw else []
    return configs or [LaunchConfig()]


def save_configs(configs: list[LaunchConfig]) -> None:
    """Serialize configs to settings.json."""
    cc_dump.io.settings.save_setting(
        "launch_configs", [_config_to_dict(c) for c in configs]
    )


def load_active_name() -> str:
    """Load the name of the active launch config."""
    return cc_dump.io.settings.load_setting("active_launch_config", "default")


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
        config: Launch configuration with launcher, command, model, resume, shell, extra_flags.
        session_id: Session ID for --resume (empty = no resume).

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
    if config.auto_resume and session_id and spec.supports_resume_flag:
        args.extend(["--resume", session_id])
    if config.extra_flags:
        args.append(config.extra_flags)

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
