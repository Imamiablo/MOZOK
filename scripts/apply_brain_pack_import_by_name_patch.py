"""Install the `/brain-packs/import-by-name` endpoint into mozok/api/main.py.

Run from the MOZOK project root after unzipping this patch:

    .\.venv\Scripts\python.exe scripts\apply_brain_pack_import_by_name_patch.py

The patch is idempotent. It appends a small endpoint that imports a brain pack by
safe local name from `data/brain_packs/`.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "mozok" / "api" / "main.py"
MARKER = "MOZOK_BRAIN_PACK_IMPORT_BY_NAME_ENDPOINT"

HOOK = f'''

# --- {MARKER} START ---
# Imports a local brain-pack file by safe name from data/brain_packs/.
# Keep /brain-packs/import for raw JSON-object imports; this endpoint is for dev/local packs.
from fastapi import Depends as _MozokDepends, HTTPException as _MozokHTTPException
from sqlalchemy.orm import Session as _MozokSession

from mozok.db.session import get_db as _mozok_get_db
from mozok.scenario_import.brain_pack_file_loader import (
    BrainPackLoadError as _MozokBrainPackLoadError,
    BrainPackNameError as _MozokBrainPackNameError,
    BrainPackNotFoundError as _MozokBrainPackNotFoundError,
    load_brain_pack_by_name as _mozok_load_brain_pack_by_name,
)
from mozok.scenario_import.service import ScenarioImportService as _MozokScenarioImportService
from mozok.schemas.brain_pack_import_by_name import BrainPackImportByNameRequest as _MozokBrainPackImportByNameRequest


@app.post("/brain-packs/import-by-name", tags=["brain-packs"])
def import_brain_pack_by_name(
    request: _MozokBrainPackImportByNameRequest,
    db: _MozokSession = _MozokDepends(_mozok_get_db),
):
    """Import a local brain pack from data/brain_packs by safe file name.

    Example body:

    ```json
    {{
      "pack_name": "cyberpunk_demo_brain_pack",
      "dry_run": true,
      "validate_relations": false,
      "atomic": true
    }}
    ```
    """

    try:
        pack, loaded_from = _mozok_load_brain_pack_by_name(request.pack_name)
    except _MozokBrainPackNameError as exc:
        raise _MozokHTTPException(status_code=400, detail=str(exc)) from exc
    except _MozokBrainPackNotFoundError as exc:
        raise _MozokHTTPException(status_code=404, detail=str(exc)) from exc
    except _MozokBrainPackLoadError as exc:
        raise _MozokHTTPException(status_code=422, detail=str(exc)) from exc

    service = _MozokScenarioImportService(db)
    result = service.import_pack(
        pack,
        dry_run=request.dry_run,
        validate_relations=request.validate_relations,
        atomic=request.atomic,
    )

    # Keep the original scenario import response, but make the selected file visible.
    if isinstance(result, dict):
        result.setdefault("brain_pack_file", str(loaded_from))
        result.setdefault("pack_name", request.pack_name)
        return result

    return {{
        "pack_name": request.pack_name,
        "brain_pack_file": str(loaded_from),
        "result": result,
    }}
# --- {MARKER} END ---
'''


def main() -> int:
    if not MAIN_PATH.exists():
        print(f"ERROR: Cannot find {{MAIN_PATH}}", file=sys.stderr)
        return 1

    text = MAIN_PATH.read_text(encoding="utf-8")
    if MARKER in text:
        print("/brain-packs/import-by-name endpoint is already installed.")
        return 0

    if "app =" not in text and "FastAPI(" not in text:
        print("ERROR: main.py does not appear to define a FastAPI app.", file=sys.stderr)
        return 1

    MAIN_PATH.write_text(text.rstrip() + HOOK + "\n", encoding="utf-8")
    print(f"Installed /brain-packs/import-by-name endpoint in {{MAIN_PATH}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
