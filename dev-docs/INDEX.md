# Textual Documentation - Granular Reference

**42 focused files, 902KB total**

Each file is small (10-50KB) and focused on a single concept or widget.
Agents can quickly find exactly what they need without reading excess content.

## Core API (11 files)

Essential APIs for building Textual apps:

- `core-app.xml` (92.7KB)
- `core-binding.xml` (10.2KB)
- `core-containers.xml` (6.1KB)
- `core-dom.xml` (35.3KB)
- `core-events.xml` (18.9KB)
- `core-messages.xml` (4.5KB)
- `core-pilot.xml` (17.0KB)
- `core-reactive.xml` (10.3KB)
- `core-screen.xml` (34.2KB)
- `core-widget.xml` (85.3KB)
- `core-worker.xml` (8.6KB)

## Widgets (27 files)

One file per widget - only load what you need:

- `widget-button.xml` (7.3KB)
- `widget-checkbox.xml` (2.7KB)
- `widget-collapsible.xml` (5.7KB)
- `widget-data_table.xml` (53.7KB)
- `widget-directory_tree.xml` (12.9KB)
- `widget-footer.xml` (4.5KB)
- `widget-header.xml` (5.2KB)
- `widget-input.xml` (21.4KB)
- `widget-label.xml` (2.4KB)
- `widget-list_view.xml` (9.4KB)
- `widget-loading_indicator.xml` (3.1KB)
- `widget-log.xml` (7.8KB)
- `widget-markdown.xml` (23.7KB)
- `widget-option_list.xml` (20.5KB)
- `widget-pretty.xml` (2.8KB)
- `widget-progress_bar.xml` (8.6KB)
- `widget-radio_button.xml` (2.9KB)
- `widget-radio_set.xml` (8.2KB)
- `widget-select.xml` (14.1KB)
- `widget-selection_list.xml` (17.4KB)
- `widget-sparkline.xml` (4.0KB)
- `widget-static.xml` (3.9KB)
- `widget-switch.xml` (4.7KB)
- `widget-tabbed_content.xml` (16.0KB)
- `widget-tabs.xml` (14.7KB)
- `widget-text_area.xml` (53.9KB)
- `widget-tree.xml` (27.8KB)

## Support Modules (4 files)

Grouped by functionality:

- `support-css.xml` (122.3KB) - 
- `support-geometry.xml` (41.4KB) - 
- `support-styling.xml` (28.8KB) - 
- `support-utils.xml` (27.4KB) - 

## Usage Examples

**Building a simple app:**
```python
# Read: core-app.xml, core-widget.xml, widget-button.xml, widget-input.xml
```

**Working with DataTable:**
```python
# Read: widget-data_table.xml, core-reactive.xml
```

**Styling and themes:**
```python
# Read: support-css.xml, support-styling.xml
```

## Generation

```bash
# First time: clone repo locally
git clone --depth 1 https://github.com/textualize/textual.git textual-repo

# Generate docs
python3 generate_granular_docs.py
```
