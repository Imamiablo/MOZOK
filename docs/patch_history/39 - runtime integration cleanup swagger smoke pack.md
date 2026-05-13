# 39 - Runtime Integration Cleanup Swagger Smoke Pack

## Summary

Adds a read-only runtime integration status endpoint, verifies new runtime routes are visible in OpenAPI/Swagger, and fixes the v38 AgentModeService explicit-mode call path.

## Safety

- Read-only by default.
- No direct tool execution.
- World actions remain adapter-owned.
- Stored changes go through ChangeProposal where applicable.

## Tests

Added `tests/unit/test_runtime_event_eval_v39_42.py`.
