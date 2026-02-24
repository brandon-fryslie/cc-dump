# Theme-Relative Filter Color Generation

How cc-dump generates per-category indicator colors (gutter bars and footer chips) that adapt to any Textual theme while guaranteeing accessibility contrast.

For a practical `$...` token reference used in CSS, see `docs/THEME_VARIABLE_REFERENCE.md`.

## The Problem

Filter indicators identify which category (user, assistant, tools, headers, etc.) each block belongs to. They appear in two places:

1. **Gutter bars** — colored `▌` / `▐` on the left/right edges of every content line
2. **Footer chips** — clickable category labels at the bottom of the screen with colored backgrounds

The original implementation used two hardcoded color sets — one for dark themes, one for light themes. This failed in multiple ways:

- **Blending with theme UI**: Fixed hues often coincided with a theme's primary/accent colors, making indicators invisible against the theme's own colored elements
- **Unreadable chip text**: Hardcoded lightness values that worked on one dark theme produced unreadable text on another (e.g., solarized-dark has a narrow luminance range between bg and fg)
- **Surface collision**: Chip backgrounds were indistinguishable from the theme's footer/panel surface color
- **No ANSI theme support**: Themes using terminal ANSI color names (`ansi_green`, `ansi_default`) can't be parsed as hex and crashed the renderer

## The Solution: Theme-Relative Generation

Instead of hardcoded colors, we derive indicator colors from the theme's actual color values. The algorithm has three main ideas:

1. **Place hues where the theme isn't** — find the largest gap in the color wheel between the theme's primary/secondary/accent hues, and seed indicator hues there
2. **Derive lightness from the theme's luminance range** — use the actual bg/surface/fg lightness values to position gutter and chip colors
3. **Enforce WCAG AA contrast per-hue** — because HSL lightness doesn't predict WCAG luminance uniformly across hues, run a per-hue correction loop

### Entry Points

- **`palette.py:generate_filter_colors()`** — pure function, theme colors in, indicator colors out
- **`rendering.py:build_theme_colors()`** — calls `generate_filter_colors()`, stores result in `ThemeColors.filter_colors`
- **`rendering.py:set_theme()`** — sole entry point for theme changes, rebuilds all module-level state

## Algorithm Detail

### Step 1: Extract Theme Hues

Parse the theme's primary, secondary, and accent colors to HSL. Skip near-achromatic colors (S < 0.05) since they don't occupy meaningful hue space.

```
theme_hues = [h for (h, s, l) in [primary, secondary, accent] if s > 0.05]
```

### Step 2: Find the Largest Hue Gap

Treat the hue wheel as a circular sequence. Find the largest angular gap between the sorted theme hues. The seed hue is placed at the center of this gap.

```
sorted_hues:  [210°, 280°, 340°]
gaps:          70°    60°   230° ← largest
seed:         340° + 230°/2 = 95° (yellow-green area)
```

This guarantees indicator hues occupy the part of the color wheel **least used by the theme**. A Dracula theme (purple/pink/cyan) gets indicators in the orange/yellow/green range. A Nord theme (blue/teal) gets indicators in the red/orange range.

If the theme has no chromatic colors, the seed defaults to 30° (warm orange).

### Step 3: Golden-Angle Hue Spread

Generate 10 hues by stepping from the seed at the golden angle (137.508°):

```
hue[i] = (seed + i * 137.508°) mod 360°
```

The golden angle is the optimal irrational rotation — it maximizes the minimum angular distance between any N **consecutively** assigned hues. This means `hue[0]` and `hue[1]` are never adjacent on the wheel, and even the first 3-4 hues are well-separated.

Each filter category maps to a fixed index (0-9) in this sequence via `_FILTER_INDICATOR_INDEX`, so the mapping is stable — "headers" is always index 0, "tools" is always index 1, etc.

#### Index Assignment Matters

The golden angle's separation guarantee only holds for **consecutive** indices. If you cherry-pick non-consecutive indices, hues can cluster. With 10 hues and indices 0-9, the offsets from seed are:

```
idx 0:   0.0°    idx 5: 327.5°
idx 1: 137.5°    idx 6: 105.0°
idx 2: 275.0°    idx 7: 242.6°
idx 3:  52.5°    idx 8:  20.1°
idx 4: 190.0°    idx 9: 157.6°
```

Notice: index 0 (0°) and index 8 (20.1°) are only **20° apart**. If the 7 main categories used indices {0,1,2,3,4,8,9}, the minimum hue gap would be ~20° — nearly indistinguishable on many monitors.

The fix: assign the 7 main gutter/footer categories to consecutive indices 0-6. Their sorted hues are 0°, 52.5°, 105°, 137.5°, 190°, 275°, 327.5° with a minimum gap of **32.5°** — a 63% improvement. The less-prominent action items (stats, economics, timeline) get indices 7-9.

### Step 4: Derive Lightness from Theme Luminance Range

Extract HSL lightness from the theme's background, surface, and foreground:

```
bg_L      = lightness(background)     e.g. 0.12 for textual-dark
surface_L = lightness(surface)        e.g. 0.17 for textual-dark
fg_L      = lightness(foreground)     e.g. 0.88 for textual-dark
is_dark   = bg_L < fg_L
```

