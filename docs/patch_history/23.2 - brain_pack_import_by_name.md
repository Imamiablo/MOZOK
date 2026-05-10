# MOZOK patch: `/brain-packs/import-by-name`

This patch adds a safer and more convenient Swagger/API endpoint for importing
local brain-pack files from `data/brain_packs/` by name.

It keeps the existing endpoint unchanged:

```text
POST /brain-packs/import
```

That endpoint still expects the full brain-pack JSON object in the request body.

This patch adds:

```text
POST /brain-packs/import-by-name
```

Example Swagger body:

```json
{
  "pack_name": "cyberpunk_demo_memory_pack",
  "dry_run": true,
  "validate_relations": false,
  "atomic": true
}
```

The backend searches only inside:

```text
data/brain_packs/
```

It tries:

```text
data/brain_packs/<pack_name>.json
data/brain_packs/<pack_name>.yaml
data/brain_packs/<pack_name>.yml
```

If the extension is included, it uses that extension only.

## Safety rules

The endpoint does **not** accept arbitrary filesystem paths.

Rejected examples:

```text
../evil
nested/folder/pack
C:/Users/me/secrets.json
pack\name
pack:evil
```

Accepted examples:

```text
cyberpunk_demo_memory_pack
cyberpunk_demo_memory_pack.json
```

## Files included

```text
mozok/scenario_import/brain_pack_file_loader.py
mozok/schemas/brain_pack_import_by_name.py
scripts/apply_brain_pack_import_by_name_patch.py
tests/unit/test_brain_pack_file_loader.py
tests/unit/test_brain_pack_import_by_name_openapi.py
data/brain_packs/cyberpunk_demo_memory_pack.json
```

## Apply

Unzip the patch into your MOZOK project root, then run:

```powershell
.\.venv\Scripts\python.exe scripts\apply_brain_pack_import_by_name_patch.py
```

The script appends a small route hook to:

```text
mozok/api/main.py
```

It is idempotent; running it twice should not duplicate the endpoint.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_brain_pack_file_loader.py
.\.venv\Scripts\python.exe -m pytest tests\unit\test_brain_pack_import_by_name_openapi.py
.\.venv\Scripts\python.exe -m pytest
```

## Swagger smoke test

Restart the API server after applying the patch.

Open Swagger and use:

```text
POST /brain-packs/import-by-name
```

Body:

```json
{
  "pack_name": "cyberpunk_demo_memory_pack",
  "dry_run": true,
  "validate_relations": false,
  "atomic": true
}
```

Then run the same request with:

```json
"dry_run": false
```

The response should include your normal scenario import report plus fields like:

```json
{
  "brain_pack_file": "data/brain_packs/cyberpunk_demo_memory_pack.json",
  "pack_name": "cyberpunk_demo_memory_pack"
}
```

If the previous memory-import integration patch is installed, the response should
also include `memory_import`.
