# 26 - Reranking MVP

## Summary

Adds a transparent deterministic reranker for memory retrieval.

The reranker improves memory ordering before ContextBuilder places memories into
the prompt. It is not LLM-based and does not mutate SQL, FAISS, memories, goals,
lorebook entries, entity states, or knowledge relations.

## Implemented

- Added `mozok.memory.reranker`.
- Replaced the old lightweight inline ranking in `MemoryService.search` with a
  dedicated deterministic reranker.
- Added score parts for:
  - vector score;
  - importance;
  - emotional weight;
  - recency;
  - access count;
  - memory type weight;
  - active goal boost;
  - relation boost;
  - lore/entity boost;
  - relation strength;
  - relation confidence.
- Added relation-aware signals from `knowledge_relations` and active goals.
- Added `_reranking` explanation metadata to `MemorySearchResult`.
- Added `/debug/context` reranking reports through `ContextPackage`.
- Added tests for deterministic reranking and debug explanation output.

## Behaviour

The final score is intentionally explainable. Debug output can now show why a
memory was selected, instead of only showing that it was selected.

Example debug shape:

```json
{
  "memory_id": 42,
  "final_score": 1.37,
  "score_parts": {
    "vector_score": 0.72,
    "importance": 0.16,
    "active_goal_boost": 0.07,
    "relation_boost": 0.05
  },
  "reason": "Selected because of strong semantic match, high importance, linked to active goal context."
}
```

## Not included yet

- LLM reranking.
- Cross-encoder reranking.
- Learning weights from user feedback.
- Direct FAISS mutation.
- Stored ranking audit table.

## Notes

The code keeps British English in comments and documentation where possible, but
existing public API and method names are kept stable.
