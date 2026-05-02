# Mozok memory maintenance

Mozok now uses four broad memory levels:

| Level | Meaning | Typical lifetime |
|---|---|---|
| `raw` | fresh dialogue, raw observations, noisy notes | short |
| `episodic` | meaningful events and experiences | medium / long |
| `semantic` | facts, preferences, knowledge, summaries | long |
| `core` | identity/profile/personality/critical relationship memory | protected |

Older names are still accepted and normalized:

- `dialogue`, `dialogue_raw`, `message`, `chat` -> `raw`
- `event`, `episode` -> `episodic`
- `fact`, `preference`, `knowledge`, `summary` -> `semantic`
- `profile`, `core/profile`, `identity` -> `core`

## Forget actions

Mozok does not treat forgetting as only deletion.

Supported actions:

| Action | Meaning |
|---|---|
| `decay` | lower `importance` |
| `archive` | set `active=false`, keep SQL record |
| `summarize` | create a semantic summary, keep original active |
| `summarize_then_archive` | create summary, then archive source memory |
| `soft_delete` | deactivate memory |
| `hard_delete` | physically delete SQL record |
| `protect` | mark memory as protected from automatic maintenance |

Automatic maintenance does **not** hard-delete by default.

## Maintenance triggers

Each agent has a memory policy stored in:

```text
agent.metadata_json["memory_policy"]
```

The policy controls five trigger situations:

1. `every_n_memories` - run maintenance after every N new memories.
2. `after_session` - run maintenance when the adapter says the session ended.
3. `memory_limit` - run maintenance when active memories exceed a configured limit.
4. `time_interval` - run maintenance every N hours.
5. `important_event` - protect / consolidate after a very important or emotional memory.

## API examples

Get an agent's policy:

```http
GET /agents/cat_001/memory-policy
```

Update trigger settings:

```http
PATCH /agents/cat_001/memory-policy
Content-Type: application/json

{
  "memory_policy": {
    "triggers": {
      "every_n_memories": {"enabled": true, "n": 50},
      "after_session": {"enabled": true},
      "memory_limit": {"enabled": true, "max_active_memories": 1500},
      "time_interval": {"enabled": true, "hours": 12},
      "important_event": {"enabled": true, "min_importance": 8, "min_abs_emotional_weight": 0.75}
    }
  }
}
```

Run maintenance manually:

```http
POST /agents/cat_001/memory-maintenance
Content-Type: application/json

{
  "trigger": "manual",
  "rebuild_index": true
}
```

Mark a session as ended:

```http
POST /agents/cat_001/sessions/end
```

Apply an explicit forget action:

```http
POST /memories/123/forget
Content-Type: application/json

{
  "action": "summarize_then_archive",
  "reason": "manual_cleanup",
  "rebuild_index": true
}
```

## Important design note

The maintenance summary is currently deterministic and offline-friendly: it creates a semantic summary by listing compressed source notes. Later this can be upgraded to call the configured LLM for a cleaner human-like summary.

## Short-term working memory

Short-term memory is separate from long-term raw memory.

- Short-term memory lives in Python RAM only.
- It keeps the most recent messages for the current `agent_id` + `session_id`.
- It is included in the prompt as recent conversation context.
- It is cleared when the session ends.
- It is not embedded, not stored in PostgreSQL, and not indexed in FAISS.

Long-term raw memory still goes to PostgreSQL as `memory_type="raw"` so that maintenance can later summarize/archive it.

Example chat request:

```json
{
  "agent_id": "cat_001",
  "session_id": "game_session_001",
  "message": "Do you remember what I just said?",
  "short_term_limit": 20
}
```

End a session and clear short-term memory:

```text
POST /agents/cat_001/sessions/end?session_id=game_session_001
```

MVP limitation: this is in-process RAM. If the API restarts, short-term memory disappears. If Mozok later runs with multiple workers or multiple servers, replace `SHORT_TERM_MEMORY` with Redis or another shared cache.
