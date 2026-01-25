# Definition of Done: protocol-definition

## Completion Criteria

### Protocol Implementation
- [ ] `tui/protocols.py` exists with `HotSwappableWidget` protocol
- [ ] Protocol is type-checkable (mypy or pyright passes)
- [ ] All 4 widgets satisfy the protocol (verified by type checker or runtime check)
- [ ] Factory functions in `widget_factory.py` have return type annotations

### Documentation
- [ ] `HOT_RELOAD_ARCHITECTURE.md` exists
- [ ] Covers all three module categories with file lists
- [ ] Includes "Add new module" instructions
- [ ] Includes "Add new widget" instructions
- [ ] Code examples are syntactically correct

### Import Validation
- [ ] Validation script or test exists
- [ ] Catches `from cc_dump.formatting import X` in stable modules
- [ ] Reports actionable error messages
- [ ] Passes on current codebase (no violations)

## Verification Commands
```bash
# Type check protocols (if mypy installed)
python -m mypy src/cc_dump/tui/protocols.py

# Run import validation
python -m pytest tests/test_hot_reload.py -v

# Verify docs exist
cat HOT_RELOAD_ARCHITECTURE.md | head -20
```

## Not In Scope
- Automated dependency ordering (Sprint 2)
- State versioning (future work)
- CI integration (future work)
