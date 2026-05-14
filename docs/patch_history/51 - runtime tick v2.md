# 51 - Runtime Tick V2

Extended runtime ticks from a single-agent endpoint into a small multi-agent runtime workflow.

## Added

- `POST /runtime/tick/batch`
- `GET /agents/{agent_id}/tick/history`
- Tick history stored in agent metadata under `runtime_tick.history`.

## Scope

This is still not a background scheduler. It remains explicit and adapter-neutral: callers trigger ticks, inspect action plans, and decide what external systems should execute.
