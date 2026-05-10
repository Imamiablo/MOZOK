# MOZOK patch: integrate brain-pack memories into the main scenario importer

This patch connects the previously added `BrainPackMemoryImporter` to the main
`ScenarioImportService`, so brain-pack `memories` are no longer only counted or
handled by the standalone CLI.

The important behaviour:

- `ScenarioImportService.import_pack(...)` continues to do the normal import.
- After the normal import succeeds, the wrapper imports `pack["memories"]`.
- Memory rows go through `MemoryService`, so existing SQL + embeddings + FAISS
  sync stays the single source of truth.
- `dry_run=True` previews memory import without writing.
- Exact duplicates are still skipped unless `allow_duplicates=True` is passed.

## Files included

- `mozok/scenario_import/memory_importer.py`
- `mozok/scenario_import/service_memory_integration.py`
- `scripts/apply_scenario_import_memory_integration_patch.py`
- `tests/unit/test_scenario_import_memory_integration.py`

## Apply

Copy/unzip these files into the project root, then run:

```powershell
.\.venv\Scripts\python.exe scripts\apply_scenario_import_memory_integration_patch.py
```

The script appends a small hook to:

```text
mozok/scenario_import/service.py
```

It is idempotent: running it twice should not duplicate the hook.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_scenario_import_memory_integration.py
.\.venv\Scripts\python.exe -m pytest tests\unit\test_brain_pack_memory_importer.py
.\.venv\Scripts\python.exe -m pytest
```

## Minimal brain-pack memory example

```json
{
  "defaults": {
    "agent_id": "npc_alice"
  },
  "memories": [
    {
      "content": "Alice knows that the old well connects to the tunnels.",
      "memory_type": "semantic",
      "importance": 0.8,
      "emotional_weight": 0.1,
      "metadata": {
        "lorebook_key": "old_well"
      }
    }
  ]
}
```

## Notes

This is still an MVP integration. It intentionally does not implement semantic
or embedding-based deduplication; that remains Dedup V2.
