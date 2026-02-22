# 04 Proxy Interception For Latency And Rich Data

Goal:
- Intercept side-channel traffic in proxy to reduce end-to-end latency and capture richer response details than CLI print output alone.

`// [LAW:single-enforcer] Interception/routing decision should happen once in proxy ingress.`
`// [LAW:dataflow-not-control-flow] Primary and side-channel requests share pipeline stages; metadata drives sink behavior.`

## How it could work

- Tag side-channel requests at request body stage.
- Stream response tokens/events to existing sinks immediately.
- Keep main client response path intact while side-channel lane gets structured event feed.
- Capture usage/cache counters from response stream events.

## Value

- Lower perceived latency for feature consumers.
- Better observability into streamed response behavior.
- More accurate analytics than stdout-only parsing.

## Rough token cost

- Interception itself: no extra tokens.
- If it enables more frequent requests, aggregate usage may rise.

## Ready to start?

Yes (as a spike).

Unknowns:
- best marker shape that is robust and non-intrusive
- sink composition that guarantees no cross-lane leakage

Definition of ready:
- side-channel stream visible earlier than subprocess completion
- no contamination of primary lane/event subscribers

