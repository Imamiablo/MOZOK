"""Ensure the `/brain-packs/import-by-name` router is included in mozok/api/main.py.

Run from the MOZOK project root:

    .\.venv\Scripts\python.exe scripts\apply_brain_pack_import_by_name_route_patch.py
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "mozok" / "api" / "main.py"
MARKER = "MOZOK_BRAIN_PACK_IMPORT_BY_NAME_ROUTE"
HOOK = f'''

# --- {MARKER} START ---
# Local safe-name brain-pack import endpoint.
from mozok.api.brain_pack_import_by_name_route import router as _mozok_brain_pack_import_by_name_router

app.include_router(_mozok_brain_pack_import_by_name_router)
# --- {MARKER} END ---
'''


def main() -> int:
    if not MAIN_PATH.exists():
        print(f"ERROR: Cannot find {MAIN_PATH}", file=sys.stderr)
        return 1

    text = MAIN_PATH.read_text(encoding="utf-8")
    if MARKER in text or "brain_pack_import_by_name_route" in text:
        print("/brain-packs/import-by-name router hook is already installed.")
        return 0

    if "app = FastAPI" not in text and "FastAPI(" not in text:
        print("ERROR: mozok/api/main.py does not look like the FastAPI app file.", file=sys.stderr)
        return 1

    MAIN_PATH.write_text(text.rstrip() + HOOK + "\n", encoding="utf-8")
    print(f"Installed /brain-packs/import-by-name router in {MAIN_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
