# Sprint 8: tmux-orchestration - surview wrap command
Generated: 2026-02-06
Confidence: HIGH: 1, MEDIUM: 1, LOW: 1
Status: RESEARCH REQUIRED

## Sprint Goal
Implement `surview wrap -- <command>` for tmux split-pane orchestration: surview TUI in one pane, target app in the other with proxy environment configured.

## Scope
**Deliverables:**
- `surview wrap` CLI subcommand
- tmux session creation with split panes
- Proxy environment auto-configuration
- Clean session teardown

## Work Items

### P0: Basic tmux orchestration
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `surview wrap -- curl https://httpbin.org/get` creates tmux session
- [ ] Left pane: surview TUI with proxy
- [ ] Right pane: target command with HTTP_PROXY/HTTPS_PROXY set
- [ ] Free port auto-selection
- [ ] tmux availability check with helpful error message

**Technical Notes:**
```bash
tmux new-session -d -s surview-<pid> \
  "surview --port <port>"
tmux split-window -h -t surview-<pid> \
  "HTTP_PROXY=http://127.0.0.1:<port> HTTPS_PROXY=http://127.0.0.1:<port> <command>"
tmux attach -t surview-<pid>
```

### P1: Reverse proxy mode for HTTPS
**Confidence: MEDIUM**
**Acceptance Criteria:**
- [ ] `surview wrap --target https://api.example.com --env API_URL -- myapp` works
- [ ] Sets specified env var to point at surview proxy
- [ ] Reverse proxy mode forwards to --target

#### Unknowns to Resolve
- How to handle HTTPS? HTTP_PROXY only works for HTTP traffic. For HTTPS, need either MITM certs or reverse proxy mode.
- **Decision for MVP**: Use reverse proxy mode. The `--target` + `--env` flags let users point their app at surview.

#### Exit Criteria
- Can debug HTTPS API traffic via reverse proxy mode
- Clear documentation of when to use --target vs HTTP_PROXY

### P2: Session lifecycle and cleanup
**Confidence: LOW**
**Acceptance Criteria:**
- [ ] When target command exits, surview TUI stays running
- [ ] When user quits surview (q), tmux session is killed
- [ ] Ctrl-C in surview pane triggers clean shutdown
- [ ] No orphaned tmux sessions after normal usage

#### Unknowns to Resolve
- How to detect target command exit from surview pane?
- Should surview auto-exit when target exits, or stay for HAR review?
- What about nested tmux (user already in tmux)?

#### Exit Criteria
- No orphaned tmux sessions in normal usage patterns
- Works both inside and outside existing tmux sessions

## Dependencies
- Sprint 5 (working TUI — surview must start and display traffic)
- Independent of Sprints 6-7 (DB/HAR not required for basic orchestration)

## Risks
- **tmux not installed**: Must detect and give clear install instructions
- **Nested tmux**: Running inside existing tmux session needs careful handling (tmux new-window vs new-session)
- **Port conflicts**: Auto-port selection should retry on EADDRINUSE
