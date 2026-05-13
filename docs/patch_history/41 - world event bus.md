# 41 - World Event Bus

## Summary

Adds a metadata-backed adapter-neutral World Event Bus with create/search/to-perception endpoints. This is intentionally flexible for games, assistants, UI events, tools, simulations, and future robotics adapters.

## Safety

- Read-only by default.
- No direct tool execution.
- World actions remain adapter-owned.
- Stored changes go through ChangeProposal where applicable.

## Tests

Added `tests/unit/test_runtime_event_eval_v39_42.py`.
