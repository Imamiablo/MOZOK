# Patch 19 — Brain Pack / Scenario Import v1

## Goal

Add a first scenario/brain-pack importer so Mozok can be filled from one package instead of manually clicking every module in Swagger UI.

The importer is intentionally sparse-friendly: every section is optional. A pack can contain only lorebook entries, only goals, only skills, etc.

## Supports

- JSON brain packs
- YAML brain packs if PyYAML is installed
- simple markdown/txt lorebook files using:
  - `## CATEGORY`
  - `### Entry Title`
  - text body
- dry-run preview
- upsert mode
- inline API import for future UI usage

## Sections

- `agents`
- `lorebook_entries`
- `agent_lorebook_knowledge`
- `entity_states`
- `goals`
- `procedural_skills`
- `knowledge_relations`
- `memories` are counted but not imported in v1, because memory import needs embedding/index services.

## CLI

```powershell
.\.venv\Scripts\python.exe scripts\import_brain_pack.py data\brain_packs\old_well_brain_pack.json --dry-run
.\.venv\Scripts\python.exe scripts\import_brain_pack.py data\brain_packs\old_well_brain_pack.json --validate-relations
```

Direct text lorebook import:

```powershell
.\.venv\Scripts\python.exe scripts\import_brain_pack.py data\brain_packs\example_world_lore.txt --world-id example_world --dry-run
```

## API

```text
POST /brain-packs/import
```

Body:

```json
{
  "dry_run": true,
  "validate_relations": false,
  "pack": {
    "world_id": "old_well_world",
    "lorebook_entries": []
  }
}
```

## Still TODO

- Memory import with embedding/index services.
- Better schema validation messages.
- File/folder pack conventions for a future scenario builder UI.
- Optional import transactions/all-or-nothing mode.
