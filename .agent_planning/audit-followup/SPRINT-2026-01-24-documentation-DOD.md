# Definition of Done: documentation

## Verification Checklist

### ARCHITECTURE.md
1. [ ] File exists at `/Users/bmf/code/cc-dump/ARCHITECTURE.md`
2. [ ] Contains ASCII component diagram
3. [ ] Documents data flow: request → event → display/storage
4. [ ] Lists all modules with one-line responsibility description
5. [ ] Explains threading model (main, router, proxy threads)
6. [ ] Explains hot-reload architecture
7. [ ] Documents extension points (adding block types, subscribers)
8. [ ] References actual file paths in src/cc_dump/

### PROJECT_SPEC.md
9. [ ] File exists at `/Users/bmf/code/cc-dump/PROJECT_SPEC.md`
10. [ ] Has clear purpose statement (one sentence)
11. [ ] Identifies target users explicitly
12. [ ] Lists 5-7 core features
13. [ ] Lists 3-5 non-goals
14. [ ] Defines success criteria

### Quality
15. [ ] Both documents are <500 lines each (concise)
16. [ ] No external image dependencies (ASCII only)
17. [ ] Markdown renders correctly (no broken formatting)

## Pass Criteria

```bash
# Files exist
ls /Users/bmf/code/cc-dump/ARCHITECTURE.md
ls /Users/bmf/code/cc-dump/PROJECT_SPEC.md

# Check line counts (should be reasonable)
wc -l /Users/bmf/code/cc-dump/ARCHITECTURE.md  # <500
wc -l /Users/bmf/code/cc-dump/PROJECT_SPEC.md  # <200
```

## Manual Verification

1. Read ARCHITECTURE.md - can you understand the system in <10 minutes?
2. Read PROJECT_SPEC.md - is the project purpose clear in <2 minutes?
3. Check that sprint planning docs could reference these for alignment
