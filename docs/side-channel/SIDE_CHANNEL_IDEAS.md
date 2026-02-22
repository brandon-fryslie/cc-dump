# Side-Channel Ideas

AI-powered enrichment via background `claude -p` processes. This doc records brainstormed applications and architectural strategies for the side-channel system.

## Applications

### MVP (Current)
- **Turn summaries** — summarize long assistant responses or tool results in a side panel

### Near-Term
- **System prompt diff explanations** — "what changed and why" when system prompt updates are detected
- **Content classification** — auto-tag turns by topic/intent (auth, debugging, refactoring, etc.)
- **Smart search** — semantic search over conversation content (beyond text matching)

### Longer-Term
- **Ongoing conversation compaction** — running summary maintained incrementally across turns
- **Shaped summaries** — user input field to guide summary focus ("focus on auth refactor, ignore debugging tangent")
- **Context reset / GC** — compact conversation into shaped summary, clear context, seed fresh session. Garbage collection for LLM context where the user controls what survives compaction.

## Architectural Strategies

### Proxy-Level Response Interception
Instead of waiting for `claude -p` stdout, tap the streaming response as it transits cc-dump's proxy. Lower latency — you see first tokens before `claude -p` even processes them.

### Sentinel-Based Traffic Routing
Include a sentinel marker in side-channel prompts. Proxy detects it, routes response to internal consumers, suppresses from main conversation view. Prevents side-channel traffic from mixing with observed sessions.

### Session Forking for Cache Hits
Duplicate the user's Claude Code session JSONL with a new local UUID. Modify outgoing API requests to use the real session ID so Anthropic's prompt cache hits (1-hour window). Locally it's a separate session — zero contamination risk. cc-dump is uniquely positioned for this since it sees all traffic and knows exactly what's cached.

### Persistent Claude Instance
Keep a `claude` process running to eliminate ~1s Node.js startup latency per request. Feed prompts via pty/stdin. Combined with proxy interception, this minimizes end-to-end latency.

### Request Body Replacement
Since cc-dump is the proxy, it can modify outgoing request bodies in transit. Claude Code generates the shape (correct API format, auth, etc.) while cc-dump stuffs the actual content. This enables cache-optimal requests without reimplementing the API client.

## Design Principles

1. **Opt-in** — always off by default in releases; costs user tokens even if minimal
2. **TOS-compliant** — uses `claude -p` which works with both API key and subscription users; no credential interception
3. **Fallback required** — everything must work without AI enrichment; DataDispatcher provides the boundary
4. **Structurally isolated** — side-channel traffic cannot accidentally mix with observed session data
5. **Outside the session** — cc-dump operates from a privileged vantage point *outside* the conversation, seeing things the model inside can't (cache hit rates, token costs, conversation drift)
