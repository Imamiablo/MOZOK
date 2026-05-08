# Patch 17 — Knowledge Relations V2

## Goal

Make Knowledge Relations useful for debugging and context assembly, not just manual storage.

V1 added generic relation edges:

```text
source_type:source_id --relation_type--> target_type:target_id
```

V2 adds lightweight graph helper behavior while deliberately avoiding heavy multi-hop graph traversal.

## Added

- Optional node validation on upsert via `validate_nodes`.
- Node resolution helpers for known node types:
  - `goal`
  - `lorebook`
  - `entity_state`
  - `memory`
  - `agent`
- `GET /knowledge-relations/{relation_id}/resolved`
- `GET /agents/{agent_id}/knowledge-relations/neighborhood`
- One-hop context expansion:
  - `include_related_knowledge_relations`
  - `related_knowledge_relation_limit`
- Debug visibility for:
  - explicit relation IDs
  - auto-expanded relation IDs
  - `related_relations_expanded` pipeline step

## Design limits

V2 intentionally does not implement:

- multi-hop traversal;
- automatic LLM-generated relations;
- hard foreign keys between relation nodes and every possible table;
- graph scoring/reranking;
- graph UI.

Those belong to later patches.

## Why `validate_nodes` defaults to false

Knowledge relations should remain flexible. During scenario design a project may want to relate a current goal to a future concept, quest, or custom node type that is not yet represented by a database record.

When `validate_nodes=true`, Mozok checks known node types and rejects missing goals/lorebook entries/entity states/memories. Unknown/custom node types are treated as flexible graph nodes.

## Context expansion

When enabled, ContextBuilder collects node references from already-selected context:

- memory IDs;
- goal IDs and goal keys;
- lorebook IDs and entry keys;
- entity-state IDs and entity IDs.

Then it adds direct one-hop relations touching those nodes.

This allows a selected goal like:

```text
goal:hide_tunnel_secret
```

to automatically bring in a link like:

```text
goal:"hide_tunnel_secret" depends_on lorebook:"old_well"
```

without manually adding every relation filter to `/debug/context` or `/chat`.
