# Theme Variable Reference (Common Across All Themes)

This is the condensed list of theme variables that exist in every available Textual theme in this runtime.

Normalization rules applied:

- Values removed (variable names only)
- Deduplicated
- Numeric suffix families collapsed to range notation
- Example: `surface-lighten-1`, `surface-lighten-2`, `surface-lighten-3` -> `surface-lighten-[1-3]`

Theme set used (18):

`atom-one-dark`, `atom-one-light`, `catppuccin-latte`, `catppuccin-mocha`, `dracula`, `flexoki`, `gruvbox`, `monokai`, `nord`, `rose-pine`, `rose-pine-dawn`, `rose-pine-moon`, `solarized-dark`, `solarized-light`, `textual-ansi`, `textual-dark`, `textual-light`, `tokyo-night`

Counts:

- Raw common variables: `163`
- Condensed variables: `111`

## Condensed Common Variable List

```text
accent
accent-darken-[1-3]
accent-lighten-[1-3]
accent-muted
background
background-darken-[1-3]
background-lighten-[1-3]
block-cursor-background
block-cursor-blurred-background
block-cursor-blurred-foreground
block-cursor-blurred-text-style
block-cursor-foreground
block-cursor-text-style
block-hover-background
boost
boost-darken-[1-3]
boost-lighten-[1-3]
border
border-blurred
button-color-foreground
button-focus-text-style
button-foreground
error
error-darken-[1-3]
error-lighten-[1-3]
error-muted
footer-background
footer-description-background
footer-description-foreground
footer-foreground
footer-item-background
footer-key-background
footer-key-foreground
foreground
foreground-darken-[1-3]
foreground-disabled
foreground-lighten-[1-3]
foreground-muted
input-cursor-background
input-cursor-foreground
input-cursor-text-style
input-selection-background
link-background
link-background-hover
link-color
link-color-hover
link-style
link-style-hover
markdown-h1-background
markdown-h1-color
markdown-h1-text-style
markdown-h2-background
markdown-h2-color
markdown-h2-text-style
markdown-h3-background
markdown-h3-color
markdown-h3-text-style
markdown-h4-background
markdown-h4-color
markdown-h4-text-style
markdown-h5-background
markdown-h5-color
markdown-h5-text-style
markdown-h6-background
markdown-h6-color
markdown-h6-text-style
panel
panel-darken-[1-3]
panel-lighten-[1-3]
primary
primary-background
primary-background-darken-[1-3]
primary-background-lighten-[1-3]
primary-darken-[1-3]
primary-lighten-[1-3]
primary-muted
scrollbar
scrollbar-active
scrollbar-background
scrollbar-background-active
scrollbar-background-hover
scrollbar-corner-color
scrollbar-hover
secondary
secondary-background
secondary-background-darken-[1-3]
secondary-background-lighten-[1-3]
secondary-darken-[1-3]
secondary-lighten-[1-3]
secondary-muted
success
success-darken-[1-3]
success-lighten-[1-3]
success-muted
surface
surface-active
surface-darken-[1-3]
surface-lighten-[1-3]
text
text-accent
text-disabled
text-error
text-muted
text-primary
text-secondary
text-success
text-warning
warning
warning-darken-[1-3]
warning-lighten-[1-3]
warning-muted
```

## Re-generate

```bash
uv run python - <<'PY'
from collections import defaultdict
import re
from textual.app import App

app = App()
names = sorted(app.available_themes.keys())
common = None
for name in names:
    keys = set(app.available_themes[name].to_color_system().generate().keys())
    common = keys if common is None else (common & keys)

level_groups = defaultdict(set)
out = []
for key in sorted(common):
    m = re.match(r'^(.*?)-(\\d+)$', key)
    if m:
        level_groups[m.group(1)].add(int(m.group(2)))
    else:
        out.append(key)

for base in sorted(level_groups):
    levels = sorted(level_groups[base])
    if len(levels) == 1:
        out.append(f"{base}-{levels[0]}")
    else:
        out.append(f"{base}-[{levels[0]}-{levels[-1]}]")

print(f"themes={len(names)}")
print(f"common_raw={len(common)}")
print(f"common_condensed={len(out)}")
for item in sorted(out):
    print(item)
PY
```
