# Footer Icon Mockups

Current footer shows level only: `·` (existence), `◐` (summary), `●` (full)
New design shows level + expansion state in a single character.

## Example Footer States

**Legend:**
- Gray text = inactive/disabled
- Colored text = active (category-specific colors)
- Icon shows: level (1/2/3) + expansion (collapsed/expanded)

---

## Option 1: Medium Triangles `◁▽▶▼`

**Scenario: Mixed state (summary collapsed, full expanded, etc.)**

```
1 ◁headers   2 ▽user   3 ▶assistant   4 ▼tools   5 ◁system   6 ·budget   7 ·metadata
8 economics  9 timeline  0 follow  r reload  / search  q quit
```

With colors (imagined):
- `1 ◁headers` (dim gray - existence)
- `2 ▽user` (bright yellow - summary expanded)
- `3 ▶assistant` (cyan - full collapsed)
- `4 ▼tools` (green - full expanded)
- `5 ◁system` (magenta - summary collapsed)
- `6 ·budget` (dim gray - existence)
- `7 ·metadata` (dim gray - existence)

**Visual weight:** Medium-large, clear direction

---

## Option 2: Squares/Boxes `▫▪□■`

**Same scenario:**

```
1 ·headers   2 ▪user   3 □assistant   4 ■tools   5 ▫system   6 ·budget   7 ·metadata
8 economics  9 timeline  0 follow  r reload  / search  q quit
```

With colors:
- `1 ·headers` (dim gray - existence)
- `2 ▪user` (bright yellow - summary expanded, small filled)
- `3 □assistant` (cyan - full collapsed, medium outline)
- `4 ■tools` (green - full expanded, medium filled)
- `5 ▫system` (magenta - summary collapsed, small outline)
- `6 ·budget` (dim gray - existence)
- `7 ·metadata` (dim gray - existence)

**Visual weight:** Heavier, loses directional metaphor

---

## Option 3: Circles `·○◉●`

**Same scenario:**

```
1 ·headers   2 ◉user   3 ◎assistant   4 ●tools   5 ○system   6 ·budget   7 ·metadata
8 economics  9 timeline  0 follow  r reload  / search  q quit
```

Mapping:
- `·` existence
- `○` summary collapsed (outline)
- `◉` summary expanded (fisheye)
- `◎` full collapsed (bullseye)
- `●` full expanded (filled)

**Visual weight:** Medium, abstract (no clear direction)

---

## Option 4: Heavy Arrows `⇨⇩⮕⬇`

**Same scenario:**

```
1 ⇨headers   2 ⇩user   3 ⮕assistant   4 ⬇tools   5 ⇨system   6 ·budget   7 ·metadata
8 economics  9 timeline  0 follow  r reload  / search  q quit
```

With colors:
- `1 ⇨headers` (dim - existence, but shouldn't have arrow...)
- `2 ⇩user` (bright yellow - summary expanded)
- `3 ⮕assistant` (cyan - full collapsed)
- `4 ⬇tools` (green - full expanded)
- `5 ⇨system` (magenta - summary collapsed)

**Issue:** Heavy arrows might not render in all terminals, need fallback

---

## Recommended: Option 1 with Color Scheme

**Full example showing all 5 states for one category:**

```
·headers    (gray)          - EXISTENCE (level 1)
◁headers    (dim yellow)    - SUMMARY collapsed
▽headers    (yellow)        - SUMMARY expanded
▶headers    (dim cyan)      - FULL collapsed
▼headers    (bright cyan)   - FULL expanded
```

**Visual hierarchy:**
- Brightness: existence (dim) → summary (medium) → full (bright)
- Icon size: dot (tiny) → outline triangle (medium) → filled triangle (medium)
- Direction: right = collapsed, down = expanded

**Color palette suggestion:**
```
·    gray/#666        (existence - barely there)
◁▽   category color   (summary - medium intensity)
▶▼   category color   (full - bright/saturated)
```

---

## Implementation Notes

In `custom_footer.py`, replace line 68:

```python
# OLD:
_LEVEL_ICONS = {1: "\u00b7", 2: "\u25d0", 3: "\u25cf"}

# NEW (Option 1):
_LEVEL_ICONS = {
    (1, False): "\u00b7",  # · existence (no expansion)
    (1, True):  "\u00b7",  # · existence (no expansion)
    (2, False): "\u25c1",  # ◁ summary collapsed
    (2, True):  "\u25bd",  # ▽ summary expanded
    (3, False): "\u25b6",  # ▶ full collapsed
    (3, True):  "\u25bc",  # ▼ full expanded
}
```

Now needs `(level, expanded)` tuple lookup instead of just `level`.
