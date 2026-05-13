# 42 - Evaluation Packs V2

## Summary

Adds Evaluation Packs V2 for context/cognition/perception/action regression checks without calling the LLM. This extends scenario evaluation beyond simple context assembly.

## Safety

- Read-only by default.
- No direct tool execution.
- World actions remain adapter-owned.
- Stored changes go through ChangeProposal where applicable.

## Tests

Added `tests/unit/test_runtime_event_eval_v39_42.py`.