**Gutter foreground** — the bar color in the content area:
- Midpoint of bg→fg range: `lerp(bg_L, fg_L, 0.50)`
- Pushed at least ΔL=0.20 from background (so it's visible against main content)

**Chip background** — the footer chip's background:
- Surface ± 0.20 (pushed toward foreground)
- This is deliberately generous — extra margin provides room for the per-hue contrast adjustment (Step 5) to darken the chip bg without hitting the surface proximity floor

**Chip foreground** — text on the chip:
- Initial target: chip_bg ± 0.45 (toward foreground)
- Floor/ceiling: L ≥ 0.80 on dark themes, L ≤ 0.20 on light themes
- This is just the starting point — per-hue WCAG enforcement adjusts it further

### Step 5: Saturation from Theme

Saturations are derived from the theme's primary color saturation, clamped to reasonable ranges:

| Role | Formula | Range |
|------|---------|-------|
| Gutter fg | `primary_S * 0.90` | [0.45, 0.85] |
| Chip bg | `gutter_S * 0.55` | [0.25, 0.60] |
| Chip fg | `gutter_S * 0.25` | [0.10, 0.35] |

The decreasing saturation from gutter → chip bg → chip fg creates a natural visual hierarchy: vivid gutter bars, muted chip backgrounds, near-neutral chip text.

### Step 6: Per-Hue WCAG Contrast Enforcement

This is the hardest and most important step. The problem: **HSL lightness is a poor predictor of WCAG luminance**, especially for green and yellow hues.

#### Why HSL Fails for Accessibility

WCAG 2.1 relative luminance is:

```
L = 0.2126 * R_linear + 0.7152 * G_linear + 0.0722 * B_linear
```

The green channel has **10x** the weight of blue. This means:

- A pure green (`#00FF00`) at HSL L=0.50 has WCAG luminance 0.7152
- A pure blue (`#0000FF`) at HSL L=0.50 has WCAG luminance 0.0722
- Same HSL lightness, **10x** difference in WCAG luminance

So a chip bg and chip fg that both look "far apart" in HSL can have terrible WCAG contrast if they're both greenish — they both get inflated WCAG luminance from the green channel.

#### The 4-Phase Enforcement Loop

For each of the 10 hues, after computing the initial chip bg and chip fg, we check WCAG contrast and run escalating corrections:

**Phase 1: Push chip fg lightness toward extreme** (6 iterations, ΔL=0.03/step)
```
while contrast < 4.6 and iterations > 0:
    fg_L += 0.03  (dark theme) or -0.03 (light theme)
```
Works for most hues. Fails when fg_L is already near ceiling (0.95) or the hue has high intrinsic WCAG luminance.

**Phase 2: Desaturate chip fg** (8 iterations, ΔS=0.04/step)
```
while contrast < 4.6 and fg_S > 0.01:
    fg_S -= 0.04
```
Achromatic colors maximize the lightness-to-luminance ratio — removing saturation from a greenish fg pushes its WCAG luminance toward the pure-lightness prediction. This is often enough to close the gap.

**Phase 3: Darken/lighten chip bg** (10 iterations, ΔL=0.02/step, with surface floor)
```
while contrast < 4.6:
    candidate = bg_L - 0.02  (dark) or + 0.02 (light)
    if |candidate - surface_L| < 0.10: break  # surface proximity floor
    bg_L = candidate
```
Moving the chip bg away from chip fg increases contrast. But we can't move it too close to the surface color, or the chip itself becomes invisible. The surface proximity floor (ΔL ≥ 0.10) prevents this.

**Phase 4: Desaturate chip bg** (10 iterations, ΔS=0.03/step)
```
while contrast < 4.6 and bg_S > 0.01:
    bg_S -= 0.03
```
The nuclear option. For green/yellow hues where the chip bg has high WCAG luminance due to the green channel, desaturating it reduces the green contribution and lowers its luminance. This is what finally resolves the hardest cases (e.g., green hue on solarized-dark where the fg/bg range is only L=0.15–0.55).

The target contrast is 4.6:1 (slightly above the WCAG AA threshold of 4.5:1) to provide rounding margin.

## ANSI Theme Handling

Textual's `textual-ansi` theme uses terminal ANSI color names instead of hex values:

| Theme field | Value |
|-------------|-------|
| primary | `"ansi_blue"` |
| foreground | `"ansi_default"` |
| background | `"ansi_default"` |
| surface | `"ansi_default"` |

Three problems arise:

1. **ANSI color names crash Rich**: `Style.parse("bold ansi_green on ansi_blue")` throws `StyleSyntaxError`
2. **`ansi_default` is unknowable**: It means "whatever the terminal uses" — we can't inspect it at runtime
3. **`dark` flag is unreliable**: The theme reports `dark=False` but the terminal may be dark

### Solution: `_normalize_color()`

A single normalizer in `rendering.py` handles all three:

```python
def _normalize_color(color: str | None, fallback: str) -> str:
    if color is None or color == "ansi_default":
        return fallback                        # unknowable → use fallback
    if color.startswith("#") and len(color) == 7:
        return color                           # already hex
    from textual.color import Color
    c = Color.parse(color)                     # "ansi_blue" → Color(0, 0, 255)
    return "#{:02X}{:02X}{:02X}".format(*c.rgb)
```

For the unknowable bg/fg/surface case, `build_theme_colors()` detects when all three are `ansi_default` and assumes dark mode for fallback values:

```python
assume_dark = dark or all(
    _is_ansi_default(getattr(textual_theme, attr))
    for attr in ("background", "foreground", "surface")
)
```

This avoids pastel indicator colors (appropriate for light themes) appearing on what is almost certainly a dark terminal.

## Render Pipeline Integration

### Theme Change Flow

```
User presses [ or ] (cycle theme)
  → App.watch_theme()
    → set_theme(textual_theme)         # rebuilds ThemeColors + FILTER_INDICATORS
    → conv._block_strip_cache.clear()  # invalidate cached block renders
    → conv._line_cache.clear()         # invalidate line-level cache
    → conv.rerender(filters, force=True)  # force all turns to re-render
    → _update_footer_state()           # re-render footer with new chip colors
```

The `force=True` on `rerender()` is critical — without it, `TurnData.re_render()` compares the filter snapshot and skips re-rendering when filters haven't changed. But a theme change means the gutter colors (read from module-level `FILTER_INDICATORS`) have changed even though filters haven't.

### Where Colors Are Consumed

| Component | Reads from | Color tuple index |
|-----------|-----------|-------------------|
| Gutter bars (`_add_gutter_to_strips()`) | `FILTER_INDICATORS[name]` | `[0]` gutter_fg |
| Footer chip bg | `tc.filter_colors[name]` | `[1]` chip_bg |
| Footer chip fg | `tc.filter_colors[name]` | `[2]` chip_fg |

## Test Coverage

`test_filter_indicators_adapt_to_theme` in `test_gutter_rendering.py` verifies across 5 themes (textual-dark, textual-light, dracula, solarized-dark, nord):

1. **Color variation**: Gutter colors differ between themes for each filter
2. **WCAG AA contrast**: Chip fg vs chip bg ratio ≥ 4.5:1 for all themes and all filters
3. **Surface separation**: Chip bg differs from surface by ΔL ≥ 0.10

## Lessons Learned

### HSL is Not Perceptual

HSL lightness treats all hues equally, but human vision (and WCAG's model of it) does not. Green light contributes 71.5% of perceived luminance, blue only 7.2%. Any algorithm that sets a "minimum lightness gap" in HSL space will fail for green/yellow hues.

The fix isn't to switch entirely to a perceptual color space (CIELAB, OKLCH) — those add complexity and dependencies. Instead, use HSL for initial placement (it's intuitive and cheap) and **validate with WCAG contrast** (which accounts for perceptual non-uniformity), then correct iteratively.

### Saturation Affects Luminance

Desaturating a color changes its WCAG luminance because it shifts the RGB channel balance toward equal parts. For a pure green, desaturation reduces the dominant green channel and increases red/blue, lowering total luminance. This is counterintuitive — "making a color more gray" actually changes its perceived brightness — but it's a powerful tool for contrast correction.

### Don't Hardcode for Dark/Light — Derive from Values

The original dark/light bifurcation failed because "dark" and "light" are not two fixed points — they're positions on a continuum. Solarized-dark has fg L=0.55 (much lower than most dark themes' ~0.88). Nord has bg L=0.18 (darker than textual-dark's 0.12). Any algorithm that says "if dark, use these values" will eventually encounter a theme that breaks the assumption.

Deriving from actual bg/surface/fg luminances handles the full continuum naturally.

### ANSI Themes Are a Special Case

ANSI themes can't tell you their actual colors at runtime — the terminal decides. The pragmatic solution is: detect the unknowable case, assume dark mode (TUI users overwhelmingly use dark terminals), and use conservative fallback values. Trying to probe the terminal's actual colors is unreliable and platform-dependent.

### Golden Angle Only Works for Consecutive Indices

The golden angle guarantees maximum minimum separation for N **consecutive** indices {0, 1, ..., N-1}. If you assign your N categories to non-consecutive indices (e.g., {0,1,2,3,4,8,9} for 7 categories out of 10), the guarantee breaks. Index 0 lands at 0° and index 8 at 20.1° — nearly identical hues despite being "different" palette entries.

The fix is trivial but easy to miss: always assign the categories you need to distinguish to consecutive indices. Less-important items get the leftover indices. This improved minimum separation from 20° to 32.5° for our 7 main categories.

### Surface Proximity Matters

A chip background that's readable (good fg/bg contrast) but indistinguishable from the footer panel surface is useless — the chip looks like plain text, not a chip. The ΔL ≥ 0.10 surface proximity constraint is just as important as the WCAG contrast constraint, and the two can conflict: darkening chip bg for contrast can push it toward surface. The solution is to give extra initial margin (ΔL=0.20 from surface) so there's room for contrast corrections.
