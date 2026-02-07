"""Color palette generator using golden-angle spacing in HSL space.

Produces ~38 distinctive 24-bit colors from a configurable seed hue.
Golden angle (137.508°) maximizes perceptual distance between consecutively
assigned colors, so color[0] and color[1] are never adjacent on the wheel.

Two lightness levels per hue:
  - Foreground (L≈0.70, S≈0.75) — text on dark backgrounds
  - Dark (L≈0.25, S≈0.60) — background highlights, active footer states
"""

import colorsys
import os

GOLDEN_ANGLE = 137.508

# Semantic target hues (degrees) for perceptually-stable roles
_SEMANTIC_TARGETS = {
    "error": 0.0,  # red
    "warning": 50.0,  # yellow-ish
    "success": 130.0,  # green
    "info": 190.0,  # cyan
}


def _hsl_to_hex(h: float, s: float, lightness: float) -> str:
    """Convert HSL (h in 0-360, s/lightness in 0-1) to #RRGGBB hex string."""
    # colorsys uses h in 0-1
    r, g, b = colorsys.hls_to_rgb(h / 360.0, lightness, s)
    return "#{:02X}{:02X}{:02X}".format(
        int(round(r * 255)),
        int(round(g * 255)),
        int(round(b * 255)),
    )


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse #RRGGBB to (r, g, b) ints."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _angular_distance(a: float, b: float) -> float:
    """Shortest angular distance between two hues in degrees."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


# ── Fixed indicator palette for filter toggles ──────────────────────────
# Hand-picked palette (warm → cool gradient) for filter indicator bars.
# Each entry is (name, foreground_hex).
_INDICATOR_COLORS: list[tuple[str, str]] = [
    ("strawberry-red", "#F94144"),
    ("atomic-tangerine", "#F3722C"),
    ("carrot-orange", "#F8961E"),
    ("tuscan-sun", "#F9C74F"),
    ("golden-sand", "#C5C35E"),
    ("willow-green", "#90BE6D"),
    ("mint-leaf", "#6AB47C"),
    ("seagrass", "#43AA8B"),
    ("dark-cyan", "#4D908E"),
    ("blue-slate", "#577590"),
]

# Stable mapping: filter name → index into _INDICATOR_COLORS
_FILTER_INDICATOR_INDEX: dict[str, int] = {
    "headers": 0,  # strawberry-red
    "tools": 1,  # atomic-tangerine
    "system": 2,  # carrot-orange
    "expand": 3,  # tuscan-sun
    "metadata": 4,  # golden-sand
    "stats": 5,  # willow-green
    "economics": 6,  # mint-leaf
    "timeline": 7,  # seagrass
}


def _darken_hex(
    hex_color: str, lightness: float = 0.25, saturation: float = 0.60
) -> str:
    """Derive a dark background variant from a hex foreground color."""
    r, g, b = _hex_to_rgb(hex_color)
    h, l_orig, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    # Re-synthesize at target lightness/saturation, preserving hue
    return _hsl_to_hex(h * 360.0, saturation, lightness)


# Pre-compute foreground and dark background variants for indicators
INDICATOR_FG: list[str] = [hex_color for _, hex_color in _INDICATOR_COLORS]
INDICATOR_BG: list[str] = [_darken_hex(hex_color) for _, hex_color in _INDICATOR_COLORS]


class Palette:
    """Color palette with golden-angle spacing from a seed hue.

    Args:
        seed_hue: Starting hue in degrees (0-360). Default 190 (cyan).
        count: Number of colors to generate. Default 38.
    """

    def __init__(self, seed_hue: float = 190.0, count: int = 38):
        self._seed_hue = seed_hue
        self._count = count

        # Generate hues using golden angle
        self._hues: list[float] = []
        for i in range(count):
            hue = (seed_hue + i * GOLDEN_ANGLE) % 360
            self._hues.append(hue)

        # Pre-compute foreground and dark variants
        self._fg_colors: list[str] = []
        self._bg_colors: list[str] = []
        for hue in self._hues:
            self._fg_colors.append(_hsl_to_hex(hue, 0.75, 0.70))
            self._bg_colors.append(_hsl_to_hex(hue, 0.60, 0.25))

        # Role colors: fixed palette positions offset from seed
        # user=0, assistant=1, system=2 — these get the first three
        # golden-angle-spaced hues, which are maximally distinct
        self._role_indices = {
            "user": 0,
            "assistant": 1,
            "system": 2,
        }

        # Indices reserved by roles (not available for semantic matching).
        # Filter indicators now use a separate fixed palette, so positions
        # 3-10 are no longer reserved in the golden-angle palette.
        _reserved = set(self._role_indices.values())

        # Map semantic roles to closest non-reserved palette indices
        self._semantic_indices: dict[str, int] = {}
        for role, target_hue in _SEMANTIC_TARGETS.items():
            best_idx = 0
            best_dist = 360.0
            for i, hue in enumerate(self._hues):
                if i in _reserved:
                    continue
                dist = _angular_distance(hue, target_hue)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            self._semantic_indices[role] = best_idx

    def fg(self, index: int) -> str:
        """Foreground hex color (#RRGGBB) at index (wraps)."""
        return self._fg_colors[index % self._count]

    def bg(self, index: int) -> str:
        """Dark background hex color (#RRGGBB) at index (wraps)."""
        return self._bg_colors[index % self._count]

    def fg_on_bg(self, index: int) -> tuple[str, str]:
        """(foreground, background) hex pair at index (wraps)."""
        i = index % self._count
        return self._fg_colors[i], self._bg_colors[i]

    # ── Semantic named colors ──────────────────────────────────────────

    @property
    def user(self) -> str:
        """Role color for user messages."""
        return self._fg_colors[self._role_indices["user"]]

    @property
    def assistant(self) -> str:
        """Role color for assistant messages."""
        return self._fg_colors[self._role_indices["assistant"]]

    @property
    def system(self) -> str:
        """Role color for system messages."""
        return self._fg_colors[self._role_indices["system"]]

    @property
    def error(self) -> str:
        """Semantic red-ish color."""
        return self._fg_colors[self._semantic_indices["error"]]

    @property
    def warning(self) -> str:
        """Semantic yellow-ish color."""
        return self._fg_colors[self._semantic_indices["warning"]]

    @property
    def info(self) -> str:
        """Semantic cyan-ish color."""
        return self._fg_colors[self._semantic_indices["info"]]

    @property
    def success(self) -> str:
        """Semantic green-ish color."""
        return self._fg_colors[self._semantic_indices["success"]]

    @property
    def error_bg(self) -> str:
        """Semantic red-ish dark background."""
        return self._bg_colors[self._semantic_indices["error"]]

    @property
    def warning_bg(self) -> str:
        """Semantic yellow-ish dark background."""
        return self._bg_colors[self._semantic_indices["warning"]]

    @property
    def info_bg(self) -> str:
        """Semantic cyan-ish dark background."""
        return self._bg_colors[self._semantic_indices["info"]]

    @property
    def success_bg(self) -> str:
        """Semantic green-ish dark background."""
        return self._bg_colors[self._semantic_indices["success"]]

    # ── Filter colors (stable assignments for headers/tools/system/etc.) ──

    def filter_color(self, filter_name: str) -> str:
        """Get a stable foreground color for a named filter.

        Uses the fixed indicator palette (warm→cool gradient), not the
        golden-angle palette.
        """
        idx = _FILTER_INDICATOR_INDEX.get(filter_name, 0)
        return INDICATOR_FG[idx]

    def filter_bg(self, filter_name: str) -> str:
        """Get a stable dark background for a named filter.

        Uses darkened variants of the fixed indicator palette.
        """
        idx = _FILTER_INDICATOR_INDEX.get(filter_name, 0)
        return INDICATOR_BG[idx]

    # ── Accent color (for keybinding highlights, etc.) ──

    @property
    def accent(self) -> str:
        """Warm accent color for keybinding highlights."""
        # Use a position that tends toward orange/warm
        # Position 11 is far enough from roles and filters
        return self._fg_colors[11 % self._count]

    # ── Bulk access ──

    @property
    def all_fg(self) -> list[str]:
        """All foreground colors."""
        return list(self._fg_colors)

    @property
    def all_bg(self) -> list[str]:
        """All dark background colors."""
        return list(self._bg_colors)

    @property
    def count(self) -> int:
        """Number of colors in palette."""
        return self._count

    # ── MSG_COLORS range (offset from tag range) ──

    def msg_color(self, index: int, count: int = 6) -> str:
        """Get a message color, offset from tag colors to avoid overlap.

        Uses palette positions starting at 12 (after roles, filters, accent).
        """
        return self._fg_colors[(12 + index) % self._count]


def _get_seed_hue() -> float:
    """Get seed hue from environment or default."""
    env = os.environ.get("CC_DUMP_SEED_HUE")
    if env is not None:
        try:
            return float(env)
        except ValueError:
            import sys

            sys.stderr.write(
                f"[palette] invalid CC_DUMP_SEED_HUE={env!r}, using default\n"
            )
            sys.stderr.flush()
    return 190.0


def init_palette(seed_hue: float | None = None) -> None:
    """Initialize the global palette with a seed hue.

    Call this before TUI starts if using --seed-hue CLI arg.
    """
    global PALETTE
    hue = seed_hue if seed_hue is not None else _get_seed_hue()
    PALETTE = Palette(seed_hue=hue)


# Module-level singleton — consumers import this
PALETTE = Palette(seed_hue=_get_seed_hue())
