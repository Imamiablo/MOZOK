# Mozok Lorebook Patch

This patch adds a Lorebook layer.

## Concept

Entity states are subjective and agent-specific:

```text
npc_bob -> social_relationship -> alice
assistant_001 -> assistant_user_profile -> denys
narrator_001 -> quest_relevance -> missing_child_quest
```

Lorebook entries are objective / author-defined world facts:

```text
world default -> old_well_secret -> "The old well connects to ancient tunnels."
```

Agent lorebook knowledge links decide whether a specific agent knows a lorebook entry:

```text
npc_bob knows old_well_secret as rumored
narrator_001 knows old_well_secret as known
npc_alice does not know old_well_secret
```

## Files to copy

```text
mozok/lorebook/__init__.py
mozok/lorebook/models.py
mozok/lorebook/schemas.py
mozok/lorebook/service.py
mozok/api/lorebook_routes.py
tests/test_lorebook_api.py
```

## Manual edits required

### 1. Register routes in `mozok/api/main.py`

Add import:

```python
from mozok.api.lorebook_routes import router as lorebook_router
```

Then after app creation:

```python
app.include_router(lorebook_router)
```

### 2. Register database models before `Base.metadata.create_all(...)`

Wherever your project imports models before table creation, add:

```python
from mozok.lorebook.models import AgentLorebookKnowledgeRecord, LorebookEntryRecord  # noqa: F401
```

Common places:
- `scripts/init_db.py`
- or wherever your launcher creates database tables.

Do NOT put this import inside SQLAlchemy site-packages.

### 3. Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Swagger smoke test

1. POST `/lorebook/upsert`

```json
{
  "world_id": "default",
  "entry_key": "old_well_secret",
  "title": "The Old Well",
  "content": "The old well connects to ancient tunnels.",
  "category": "location_secret",
  "visibility": "restricted",
  "importance": 9,
  "tags": ["well", "secret"],
  "metadata": {}
}
```

2. POST `/agents/npc_bob/lorebook/knowledge`

```json
{
  "agent_id": "npc_bob",
  "world_id": "default",
  "entry_key": "old_well_secret",
  "knowledge_state": "rumored",
  "confidence": 4,
  "notes": "Bob heard this from Alice but is not sure.",
  "metadata": {}
}
```

3. GET `/agents/npc_bob/lorebook/context?world_id=default`

Bob should see the lorebook entry as `rumored`.

4. GET `/agents/npc_alice/lorebook/context?world_id=default`

Alice should not see the restricted entry unless you link it to her too.
