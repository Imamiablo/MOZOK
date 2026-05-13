# 40 - Agent Runtime Tick Mvp

## Summary

Adds POST /agents/{agent_id}/tick. A tick pulls recent world events, compiles perception, builds context, runs Cognitive Field, previews Self-Model, plans an ActionIntent, and optionally creates reviewable ChangeProposals. It does not execute tools or mutate game state.

## Safety

- Read-only by default.
- No direct tool execution.
- World actions remain adapter-owned.
- Stored changes go through ChangeProposal where applicable.

## Tests

Added `tests/unit/test_runtime_event_eval_v39_42.py`.
