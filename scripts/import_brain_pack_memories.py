r"""Import only the `memories` section from a MOZOK brain pack.

Usage from project root:

    .\.venv\Scripts\python.exe scripts\import_brain_pack_memories.py data\brain_packs\old_well.json --dry-run
    .\.venv\Scripts\python.exe scripts\import_brain_pack_memories.py data\brain_packs\old_well.json

This script is intentionally separate from the main scenario importer so the
memory/FAISS part can be tested safely before being folded into API import.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# When this file is executed directly as:
#   python scripts/import_brain_pack_memories.py ...
# Python puts the scripts/ folder on sys.path, not the project root.
# Add the project root explicitly so `import mozok...` works from PowerShell.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mozok.db.session import SessionLocal
from mozok.core.bot_core import get_memory_service
from mozok.scenario_import.memory_importer import BrainPackMemoryImporter


def load_pack(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError("PyYAML is required for YAML brain packs. Install pyyaml or use JSON.") from exc
        loaded = yaml.safe_load(text)
    else:
        loaded = json.loads(text)

    if not isinstance(loaded, dict):
        raise ValueError("Brain pack must contain a JSON/YAML object at the top level.")
    return loaded


def main() -> int:
    parser = argparse.ArgumentParser(description="Import brain-pack memories through MemoryService.")
    parser.add_argument("path", type=Path, help="Path to brain-pack JSON/YAML file")
    parser.add_argument("--agent-id", default=None, help="Fallback agent_id for memory rows without agent_id")
    parser.add_argument("--dry-run", action="store_true", help="Preview import without writing SQL/FAISS")
    parser.add_argument("--allow-duplicates", action="store_true", help="Do not skip exact duplicates")
    args = parser.parse_args()

    pack = load_pack(args.path)

    db = SessionLocal()
    try:
        importer = BrainPackMemoryImporter(db=db, memory_service=get_memory_service(db))
        result = importer.import_pack_memories(
            pack,
            default_agent_id=args.agent_id,
            dry_run=args.dry_run,
            allow_duplicates=args.allow_duplicates,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        if result.errors:
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
