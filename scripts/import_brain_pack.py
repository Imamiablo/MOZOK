from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mozok.db.session import SessionLocal
from mozok.scenario_import.service import BrainPackImportService, build_arg_parser, load_brain_pack_file

# Register optional module tables with Base.metadata before any init/import workflows.
from mozok.lorebook.models import AgentLorebookKnowledgeRecord, LorebookEntryRecord  # noqa: F401
from mozok.entity_state.models import AgentEntityStateRecord  # noqa: F401
from mozok.goals.models import AgentGoalRecord  # noqa: F401
from mozok.knowledge_relations.models import KnowledgeRelationRecord  # noqa: F401
from mozok.procedural_skills.models import AgentProceduralSkillRecord  # noqa: F401


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    path = Path(args.path)

    try:
        pack = load_brain_pack_file(path, world_id=args.world_id)
        with SessionLocal() as db:
            report = BrainPackImportService(db).import_pack(
                pack,
                dry_run=args.dry_run,
                base_dir=path.parent,
                validate_relations=args.validate_relations,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"Brain pack import failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        mode = "DRY RUN" if report.dry_run else "IMPORT"
        print(f"=== Mozok Brain Pack {mode} ===")
        print(f"world_id: {report.world_id}")
        print("counts:")
        for key, value in report.counts.items():
            print(f"  {key}: {value}")
        if report.warnings:
            print("warnings:")
            for warning in report.warnings:
                print(f"  - {warning}")
        if report.errors:
            print("errors:")
            for error in report.errors:
                print(f"  - {error}")
        print("actions:")
        for action in report.actions[:200]:
            msg = f" — {action.message}" if action.message else ""
            print(f"  - [{action.section}] {action.action}: {action.key}{msg}")
        if len(report.actions) > 200:
            print(f"  ... {len(report.actions) - 200} more actions")

    return 0 if not report.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
