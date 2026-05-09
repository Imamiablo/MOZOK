# Patch 20 — Brain Pack Import V2: validation + atomic import

## Goal

Make scenario/brain-pack import safer before larger packs are used.

## Added

- Preflight validation before import:
  - duplicate keys in pack sections;
  - basic payload shape validation via existing Pydantic schemas;
  - optional relation node validation against nodes in the pack and database.
- Atomic import mode:
  - default for real imports;
  - internal service commits are converted to flushes during the import;
  - if an import records errors, the whole pack is rolled back.
- API/CLI support for `atomic`.
- Tests for duplicate detection, relation preflight, abort-before-write, and API atomic flag.

## CLI

```powershell
.\.venv\Scripts\python.exe scripts\import_brain_pack.py data\brain_packs\old_well_brain_pack.json --dry-run --validate-relations
.\.venv\Scripts\python.exe scripts\import_brain_pack.py data\brain_packs\old_well_brain_pack.json --validate-relations
```

Use `--no-atomic` only when intentionally allowing partial imports.

## Notes

Memory import is still intentionally not implemented here because memories need the embedding/index pipeline.
