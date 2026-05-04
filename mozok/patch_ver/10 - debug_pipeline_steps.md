# Patch 12 — Debug Pipeline Steps

This patch improves `/debug/context` by adding a `pipeline_steps` section.

The goal is to make the debug response easier to read for a future UI popup:

```text
retrieved -> deduped -> budget_trimmed -> final_prompt
```

## Files changed

- `mozok/context/context_builder.py`

## What changed

`ContextPackage` now keeps debug-only snapshots of earlier stages:

- context retrieved before deduplication;
- context after safe deduplication but before token-budget trimming;
- final context after token-budget trimming.

`/debug/context` now returns:

```json
"pipeline_steps": [
  {"step": "retrieved", ...},
  {"step": "deduped", ...},
  {"step": "budget_trimmed", ...},
  {"step": "final_prompt", ...}
]
```

This does not change the database, FAISS index, memory retrieval behaviour, or LLM prompt content.
It only improves debug visibility.

## Expected behaviour

When memories are retrieved, deduplicated, and then trimmed by token budget, the debug response shows each stage separately:

- `retrieved` shows what ContextBuilder initially found;
- `deduped` shows which near-duplicates were hidden and why;
- `budget_trimmed` shows which items were removed due to token budget;
- `final_prompt` shows what remained in the actual prompt.

## Why this matters

Before this patch, `/debug/context` showed `dedup_removed_details` and `context_budget` separately, but it was not obvious that the pipeline happens in order:

1. retrieve candidate memories;
2. hide duplicates from the prompt;
3. trim for token budget;
4. build final prompt.

This patch makes that lifecycle explicit.
