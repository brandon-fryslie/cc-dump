# Definition of Done: auto-registration

## Completion Criteria

### Module Discovery
- [ ] `_RELOAD_ORDER` list removed from hot_reload.py
- [ ] Replaced with `_discover_modules()` function
- [ ] All current reloadable modules are discovered
- [ ] Stable boundaries excluded via `_STABLE_BOUNDARY` set
- [ ] Test: Add dummy module, verify it's discovered

### Dependency Ordering
- [ ] `_compute_reload_order()` function exists
- [ ] Uses AST to parse imports
- [ ] Returns topologically sorted module list
- [ ] Handles modules with no internal imports
- [ ] Test: formatting.py reloaded after colors.py

### Dynamic Addition (if MEDIUM item resolved)
- [ ] New module detected within one check cycle
- [ ] New module importable after detection
- [ ] No crash if new module has syntax error
- [ ] Warning logged for circular dependency

## Verification Commands
```bash
# Run hot-reload and verify all modules discovered
python -c "
import cc_dump.hot_reload as hr
hr.init('src/cc_dump')
modules = hr._discover_modules()
print('Discovered:', modules)
"

# Verify dependency order
python -c "
import cc_dump.hot_reload as hr
hr.init('src/cc_dump')
order = hr._compute_reload_order()
print('Reload order:', order)
"

# Integration test
python -m pytest tests/test_hot_reload.py::test_auto_registration -v
```

## Not In Scope
- Cross-package imports (only cc_dump.* tracked)
- Conditional imports (only static import statements)
- Import hooks or lazy imports
