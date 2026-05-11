# 31 - Dedup V2 audit

## Summary

This patch adds a read-only Dedup V2 audit layer for long-term memories.

The goal is to move beyond simple prompt-time text deduplication without making unsafe automatic changes. Dedup V2 can now report likely duplicate, similar, superseding, or contradicting memory pairs and propose graph-style relation payloads for later review.

## Changed files

- `mozok/context/dedup.py`
- `mozok/memory/dedup_audit.py`
- `mozok/schemas/memory.py`
- `mozok/schemas/knowledge_relations.py`
- `mozok/api/main.py`
- `ROADMAP.md`
- `tests/unit/test_dedup_v2_audit.py`
- `tests/unit/test_dedup_v2_api_openapi.py`

## Behaviour

### Language-aware tokenisation

Prompt-time context dedup now uses a shared language-aware fingerprint helper:

- English stopwords
- Ukrainian stopwords
- Russian stopwords
- simple CJK n-grams
- normalised punctuation/spacing

This keeps retrieval-time prompt dedup conservative while making it less English-only.

### Read-only audit endpoint

Added:

```text
POST /agents/{agent_id}/memory-dedup/audit
```

The endpoint:

- scans active memories for one agent;
- optionally filters by memory levels;
- compares normalised text similarity;
- compares token overlap;
- optionally calculates embedding cosine similarity;
- reports candidate relation types:
  - `duplicate_of`
  - `similar_to`
  - `supersedes`
  - `contradicts`
- returns optional KnowledgeRelation-style suggestion payloads.

### Safety

The audit endpoint is deliberately dry-run only:

- no memory deletion;
- no hard-delete;
- no archive/soft-delete;
- no merge;
- no SQL mutation;
- no FAISS mutation;
- no automatic KnowledgeRelation creation.

The response marks candidates as `review_only`, `would_modify=false`, and `would_delete=false`.

## Tests

Added tests for:

- OpenAPI route/schema registration;
- language-aware tokenisation;
- duplicate detection;
- embedding-similar memory detection;
- contradiction detection;
- superseding detection;
- audit not mutating database memories.

Full test result in the patch environment:

```text
136 passed, 3 skipped, 7 warnings
```

## Swagger UI check

Optional but useful:

1. Create a few similar memories for the same `agent_id` using `POST /memories`.
2. Run `POST /agents/{agent_id}/memory-dedup/audit`.
3. Confirm the response includes candidates but does not modify or delete anything.
4. Check `relation_suggestion` payloads if future graph workflows need reviewed relation creation.

No automatic apply endpoint was added in this patch by design.
