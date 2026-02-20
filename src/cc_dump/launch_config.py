"""Launch configuration model for Claude tmux integration.

Manages named run configurations with their own claude command and flags.
Configs are persisted in settings.json.

This module is RELOADABLE — pure data + persistence, no widget deps.

// [LAW:one-source-of-truth] claude_command lives in LaunchConfig (per-config).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, asdict

import cc_dump.settings


SHELL_OPTIONS = ("", "bash", "zsh")
"""Valid values for LaunchConfig.shell. Empty string = no shell wrapper."""


@dataclass
class LaunchConfig:
    """A named run configuration for launching Claude."""

    name: str = "default"
    claude_command: str = "claude"  # executable name (e.g. "claude", "clod")
    model: str = ""           # e.g. "haiku", "opus" — empty = no --model flag
    auto_resume: bool = True  # pass --resume <session_id> when relaunching
    # NOTE: --resume <id> (not --continue) because --continue always resumes
    # the most recent session, which breaks concurrent multi-session workflows.
    shell: str = ""           # "", "bash", or "zsh" — wraps in shell -c "source rc; cmd"
    extra_flags: str = ""     # freeform, appended to command


def _config_to_dict(config: LaunchConfig) -> dict:
    return asdict(config)


def _dict_to_config(d: dict) -> LaunchConfig:
    shell = d.get("shell", "")
    return LaunchConfig(
        name=d.get("name", "default"),
        claude_command=d.get("claude_command", "claude"),
        model=d.get("model", ""),
        auto_resume=bool(d.get("auto_resume", True)),
        shell=shell if shell in SHELL_OPTIONS else "",
        extra_flags=d.get("extra_flags", ""),
    )


def load_configs() -> list[LaunchConfig]:
    """Load launch configs from settings.json. Falls back to [default]."""
    raw = cc_dump.settings.load_setting("launch_configs", None)
    # [LAW:dataflow-not-control-flow] Always return a list; empty/missing → default.
    configs = [_dict_to_config(d) for d in raw] if isinstance(raw, list) and raw else []
    return configs or [LaunchConfig()]


def save_configs(configs: list[LaunchConfig]) -> None:
    """Serialize configs to settings.json."""
    cc_dump.settings.save_setting(
        "launch_configs", [_config_to_dict(c) for c in configs]
    )


def load_active_name() -> str:
    """Load the name of the active launch config."""
    return cc_dump.settings.load_setting("active_launch_config", "default")


def save_active_name(name: str) -> None:
    """Persist the active launch config name."""
    cc_dump.settings.save_setting("active_launch_config", name)


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
    //   Uses config.claude_command as the executable.

    Args:
        config: Launch configuration with claude_command, model, resume, shell, extra_flags.
        session_id: Session ID for --resume (empty = no resume).

    Returns:
        Complete command string ready for tmux. When shell is set, the command
        and all args are wrapped inside ``shell -c 'source ~/.<shell>rc; ...'``
        with proper shlex escaping.
    """
    # Build the arg list
    args: list[str] = []
    if config.model:
        args.extend(["--model", config.model])
    if config.auto_resume and session_id:
        args.extend(["--resume", session_id])
    if config.extra_flags:
        args.append(config.extra_flags)

    inner_command = " ".join([config.claude_command] + args)

    # // [LAW:dataflow-not-control-flow] shell wrapping is a transformation of the
    # command value, not a branch that skips assembly.
    if not config.shell:
        return inner_command

    rc_file = "~/.{}rc".format(config.shell)
    inner_script = "source {}; {}".format(rc_file, inner_command)
    return "{} -c {}".format(config.shell, shlex.quote(inner_script))
