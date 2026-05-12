# 36 - Reflection Loop

## Summary

Adds a post-turn reflection layer that can analyse one completed chat/debug turn and create safe change proposals. Reflection does not directly mutate long-term memory, skills, entity states, goals, or FAISS. It uses the Safe Change Proposals workflow from patch 35.

## Added

- `mozok/reflection/schemas.py`
- `mozok/reflection/service.py`
- `mozok/api/reflection_routes.py`
- `POST /agents/{agent_id}/reflection/preview`
- `POST /agents/{agent_id}/reflection/run`
- Optional `/chat` fields for running reflection after a model response.

## Chat fields

- `enable_reflection_loop`
- `reflection_approval_mode`
- `reflection_auto_apply`
- `reflection_store_proposals`
- `reflection_outcome`
- `reflection_feedback`

## Behaviour

Reflection can propose:

- compact episodic memory from the turn;
- agent metadata update with last reflection summary;
- procedural skill usage result when a skill participated in the cognitive broadcast.

These are proposals, not direct writes. Automatic application is possible only through the configured proposal approval policy.

## Scenario import note

The importer already supports storing cognitive/perception/reflection policy inside agent metadata. A future scenario import standardisation pass should add first-class pack sections for cognitive profiles, perception profiles, and change-approval policies.
