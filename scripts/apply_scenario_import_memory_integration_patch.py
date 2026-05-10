"""Apply the ScenarioImportService memory integration hook.

Run from the MOZOK project root:

    .\.venv\Scripts\python.exe scripts\apply_scenario_import_memory_integration_patch.py

The patch appends a tiny hook to mozok/scenario_import/service.py. It does not
rewrite the service implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = PROJECT_ROOT / "mozok" / "scenario_import" / "service.py"
MARKER = "MOZOK_SCENARIO_MEMORY_IMPORT_INTEGRATION"
HOOK = f'''

# --- {MARKER} START ---
# Adds memory import support to the main brain-pack scenario importer.
# The real logic lives in a small wrapper module so this service stays readable.
try:
    from mozok.scenario_import.service_memory_integration import (
        install_memory_import_integration as _mozok_install_memory_import_integration,
    )

    _mozok_install_memory_import_integration(ScenarioImportService)
except NameError:
    # ScenarioImportService was not defined; keep import-time failure readable.
    raise
# --- {MARKER} END ---
'''


def main() -> int:
    if not SERVICE_PATH.exists():
        print(f"ERROR: Cannot find {SERVICE_PATH}", file=sys.stderr)
        return 1

    text = SERVICE_PATH.read_text(encoding="utf-8")
    if MARKER in text:
        print("ScenarioImportService memory integration is already installed.")
        return 0

    if "class ScenarioImportService" not in text:
        print("ERROR: service.py does not appear to define ScenarioImportService.", file=sys.stderr)
        return 1

    SERVICE_PATH.write_text(text.rstrip() + HOOK + "\n", encoding="utf-8")
    print(f"Installed ScenarioImportService memory integration hook in {SERVICE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
