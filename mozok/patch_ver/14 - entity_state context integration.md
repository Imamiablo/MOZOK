# Patch 14 — EntityState Context Integration

## Goal

Make `AgentEntityState` usable by real chat/debug context, not only by standalone CRUD endpoints.

EntityStates now flow into the same context pipeline as Lorebook:

- `/debug/context`
- `/chat`
- prompt rendering
- debug sections
- pipeline step counts
- token-budget trimming

## Added / changed

- `ContextPackage.entity_state_items`
- `retrieved_entity_state_items` and `post_dedup_entity_state_items` snapshots
- `used_entity_state_ids()` helper
- `sections.entity_states` in `/debug/context`
- `used_entity_state_ids` and `used_entity_states_count` in debug output
- `used_entity_state_ids` and `used_entity_states_count` in `ChatResponse`
- `include_entity_states`, `entity_state_limit`, `entity_state_kind`, and `entity_state_entity_id` request fields for `/debug/context` and `/chat`
- token budget trimming support for `entity_state_items`
- unit tests for EntityState prompt/debug integration, filtering/isolation, and token-budget trimming

## Design note

`ContextBuilder.build()` keeps `include_entity_states=False` by default for direct internal calls/backward compatibility. The public `/debug/context` and `/chat` schemas default to `include_entity_states=True`, so normal API usage includes active EntityStates unless disabled.

## Manual Swagger checks

1. Create an EntityState with `POST /entity-states/upsert`.
2. Confirm standalone context with `GET /agents/{agent_id}/entity-states/context`.
3. Confirm integration with `POST /debug/context`:
   - `used_entity_states_count` should be greater than 0.
   - `sections.entity_states` should contain the state.
   - `full_prompt` should contain `Entity state context available to this agent:`.
4. Confirm `/chat` returns `used_entity_state_ids` and `used_entity_states_count`.
