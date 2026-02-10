# Textual Documentation - Granular Reference

**42 focused files, 902KB total**

Organized in subdirectories:
- `core/` - Essential APIs for building apps
- `widgets/` - One file per widget
- `support/` - Grouped utility modules

Each file is small (10-50KB) and focused on a single concept.

## Core API (11 files)

Location: `textual-docs/core/`

- `app.xml` (92.7KB)
- `binding.xml` (10.2KB)
- `containers.xml` (6.1KB)
- `dom.xml` (35.3KB)
- `events.xml` (18.9KB)
- `messages.xml` (4.5KB)
- `pilot.xml` (17.0KB)
- `reactive.xml` (10.3KB)
- `screen.xml` (34.2KB)
- `widget.xml` (85.3KB)
- `worker.xml` (8.6KB)

## Widgets (27 files)

Location: `textual-docs/widgets/`

- `button.xml` (7.3KB)
- `checkbox.xml` (2.7KB)
- `collapsible.xml` (5.7KB)
- `data_table.xml` (53.7KB)
- `directory_tree.xml` (12.9KB)
- `footer.xml` (4.5KB)
- `header.xml` (5.2KB)
- `input.xml` (21.4KB)
- `label.xml` (2.4KB)
- `list_view.xml` (9.4KB)
- `loading_indicator.xml` (3.1KB)
- `log.xml` (7.8KB)
- `markdown.xml` (23.7KB)
- `option_list.xml` (20.5KB)
- `pretty.xml` (2.8KB)
- `progress_bar.xml` (8.6KB)
- `radio_button.xml` (2.9KB)
- `radio_set.xml` (8.2KB)
- `select.xml` (14.1KB)
- `selection_list.xml` (17.4KB)
- `sparkline.xml` (4.0KB)
- `static.xml` (3.9KB)
- `switch.xml` (4.7KB)
- `tabbed_content.xml` (16.0KB)
- `tabs.xml` (14.7KB)
- `text_area.xml` (53.9KB)
- `tree.xml` (27.8KB)

## Support Modules (4 files)

Location: `textual-docs/support/`

- `css.xml` (122.3KB)
- `geometry.xml` (41.4KB)
- `styling.xml` (28.8KB)
- `utils.xml` (27.4KB)

## Usage Examples

**Building a simple app:**
```python
# Read:
#   textual-docs/core/app.xml
#   textual-docs/core/widget.xml
#   textual-docs/widgets/button.xml
#   textual-docs/widgets/input.xml
```

**Working with DataTable:**
```python
# Read:
#   textual-docs/widgets/data_table.xml
#   textual-docs/core/reactive.xml
```

**Styling and themes:**
```python
# Read:
#   textual-docs/support/css.xml
#   textual-docs/support/styling.xml
```

## Generation

```bash
# First time: clone repo locally
git clone --depth 1 https://github.com/textualize/textual.git textual-repo

# Generate docs
python3 generate_granular_docs.py
```
