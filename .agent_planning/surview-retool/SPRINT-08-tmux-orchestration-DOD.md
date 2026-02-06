# Definition of Done: Sprint 8 - tmux Orchestration

## Exit Criteria
1. `surview wrap -- curl https://httpbin.org/get` creates tmux split-pane
2. Target command's HTTP traffic appears in surview TUI
3. No orphaned tmux sessions after quit
4. `surview wrap --target https://api.example.com --env API_BASE -- myapp` works

## Verification
```bash
# Test basic wrap
surview wrap -- curl -s https://httpbin.org/get
# Should see: tmux split with surview TUI + curl output

# Test reverse proxy wrap
surview wrap --target https://api.example.com --env API_URL -- bash -c 'curl $API_URL/status'

# Test tmux cleanup
tmux list-sessions | grep surview
# After quitting, no surview sessions should remain
```
