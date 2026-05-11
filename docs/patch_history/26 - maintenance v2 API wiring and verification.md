# 26 - Maintenance V2 API Wiring and Verification

## Purpose

This patch does not re-implement LLM explanation or embedding clustering, because the current code already contains them inside the read-only maintenance suggestion engine.

Instead, this patch makes the Maintenance V2 workflow coherent by wiring the apply/reject endpoints into the main FastAPI app and adding tests that verify the API and the existing V2 suggestion features.

## Current status after this patch

### Already implemented

- Read-only maintenance suggestions.
- Relation-aware protection in the preview layer.
- Optional embedding clustering for similar raw memories.
- Optional LLM-written explanation text.
- Apply selected suggestions.
- Apply all suggestions.
- Reject selected suggestions.
- Reject all suggestions.
- Relation-aware protection in the apply layer.

### Added by this patch

- `POST /agents/{agent_id}/memory-maintenance/apply`
- `POST /agents/{agent_id}/memory-maintenance/reject`
- OpenAPI tests for the maintenance suggestions/apply/reject routes.
- Tests proving that the suggestions request exposes LLM explanation and embedding clustering options.
- Tests for embedding cluster suggestions, LLM explanation rewriting, and relation protection on cluster suggestions.

## Behaviour

The recommended safe workflow is:

1. call `/agents/{agent_id}/memory-maintenance/suggestions`;
2. review the returned suggestions;
3. pass selected or all suggestions to `/agents/{agent_id}/memory-maintenance/apply`;
4. optionally pass rejected suggestions to `/agents/{agent_id}/memory-maintenance/reject`.

The LLM explanation layer is deliberately not the decision-maker. It may rewrite the reason, but rule-based and clustering logic still choose the action.

Embedding clustering is also suggest-only. It proposes `summarize_then_archive` candidates for groups of similar raw memories, but it does not create summaries, archive records, or mutate FAISS by itself.

## Files

- `mozok/api/main.py`
- `tests/unit/test_maintenance_v2_api_routes.py`
- `tests/unit/test_maintenance_v2_suggestion_features.py`
- `mozok/docs/patch_history/26 - maintenance v2 API wiring and verification.md`

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_maintenance_v2_api_routes.py
.\.venv\Scripts\python.exe -m pytest tests\unit\test_maintenance_v2_suggestion_features.py
.\.venv\Scripts\python.exe -m pytest
```
