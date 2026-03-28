# Themes and Color System

> Status: draft
> Last verified against: not yet

## Overview

cc-dump displays a high volume of heterogeneous content: user messages, assistant responses, tool calls, system prompts, metadata, thinking blocks. Without a principled color system, this content collapses into visual noise. The theme system exists so that every piece of content has a distinguishable, semantically meaningful color assignment regardless of which terminal theme the user prefers, and so that colors remain accessible (readable contrast) across the full range of dark, light, and ANSI terminal environments.

From the user's perspective: content types are color-coded with consistent hues, gutter bars and footer chips identify categories at a glance, and pressing `[` or `]` cycles through 18 built-in themes. Colors adapt automatically to each theme's palette. No configuration is required beyond choosing a theme.

## Concepts

### Color Roles

Colors in the system serve four distinct roles:

1. **Theme semantic colors** -- directly from the Textual theme: `primary`, `secondary`, `accent`, `warning`, `error`, `success`, `foreground`, `background`, `surface`. These are the foundation.

2. **Content-type role colors** -- map API message roles to theme semantics:
   - User messages: `primary`
   - Assistant messages: `secondary`
   - System messages: `accent`
   - Info: `primary`

3. **Filter indicator colors** -- per-category hues for gutter bars and footer chips (tools, system, user, assistant, metadata, thinking). These are *generated* from theme colors, not hardcoded, and placed in the hue space where the theme is least busy.

4. **Palette colors** -- a golden-angle-spaced set of ~38 hues used for tag styling and message differentiation. These provide variety for content that needs many distinct colors (e.g., distinguishing multiple tool calls or conversation messages by index).

### ThemeColors

A frozen data object that captures every color the rendering pipeline needs, derived from a single Textual theme. Fields:

| Field | Type | Source |
|-------|------|--------|
| `primary` | hex string | theme primary (normalized) |
| `secondary` | hex string | theme secondary (normalized) |
| `accent` | hex string | theme accent (normalized) |
| `warning` | hex string | theme warning (normalized) |
| `error` | hex string | theme error (normalized) |
| `success` | hex string | theme success (normalized) |
| `foreground` | hex string | theme foreground (normalized) |
| `background` | hex string | theme background (normalized) |
| `surface` | hex string | theme surface (normalized) |
| `dark` | bool | theme dark mode flag |
| `user` | hex string | alias for `primary` |
| `assistant` | hex string | alias for `secondary` |
| `system` | hex string | alias for `accent` |
| `info` | hex string | alias for `primary` |
| `code_theme` | string | `"github-dark"` (dark) or `"friendly"` (light) |
| `search_all_bg` | hex string | `surface` |
| `search_current_style` | Rich style string | bold, inverted fg on accent |
| `follow_active_style` | Rich style string | bold, bg on fg (inverted) |
| `follow_engaged_style` | Rich style string | bold, fg on bg |
| `search_prompt_style` | Rich style string | bold primary |
| `search_active_style` | Rich style string | bold success |
| `search_error_style` | Rich style string | bold error |
| `search_keys_style` | Rich style string | bold warning |
| `markdown_theme_dict` | dict | Rich Theme entries for markdown rendering |
| `filter_colors` | dict | name to (gutter_fg, chip_bg, chip_fg) hex triples |
| `action_colors` | list | pool of theme semantic hex colors for non-filter UI items |

### Render Runtime

Theme-derived state that changes when the user switches themes. Includes:

- **role_styles**: `{"user": "bold <primary>", "assistant": "bold <secondary>", "system": "bold <accent>"}`
- **tag_styles**: list of 12 (fg, bg) hex pairs from the palette, mode-adjusted
- **msg_colors**: list of 6 foreground hex colors from the palette, mode-adjusted
- **filter_indicators**: dict mapping filter name to (symbol, fg_color) used for gutter rendering

## Theme Switching

The user cycles themes with `[` (previous) and `]` (next). The 18 available themes are sorted alphabetically and wrap cyclically. The selected theme name is persisted to settings.

When a theme changes, the following happens in order:

1. `ThemeColors` is rebuilt from the new Textual theme
2. Role styles, tag styles, message colors, and filter indicators are recomputed
3. The markdown Rich theme is popped and re-pushed on the console
4. All block strip caches and line caches are invalidated
5. All turns are re-rendered with `force=True` (because gutter colors changed even though filter state did not)
6. The footer is re-rendered with new chip colors
7. A theme generation counter is incremented (triggers reactive UI updates)
8. A notification toast shows the new theme name

### Available Themes (18)

`atom-one-dark`, `atom-one-light`, `catppuccin-latte`, `catppuccin-mocha`, `dracula`, `flexoki`, `gruvbox`, `monokai`, `nord`, `rose-pine`, `rose-pine-dawn`, `rose-pine-moon`, `solarized-dark`, `solarized-light`, `textual-ansi`, `textual-dark`, `textual-light`, `tokyo-night`

