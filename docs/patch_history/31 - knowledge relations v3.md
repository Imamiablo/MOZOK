# 31 - Knowledge Relations V3

## Summary

This patch upgrades knowledge relations from simple edge storage and one-hop context expansion into a small graph-intelligence layer.

The implementation is deliberately conservative: traversal and debug tooling are read-only, graph fan-out is capped by depth, relation count, per-node limits, and optional token budget, and automatic relation creation is limited to safe summarisation provenance edges.

## Changed files

- `mozok/knowledge_relations/service.py`
- `mozok/api/knowledge_relation_routes.py`
- `mozok/schemas/knowledge_relations.py`
- `mozok/context/context_builder.py`
- `mozok/schemas/context.py`
- `mozok/schemas/chat.py`
- `mozok/core/bot_core.py`
- `mozok/api/main.py`
- `mozok/memory/service.py`
- `tests/test_knowledge_relations_api.py`
- `tests/unit/test_memory_maintenance_apply.py`
- `ROADMAP.md`
- `docs/patch_history/30.1 - dedup v2 audit.md`

## Behaviour

### Multi-hop traversal

Added read-only graph traversal through:

- `POST /agents/{agent_id}/knowledge-relations/graph/debug`

The endpoint accepts root nodes, direction, maximum depth, maximum relation count, per-node limits, optional relation type filters, strength/confidence thresholds, and optional estimated token budget.

It returns:

- traversed nodes;
- traversed relations;
- compact relation prompt lines;
- paths;
- detected cycles;
- relation-aware reranking hints;
- a traversal report.

### Cycle detection

Traversal tracks the current path and reports cycles instead of following them forever.

This prevents loops such as:

```text
old_well -> tunnels -> map_room -> old_well
```

from blowing up context assembly or debug views.

### Budget-aware traversal

The graph debug endpoint and context expansion can stop relation fan-out using an approximate token budget.

ContextBuilder now supports:

- `knowledge_relation_traversal_depth`
- `knowledge_relation_traversal_token_budget`

Depth `1` keeps legacy one-hop behaviour. Depth `2+` enables V3 multi-hop traversal.

### Relation-aware reranking

Memory reranking already used direct graph links. It now also adds a small second-hop graph signal, so memories connected through nearby goals/lore/entity-state graph nodes can receive a transparent reranking boost.

This remains request-time metadata only. It does not mutate memories, SQL records, FAISS, or graph edges.

### Reviewed relation auto-create endpoint

Added:

- `POST /agents/{agent_id}/knowledge-relations/auto-create`

This endpoint is intended for reviewed suggestions from maintenance, summarisation, or dedup tooling. It supports `dry_run=true` so callers can preview/validate before writing.

It is explicit, not hidden automation.

### Automatic summarisation provenance edges

When maintenance/summarisation creates a semantic summary memory, Mozok now creates conservative graph provenance relations:

- source memory `summarised_by` summary memory;
- summary memory `derived_from` source memory.

These edges make future maintenance and graph debug safer because the system can explain where a summary came from.

## Tests

Added coverage for:

- multi-hop graph traversal;
- cycle reporting;
- token-budget traversal skips;
- reviewed relation auto-create dry-run and write mode;
- summarisation-created provenance relations;
- existing API/context/reranking behaviour remaining stable.

Full test result in the review environment:

```text
140 passed, 3 skipped, 7 warnings
```

The 3 skipped tests are HTTP smoke tests that require a live local Mozok API.

## Swagger UI checks

Useful manual checks:

1. Create a small relation chain with `/knowledge-relations/upsert`.
2. Call `/agents/{agent_id}/knowledge-relations/graph/debug` with `max_depth=3`.
3. Confirm `relation_count`, `paths`, `cycles`, and `traversal_report` look sensible.
4. Try `estimated_token_budget=1` and confirm the endpoint reports `skipped_for_budget` without modifying data.
5. Try `/agents/{agent_id}/knowledge-relations/auto-create` first with `dry_run=true`, then with `dry_run=false`.

## Notes

- No schema migration is required; the existing generic `knowledge_relations` table is reused.
- Direct FAISS graph mutation remains deferred.
- Advanced automatic relation creation from dedup clusters remains deferred unless routed through explicit reviewed suggestions.
