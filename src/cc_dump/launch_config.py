"""Launch configuration model for Claude tmux integration.

Manages named run configurations that add flags on top of the base
claude_command from settings. Configs are persisted in settings.json.

This module is RELOADABLE — pure data + persistence, no widget deps.

// [LAW:one-source-of-truth] claude_command in settings.py is the base executable.
//   LaunchConfig adds flags on top. No duplication of the executable path.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import cc_dump.settings


@dataclass
class LaunchConfig:
    """A named run configuration for launching Claude."""

    name: str = "default"
    model: str = ""           # e.g. "haiku", "opus" — empty = no --model flag
    auto_resume: bool = True  # pass --resume <session_id> when relaunching
    extra_flags: str = ""     # freeform, appended to command


def _config_to_dict(config: LaunchConfig) -> dict:
    return asdict(config)


def _dict_to_config(d: dict) -> LaunchConfig:
    return LaunchConfig(
        name=d.get("name", "default"),
        model=d.get("model", ""),
        auto_resume=bool(d.get("auto_resume", True)),
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


def build_command_args(config: LaunchConfig, session_id: str = "") -> str:
    """Build extra CLI args from a config + optional session_id.

    Returns a string to append after the base claude command.
    // [LAW:one-source-of-truth] This is the sole place args are assembled.
    """
    parts: list[str] = []
    if config.model:
        parts.append("--model {}".format(config.model))
    if config.auto_resume and session_id:
        parts.append("--resume {}".format(session_id))
    if config.extra_flags:
        parts.append(config.extra_flags)
    return " ".join(parts)