## Filter Indicator Color Generation

### Problem

Filter indicators (colored gutter bars and footer chips) must be visually distinct from each other, distinct from the theme's own UI colors, and maintain readable contrast -- across all 18 themes. Hardcoded colors fail because:

- Fixed hues can collide with a theme's primary/accent, making indicators invisible
- A fixed lightness value readable on one dark theme produces unreadable text on another (solarized-dark has a much narrower luminance range than textual-dark)
- Chip backgrounds can blend into the theme's footer surface

### Algorithm

The generation is a pure function: six theme hex colors in, a dictionary of (gutter_fg, chip_bg, chip_fg) triples out.

**Step 1: Extract theme hues.** Parse primary, secondary, and accent to HSL. Discard near-achromatic colors (saturation < 0.05).

**Step 2: Find the largest hue gap.** Treat the color wheel as circular, find the widest angular gap between theme hues. Place the indicator seed hue at the center of this gap. This ensures indicator hues occupy the least-used region of the color wheel. Example: a purple/pink/cyan theme (Dracula) gets indicators in the orange/yellow/green range.

**Step 3: Generate hues via golden-angle spacing.** From the seed, generate N hues at 137.508-degree increments. The golden angle maximizes perceptual distance between consecutively indexed colors.

**Step 4: Derive lightness from theme luminance range.** Extract HSL lightness from background, surface, and foreground. Compute:
- Gutter foreground: midpoint of bg-to-fg range, at least 0.20 L-distance from background
- Chip background: surface +/- 0.20 (pushed toward foreground)
- Chip foreground: chip_bg +/- 0.45 (toward foreground), floored at L >= 0.80 (dark themes) or <= 0.20 (light themes)

**Step 5: Derive saturation from theme.** Saturations decrease from gutter (most vivid) to chip bg (muted) to chip fg (near-neutral):
- Gutter fg: `primary_S * 0.90`, clamped to [0.45, 0.85]
- Chip bg: `gutter_S * 0.55`, clamped to [0.25, 0.60]
- Chip fg: `gutter_S * 0.25`, clamped to [0.10, 0.35]

**Step 6: Per-hue WCAG contrast enforcement.** For each hue, verify chip fg vs chip bg meets WCAG AA (target 4.6:1, slightly above the 4.5:1 threshold for rounding margin). If not, apply corrections in escalating phases:

1. Push chip fg lightness toward extreme (6 steps of 0.03)
2. Desaturate chip fg (8 steps of 0.04) -- achromatic maximizes luminance-to-lightness ratio
3. Darken/lighten chip bg (10 steps of 0.02) -- with a floor: must stay >= 0.10 L-distance from surface
4. Desaturate chip bg (10 steps of 0.03) -- reduces green-channel WCAG luminance inflation

This multi-phase approach is necessary because HSL lightness is a poor predictor of WCAG luminance. Green hues at the same HSL lightness as blue hues have ~10x higher WCAG luminance due to the 0.7152 green coefficient in the WCAG formula.

### Category Index Assignment

Each filter category has a fixed indicator index:

| Category | Indicator Index |
|----------|----------------|
| tools | 0 |
| system | 1 |
| metadata | 2 |
| user | 3 |
| assistant | 4 |
| thinking | 5 |

The six main categories use consecutive indices 0-5. This matters because the golden angle's minimum-separation guarantee only holds for consecutive indices. Non-consecutive indices can produce hue clusters (e.g., index 0 at 0 degrees and index 8 at 20.1 degrees would be nearly indistinguishable).

### Where Colors Appear

| Component | Color Used | Tuple Index |
|-----------|-----------|-------------|
| Gutter bars (left edge of content lines) | gutter_fg | [0] |
| Footer chip background | chip_bg | [1] |
| Footer chip foreground (text) | chip_fg | [2] |

Gutter bars use the `chip_bg` color (element [1]) for their foreground styling. The `gutter_fg` value (element [0]) is generated by the algorithm but is unused for gutter rendering.

## Palette

A secondary color source independent of theme-relative filter colors. Provides ~38 maximally-distinct hues for tag styling and message differentiation.

### Construction

- Seed hue: 190 degrees (cyan) by default, configurable via `CC_DUMP_SEED_HUE` environment variable
- Count: 38 colors
- Each hue is offset from seed by `i * 137.508` degrees (golden angle)
- Two lightness levels per hue:
  - Foreground: S=0.75, L=0.70 (text on dark backgrounds)
  - Dark background: S=0.60, L=0.25 (background highlights)
- Mode-aware variants adjust for light themes: fg L=0.40, bg S=0.45/L=0.88 (note: L=0.35 applies to tag foreground via `fg_on_bg_for_mode`, not to msg_color)

### Semantic Named Colors

