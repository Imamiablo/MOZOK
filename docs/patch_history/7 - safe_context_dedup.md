# Patch 7 - Safe context deduplication

This patch adds retrieval-time/context-only deduplication.

It does **not** delete, archive, merge, or modify memories in PostgreSQL/FAISS.
It only removes near-duplicate memories from the LLM prompt for the current chat turn.

## Added

- `mozok/context/dedup.py`
  - `ContextMemoryDeduplicator`
  - `DedupResult`

## Changed

- `mozok/context/context_builder.py`
  - runs core/semantic/episodic/raw memories through the deduplicator before creating the context package.
  - adds `dedup_removed_memories_count` and `dedup_removed_memory_ids` to `ContextPackage`.

- `mozok/schemas/chat.py`
  - adds `dedup_removed_memories_count` to `ChatResponse`.

- `mozok/core/bot_core.py`
  - returns `dedup_removed_memories_count` from chat responses.

## Dedup priority

If two memories look nearly identical in the current retrieved context, the stronger one wins:

`core > semantic > episodic > raw`

For the same level, the tie-breakers are:

1. higher `importance`
2. higher retrieval `score`
3. larger/newer `id`

## How to test

Create two very similar semantic memories for the same agent:

```json
{
  "agent_id": "dedup_test_001",
  "content": "Denys prefers practical beginner-friendly programming explanations.",
  "memory_type": "semantic",
  "importance": 7,
  "metadata": {}
}
```

```json
{
  "agent_id": "dedup_test_001",
  "content": "Denys likes practical and beginner friendly programming explanations.",
  "memory_type": "semantic",
  "importance": 5,
  "metadata": {}
}
```

Then call `/chat` with:

```json
{
  "agent_id": "dedup_test_001",
  "session_id": "dedup_test_001",
  "message": "How should you explain programming to me?",
  "short_term_limit": 20
}
```

Expected result: `dedup_removed_memories_count` should be at least `1` if both memories were retrieved for that prompt.
