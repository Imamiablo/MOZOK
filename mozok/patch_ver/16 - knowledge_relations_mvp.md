# Patch 16 — Knowledge Relations MVP

## Goal

Add a generic relation table that can connect different kinds of Mozok knowledge nodes:

- memories
- lorebook entries
- entity states
- goals/plans
- plan steps
- agents/entities/factions/quests/locations/concepts

The relation is a directed edge:

```text
source_type:source_id --relation_type--> target_type:target_id
```

Example:

```text
goal:hide_tunnel_secret --depends_on--> lorebook:old_well
```

## Added

- `mozok/knowledge_relations/models.py`
- `mozok/knowledge_relations/service.py`
- `mozok/schemas/knowledge_relations.py`
- `mozok/api/knowledge_relation_routes.py`
- tests for API and ContextBuilder integration

## Endpoints

```text
POST   /knowledge-relations/upsert
PATCH  /knowledge-relations/{relation_id}
DELETE /knowledge-relations/{relation_id}
GET    /agents/{agent_id}/knowledge-relations
GET    /agents/{agent_id}/knowledge-relations/context
```

## Context integration

Knowledge relations can be included in:

- `/debug/context`
- `/chat`
- `ContextBuilder`
- token budget trimming

They are disabled by default at the ContextBuilder level because graph edges can be noisy without careful filtering.
Use `include_knowledge_relations=true` when you explicitly want them in the prompt.

## Design choices

- `source_type`, `target_type`, and `relation_type` are strings, not enums.
- `source_id` and `target_id` are strings so they can reference integer IDs, lorebook keys, goal keys, plan step keys, or custom project IDs.
- No foreign keys in MVP. This keeps the graph flexible and avoids migrations every time a new knowledge node type is added.
- `agent_id` controls whose knowledge graph edge this is. For global/world relations, use an agent-like owner such as `world_state` or `narrator_001`.

## Still TODO / V2 ideas

- Add optional validation that referenced source/target nodes actually exist.
- Add graph expansion retrieval: when a memory/goal/lorebook item is selected, optionally pull linked nodes.
- Add multi-hop traversal with token-budget controls.
- Add relation-aware reranking.
- Add automatic relation creation from dedup, summarization, goal updates, and procedural skill use.
- Add UI/debug graph view.
- Consider a clearer `scope` field later if `agent_id=world_state` is not expressive enough.
