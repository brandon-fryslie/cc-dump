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


# ── Filter indicator index ────────────────────────────────────────────
# Stable mapping: filter name → index (for golden-angle hue generation).
# The 7 main gutter/footer categories MUST occupy consecutive indices 0-6
# so golden-angle spacing keeps them maximally separated (min gap 32.5°).
# Non-consecutive indices cluster — e.g. indices {0,1,2,3,4,8,9} have
# only 20° minimum gap because index 8 lands 20° from index 0.
_FILTER_INDICATOR_INDEX: dict[str, int] = {
    "headers": 0,
    "tools": 1,
    "system": 2,
    "budget": 3,
    "metadata": 4,
    "user": 5,
    "assistant": 6,
}


# ── Theme-relative filter color generation ────────────────────────────


def _hex_to_hsl(hex_color: str) -> tuple[float, float, float]:
    """Parse #RRGGBB to (H in 0-360, S in 0-1, L in 0-1).

    Returns (0, 0.5, 0.5) for unparseable values (e.g. ANSI color names).
    """
    h_str = hex_color.lstrip("#")
    if len(h_str) != 6:
        return (0.0, 0.5, 0.5)
    try:
        r, g, b = int(h_str[0:2], 16), int(h_str[2:4], 16), int(h_str[4:6], 16)
    except ValueError:
        return (0.0, 0.5, 0.5)
    h, lightness, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    return (h * 360.0, s, lightness)


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b by factor t."""
    return a + (b - a) * t


def _find_indicator_seed(theme_hues: list[float]) -> float:
    """Find seed hue in the largest angular gap between theme hues.

    // [LAW:one-source-of-truth] Single algorithm for gap detection.
    """
    if not theme_hues:
        return 30.0  # warm fallback when no theme colors

    # Deduplicate and sort
    sorted_hues = sorted(set(h % 360 for h in theme_hues))
    if len(sorted_hues) < 2:
        return (sorted_hues[0] + 180.0) % 360

    # Find the largest angular gap
    best_gap = 0.0
    best_mid = 0.0
    for i in range(len(sorted_hues)):
        h1 = sorted_hues[i]
        h2 = sorted_hues[(i + 1) % len(sorted_hues)]
        gap = (h2 - h1) % 360
        if gap > best_gap:
            best_gap = gap
            best_mid = (h1 + gap / 2) % 360

    return best_mid


def _wcag_relative_luminance(hex_color: str) -> float:
    """Compute WCAG 2.1 relative luminance from #RRGGBB hex."""
    r, g, b = _hex_to_rgb(hex_color)
    rs, gs, bs = r / 255.0, g / 255.0, b / 255.0

    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * linearize(rs) + 0.7152 * linearize(gs) + 0.0722 * linearize(bs)