The palette provides named colors by mapping to specific hue indices:

**Role colors** (indices 0-2, the first three golden-angle hues, maximally distinct):
- `user` -- palette index 0
- `assistant` -- palette index 1
- `system` -- palette index 2

Palette indices 3-10 are unreserved (not tightly packed after the role indices).

**Semantic colors** (mapped to closest unreserved hue matching target):
- `error` -- target hue 0 degrees (red)
- `warning` -- target hue 50 degrees (yellow)
- `success` -- target hue 130 degrees (green)
- `info` -- target hue 190 degrees (cyan)

Each semantic role has both foreground and dark-background variants (e.g., `palette.error` and `palette.error_bg`).

**Accent** -- palette index 11, tends toward warm/orange tones.

### Tag Colors

12 palette positions (indices 0-11) are used for tag styling. Each provides a (fg, bg) pair adjusted for the current theme's dark/light mode.

### Message Colors

6 palette positions starting at index 12 (after roles, filters, accent) provide foreground colors for message differentiation.

## ANSI Theme Handling

Textual's `textual-ansi` theme uses terminal ANSI color names (`ansi_blue`, `ansi_default`) instead of hex values. These require special handling:

- `ansi_default` is unknowable at runtime (the terminal decides the actual color)
- ANSI color names crash Rich's style parser if used directly
- The `dark` flag is unreliable for ANSI themes

**Normalization**: Every theme color passes through a normalizer that:
1. Converts `ansi_default` and `None` to a fallback hex value
2. Passes `#RRGGBB` strings through unchanged
3. Converts named ANSI colors (e.g., `ansi_blue`) to their hex equivalents via Textual's Color parser

**Dark mode detection for ANSI**: When background, foreground, and surface are all `ansi_default`, the system assumes dark mode. This avoids pastel indicator colors (appropriate for light themes) appearing on what is almost certainly a dark terminal.

**Markdown theme**: ANSI themes skip the Rich markdown theme push entirely, since the color names are incompatible with Rich's style parser.

## Markdown Theme

When a non-ANSI theme is active, a Rich `Theme` is pushed onto the app console to style markdown content. Styles are derived from the current theme's colors:

| Markdown Element | Style |
|-----------------|-------|
| text, paragraph, item | foreground |
| strong | bold foreground |
| em | italic foreground |
| code | foreground on surface |
| code_block | on surface |
| h1 | bold underline primary |
| h2 | bold primary |
| h3 | bold secondary |
| h4 | italic secondary |
| h5 | italic foreground |
| h6 | dim italic |
| link | underline primary |
| link_url | dim underline primary |
| block_quote | italic foreground |
| table border | dim foreground |
| table header | bold primary |
| hr | dim foreground |

The markdown theme is popped and re-pushed on every theme change.

## Action Colors

A pool of 6 theme semantic colors used for non-filter UI items (panels, toggles, etc.): accent, warning, success, error, primary, secondary. These are naturally distinct from filter indicator colors because the filter hues are placed in the gaps *between* these theme colors.

## Textual Theme Variables

All 18 themes share a common set of 163 CSS variables (111 after collapsing numeric suffix families). Key variable families:

- **Core**: `primary`, `secondary`, `accent`, `warning`, `error`, `success` -- each with `-darken-[1-3]`, `-lighten-[1-3]`, `-muted` variants
- **Surfaces**: `background`, `surface`, `panel`, `boost` -- each with darken/lighten variants
- **Text**: `foreground`, `text`, `text-muted`, `text-disabled`, `text-accent`, `text-primary`, `text-secondary`, `text-success`, `text-warning`, `text-error`
- **Footer**: `footer-background`, `footer-foreground`, `footer-key-background`, `footer-key-foreground`, `footer-description-background`, `footer-description-foreground`, `footer-item-background`
- **Scrollbar**: `scrollbar`, `scrollbar-hover`, `scrollbar-active`, `scrollbar-background`, `scrollbar-background-hover`, `scrollbar-background-active`, `scrollbar-corner-color`
- **Markdown**: `markdown-h[1-6]-background`, `markdown-h[1-6]-color`, `markdown-h[1-6]-text-style`

cc-dump uses these variables via Textual's theme object, not directly as CSS tokens. The rendering pipeline reads `theme.primary`, `theme.surface`, etc. and normalizes them to hex for use in Rich styles.

## Cross-References

- **Filter categories** that receive indicator colors are defined in the filter registry (see `spec/filters.md`)
- **Gutter bars** that consume filter indicator colors are part of the rendering pipeline (see `spec/rendering.md`)
- **Footer chips** that display filter colors are documented in the navigation spec (see `spec/navigation.md`)
- **Theme cycling keybindings** (`[` and `]`) are documented in the navigation spec (see `spec/navigation.md`)
- **Settings persistence** for theme selection is part of the session system (see `spec/sessions.md`)
