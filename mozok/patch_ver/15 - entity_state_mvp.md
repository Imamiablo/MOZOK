# Patch 15 — Entity State MVP

## Goal

Replace the too-narrow idea of `relationship memory` with a broader backend-friendly concept: `AgentEntityState`.

This supports multiple use cases:

- `social_relationship` — RPG/Simulacra NPC relationship state.
- `assistant_user_profile` — assistant's structured model of a user.
- `narrative_entity` — narrator continuity model for story entities.
- `faction_reputation` — game faction status.
- `quest_relevance` — quest/story relevance state.

## Added

- `mozok/entity_state/models.py`
- `mozok/entity_state/service.py`
- `mozok/schemas/entity_state.py`
- `mozok/api/entity_state_routes.py`
- unit tests for prompt-line formatting
- FastAPI OpenAPI contract test for entity-state routes

## Endpoints

```text
POST   /entity-states/upsert
PATCH  /entity-states/{state_id}
DELETE /entity-states/{state_id}
GET    /agents/{agent_id}/entity-states
GET    /agents/{agent_id}/entity-states/context
```

## Design choice

`state_kind` is a string, not an enum, so projects can add their own state categories without DB migrations.

`attributes_json` is flexible JSON, not hard-coded relationship columns. This avoids forcing assistant/narrator/faction systems into NPC emotion stats like `fear` or `resentment`.

## Still TODO

- Integrate entity states into `ContextBuilder`.
- Show entity states in `/debug/context` sections and pipeline steps.
- Add token budget trimming for entity-state context lines.
- Add optional LLM/manual updater later.
- Add integration tests with a real temporary DB.