def _wcag_contrast(hex1: str, hex2: str) -> float:
    """WCAG 2.1 contrast ratio between two hex colors."""
    l1 = _wcag_relative_luminance(hex1)
    l2 = _wcag_relative_luminance(hex2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def generate_filter_colors(
    primary: str,
    secondary: str,
    accent: str,
    background: str,
    foreground: str,
    surface: str,
) -> dict[str, tuple[str, str, str]]:
    """Generate theme-relative filter indicator colors.

    Returns dict mapping filter name to (gutter_fg_hex, chip_bg_hex, chip_fg_hex).

    // [LAW:one-source-of-truth] Single function for all filter color derivation.
    // [LAW:dataflow-not-control-flow] All parameters are values; computation is unconditional.

    Algorithm:
    1. Extract hues from theme primary/secondary/accent
    2. Find largest hue gap → seed indicator hues there
    3. Derive S/L from theme luminance range (bg, surface, fg)
    4. Per-hue WCAG contrast enforcement for chip fg/bg
    """
    # Step 1: Extract theme hues
    theme_hues: list[float] = []
    for hex_color in (primary, secondary, accent):
        h, s, _ = _hex_to_hsl(hex_color)
        if s > 0.05:  # skip near-achromatic
            theme_hues.append(h)

    # Step 2: Find seed hue in largest gap
    seed = _find_indicator_seed(theme_hues)

    # Step 3: Generate hues via golden angle from seed
    n_hues = len(_FILTER_INDICATOR_INDEX)
    hues = [(seed + i * GOLDEN_ANGLE) % 360 for i in range(n_hues)]

    # Step 4: Compute luminances from theme
    _, _, bg_l = _hex_to_hsl(background)
    _, _, surface_l = _hex_to_hsl(surface)
    _, _, fg_l = _hex_to_hsl(foreground)
    _, primary_s, _ = _hex_to_hsl(primary)

    is_dark = bg_l < fg_l

    # Gutter foreground: midpoint of bg→fg range, pushed away from bg
    gutter_l = _lerp(bg_l, fg_l, 0.50)
    min_gutter_dist = 0.20
    if abs(gutter_l - bg_l) < min_gutter_dist:
        gutter_l = bg_l + min_gutter_dist if is_dark else bg_l - min_gutter_dist
    gutter_l = max(0.05, min(0.95, gutter_l))

    # Chip background: pushed away from surface by ΔL≥0.20
    # Extra margin provides room for per-hue contrast adjustments (phase 2)
    # without violating the surface proximity constraint.
    chip_bg_l = surface_l + (0.20 if is_dark else -0.20)
    chip_bg_l = max(0.05, min(0.95, chip_bg_l))

    # Chip foreground: initial target pushed away from chip_bg
    chip_fg_l_base = chip_bg_l + (0.45 if is_dark else -0.45)
    if is_dark:
        chip_fg_l_base = max(chip_fg_l_base, 0.80)
    else:
        chip_fg_l_base = min(chip_fg_l_base, 0.20)
    chip_fg_l_base = max(0.05, min(0.95, chip_fg_l_base))

    # Step 5: Compute saturations from primary_S
    gutter_s = max(0.45, min(0.85, primary_s * 0.90))
    chip_bg_s = max(0.25, min(0.60, gutter_s * 0.55))
    chip_fg_s = max(0.10, min(0.35, gutter_s * 0.25))

    # Step 6: Map hue[i] → filter name, with per-hue WCAG contrast enforcement.
    #
    # HSL lightness doesn't map linearly to WCAG luminance — green-yellow
    # hues have much higher luminance at the same HSL L due to the 0.7152
    # green coefficient. We enforce contrast in escalating phases:
    # Phase 1: Push chip_fg L toward extreme
    # Phase 2: Desaturate chip_fg (achromatic maximizes luminance at given L)
    # Phase 3: Darken chip_bg L (with surface proximity floor)
    # Phase 4: Desaturate chip_bg (reduces green/yellow WCAG luminance)
    min_contrast = 4.6  # target slightly above 4.5 for rounding margin
    result: dict[str, tuple[str, str, str]] = {}
    for name, idx in _FILTER_INDICATOR_INDEX.items():
        h = hues[idx]
        gutter_fg = _hsl_to_hex(h, gutter_s, gutter_l)

        bg_l = chip_bg_l
        bg_s = chip_bg_s
        fg_l = chip_fg_l_base
        fg_s = chip_fg_s
        chip_bg = _hsl_to_hex(h, bg_s, bg_l)
        chip_fg = _hsl_to_hex(h, fg_s, fg_l)
        contrast = _wcag_contrast(chip_fg, chip_bg)

        # Phase 1: push chip_fg L toward extreme
        fg_step = 0.03 if is_dark else -0.03
        iterations = 6
        while contrast < min_contrast and iterations > 0:
            fg_l = max(0.05, min(0.95, fg_l + fg_step))
            chip_fg = _hsl_to_hex(h, fg_s, fg_l)
            contrast = _wcag_contrast(chip_fg, chip_bg)
            iterations -= 1

        # Phase 2: desaturate chip_fg (achromatic maximizes luminance at given L)
        iterations = 8
        while contrast < min_contrast and fg_s > 0.01 and iterations > 0:
            fg_s = max(0.0, fg_s - 0.04)
            chip_fg = _hsl_to_hex(h, fg_s, fg_l)
            contrast = _wcag_contrast(chip_fg, chip_bg)
            iterations -= 1

        # Phase 3: darken/lighten chip_bg L with surface proximity floor
        bg_step = -0.02 if is_dark else 0.02
        min_surface_dist = 0.10
        iterations = 10
        while contrast < min_contrast and iterations > 0:
            candidate = bg_l + bg_step
            if abs(candidate - surface_l) < min_surface_dist:
                break
            bg_l = max(0.05, min(0.95, candidate))
            chip_bg = _hsl_to_hex(h, bg_s, bg_l)
            contrast = _wcag_contrast(chip_fg, chip_bg)
            iterations -= 1

        # Phase 4: desaturate chip_bg (reduces green/yellow WCAG luminance
        # because green channel has highest WCAG weight 0.7152)
        iterations = 10
        while contrast < min_contrast and bg_s > 0.01 and iterations > 0:
            bg_s = max(0.0, bg_s - 0.03)
            chip_bg = _hsl_to_hex(h, bg_s, bg_l)
            contrast = _wcag_contrast(chip_fg, chip_bg)
            iterations -= 1

        result[name] = (gutter_fg, chip_bg, chip_fg)

    return result


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

    def fg_on_bg_for_mode(self, index: int, dark: bool = True) -> tuple[str, str]:
        """(fg, bg) pair with mode-aware lightness.

        Dark mode: fg L=0.70, bg L=0.25 (current defaults).
        Light mode: fg L=0.35, bg L=0.88 (darker text, lighter background).
        """
        hue = self._hues[index % self._count]
        if dark:
            fg = _hsl_to_hex(hue, 0.75, 0.70)
            bg = _hsl_to_hex(hue, 0.60, 0.25)
        else:
            fg = _hsl_to_hex(hue, 0.75, 0.35)
            bg = _hsl_to_hex(hue, 0.45, 0.88)
        return fg, bg

    def msg_color_for_mode(self, index: int, dark: bool = True) -> str:
        """Message color with mode-aware lightness.

        Dark mode: L=0.70. Light mode: L=0.40.
        """
        hue = self._hues[(12 + index) % self._count]
        lightness = 0.70 if dark else 0.40
        return _hsl_to_hex(hue, 0.75, lightness)


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
