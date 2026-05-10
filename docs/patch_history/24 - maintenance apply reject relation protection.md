# 25 - Maintenance Apply/Reject with Relation Protection

## Purpose

This patch adds a controlled maintenance workflow for applying or rejecting selected maintenance suggestions.

The goal is to make future UI flows safer:

1. generate maintenance suggestions;
2. review them;
3. apply selected or all suggestions;
4. reject selected or all suggestions;
5. protect memories that are linked by active knowledge relations.

## Added

### New service

- `mozok/memory/maintenance_apply.py`

The service adds:

- apply selected suggestions;
- apply all suggestions provided in the request;
- reject selected suggestions;
- reject all suggestions provided in the request;
- relation-aware protection for destructive actions.

Destructive actions are blocked by default when a target memory is linked by active knowledge relations.
The memory is protected instead of being archived, decayed, soft-deleted, hard-deleted, or summarised-and-archived.

### New API endpoints

- `POST /agents/{agent_id}/memory-maintenance/apply`
- `POST /agents/{agent_id}/memory-maintenance/reject`

The endpoints are suggestion-driven. A preview endpoint or UI can pass suggestion objects into these endpoints.

### New schemas

Added to `mozok/schemas/memory.py`:

- `MemoryMaintenanceSuggestionInput`
- `MemoryMaintenanceApplyRejectRequest`
- `MemoryMaintenanceApplyRejectResult`
- `MemoryMaintenanceApplyRejectResponse`

### Tests

- `tests/unit/test_memory_maintenance_apply.py`

The tests cover:

- relation-aware protection blocks destructive apply;
- apply all can archive unrelated memories;
- reject selected records the rejection without applying the original action.

## Behaviour

### Apply selected

```json
{
  "selection": "selected",
  "selected_suggestion_ids": ["archive:memory:42"],
  "suggestions": [
    {
      "suggestion_id": "archive:memory:42",
      "action": "archive",
      "target_memory_ids": [42],
      "reason": "Low retention score."
    }
  ]
}
```

### Apply all

```json
{
  "selection": "all",
  "suggestions": [
    {
      "suggestion_id": "archive:memory:42",
      "action": "archive",
      "target_memory_ids": [42],
      "reason": "Low retention score."
    }
  ]
}
```

### Reject selected/all

Rejecting suggestions does not apply the proposed action. It records a small rejection note in each target memory's metadata.

## Relation-aware protection

The following destructive actions are protected:

- `archive`
- `decay`
- `soft_delete`
- `hard_delete`
- `summarize_then_archive`

If a target memory has active knowledge relations, these actions are blocked unless `override_relation_protection` is set to `true`.

Archive-friendly relation types such as `duplicate_of`, `summarised_by`, `summarized_by`, `superseded_by`, and `obsolete_after` do not block maintenance.

## Notes

This patch does not add a stored suggestion table. Suggestions are passed in by the client, which keeps the implementation simple and works with the existing preview-style roadmap.

FAISS is rebuilt once at the end when an applied action requires index clean-up.
