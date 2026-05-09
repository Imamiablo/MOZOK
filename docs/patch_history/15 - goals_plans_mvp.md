# Patch 15 — Goals/Plans MVP

## Goal

Add a first-class goals/plans layer to Mozok.

This is intentionally separate from EntityState:

- `EntityState` answers: what structured state does an agent keep about an entity?
- `Goals/Plans` answers: what is this agent currently trying to do?

## Added

- `mozok/goals/models.py`
- `mozok/goals/service.py`
- `mozok/schemas/goals.py`
- `mozok/api/goal_routes.py`
- Goals/plans integration into `ContextBuilder`
- Goals/plans integration into `/debug/context`
- Goals/plans integration into `/chat`
- Token budget trimming for `goal_items`
- API tests for goals
- ContextBuilder unit tests for goals

## Endpoints

```text
POST   /goals/upsert
PATCH  /goals/{goal_id}
DELETE /goals/{goal_id}
GET    /agents/{agent_id}/goals
GET    /agents/{agent_id}/goals/context
```

## Design choice

Goals use one row per `agent_id + goal_key`.

Plan steps stay as flexible JSON for the MVP so games/apps can experiment with different plan shapes without database migrations.

## Context order

Goals/plans are placed early in the prompt:

```text
System instructions
Agent profile
Goals / plans
Entity state context
Lorebook / world knowledge
Memories
Current user message
Response guidance
```

## Still TODO

- Scenario import should later import `lorebook_entries`, `entity_states`, and `goals` together.
- Optional LLM/manual goal updater can be added later.
- Knowledge relations can later link goals to memories, lorebook entries, and entity states.
