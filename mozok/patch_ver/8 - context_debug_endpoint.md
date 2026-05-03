# Patch 8 - Context Debug Endpoint

This patch adds infrastructure for inspecting the exact context Mozok would send to the LLM.

## New endpoint

```text
POST /debug/context
```

This endpoint:

- builds the same `ContextPackage` that `/chat` uses;
- does **not** call the LLM;
- does **not** write new memories;
- shows short-term memory, core memories, semantic memories, episodic memories, raw memories;
- shows the final prompt preview/full prompt;
- shows deduplication decisions: which memory IDs were hidden from the prompt and why.

## Example body

```json
{
  "agent_id": "cat_001",
  "session_id": "default",
  "message": "What do you remember about my cats?",
  "short_term_limit": 20,
  "core_limit": 10,
  "semantic_limit": 6,
  "episodic_limit": 4,
  "raw_limit": 0,
  "include_full_prompt": true,
  "prompt_preview_chars": 2000
}
```

## Why this exists

Later, a frontend can call this endpoint when the user clicks a message and show a popup/modal with the context used for that response.

For now, Swagger UI is enough to inspect the output.

## Safety

This patch does not implement database deduplication. Dedup remains retrieval-time/context-only.

The database and FAISS index are not modified by `/debug/context`.
