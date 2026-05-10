# 25 - Maintenance Suggestions with Relation Protection

## Purpose

This patch adds a read-only maintenance suggestion layer for Mozok.

The goal is to let Mozok show what it would do before anything is applied:

- which memories look safe to archive;
- which memories should decay gently;
- which raw memories look suitable to summarise together;
- which memories should be protected because they are important or connected by knowledge relations;
- optional LLM-written explanations for suggestions.

This patch does **not** apply the suggestions. It does not mutate SQL records, FAISS, access counters, summaries, metadata, or relations.

## Added

### New service

`mozok/memory/maintenance_suggestions.py`

Adds `MemoryMaintenanceSuggestionService`, a read-only preview engine.

It can use:

- deterministic maintenance rules;
- relation-aware protection;
- optional embedding clustering for similar raw memories;
- optional LLM explanation text.

The LLM is not allowed to choose the action. Rule/cluster logic creates the action first, and the LLM can only rewrite the explanation.

### New endpoint

`POST /agents/{agent_id}/memory-maintenance/suggestions`

Returns suggestions in a format that can later be passed to apply/reject endpoints.

### New schemas

Added to `mozok/schemas/memory.py`:

- `MemoryMaintenanceSuggestionsRequest`
- `MemoryMaintenanceSuggestion`
- `MemoryMaintenanceSuggestionsResponse`

### Tests

`tests/unit/test_memory_maintenance_suggestions.py`

Covers:

- relation-linked memories receive protect suggestions;
- read-only preview does not mutate the memory record;
- embedding clustering suggests `summarize_then_archive` for similar raw memories;
- LLM explanation rewrites the reason without changing the selected action.

## Safety notes

Relation-aware protection treats active knowledge relations as a reason to avoid destructive automatic maintenance.

Destructive actions include:

- `archive`
- `decay`
- `soft_delete`
- `hard_delete`
- `summarize_then_archive`

Some relation types are archive-friendly because they usually mean the source memory is already obsolete or represented elsewhere:

- `duplicate_of`
- `near_duplicate_of`
- `summarised_by`
- `summarized_by`
- `superseded_by`
- `obsolete_after`

## Suggested test command

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_memory_maintenance_suggestions.py
.\.venv\Scripts\python.exe -m pytest
```

## Roadmap status

This patch completes a safe MVP for:

- relation-aware maintenance preview;
- embedding clustering as suggest-only consolidation;
- LLM-assisted maintenance explanations without LLM-owned decisions.

It deliberately does not add automatic apply-all behaviour, direct FAISS mutation, or semantic duplicate merging.
