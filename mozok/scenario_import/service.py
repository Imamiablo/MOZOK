from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from mozok.agent.service import AgentService
from mozok.db.models import AgentRecord
from mozok.entity_state.service import EntityStateService
from mozok.goals.service import GoalService
from mozok.knowledge_relations.service import KnowledgeRelationService
from mozok.lorebook.schemas import AgentLorebookKnowledgeUpsert, LorebookEntryUpsert
from mozok.lorebook.service import LorebookService
from mozok.procedural_skills.service import ProceduralSkillService
from mozok.schemas.entity_state import EntityStateUpsert
from mozok.schemas.goals import AgentGoalUpsert
from mozok.schemas.knowledge_relations import KnowledgeRelationUpsert
from mozok.schemas.procedural_skills import AgentProceduralSkillUpsert
from mozok.scenario_import.memory_importer import BrainPackMemoryImporter
from mozok.scenario_import.schemas import BrainPackImportAction, BrainPackImportReport


_SECTION_ALIASES = {
    "agents": "agents",
    "agent_profiles": "agents",
    "lorebook": "lorebook_entries",
    "lorebook_entries": "lorebook_entries",
    "lore": "lorebook_entries",
    "agent_lorebook_knowledge": "agent_lorebook_knowledge",
    "lorebook_knowledge": "agent_lorebook_knowledge",
    "entity_states": "entity_states",
    "states": "entity_states",
    "goals": "goals",
    "plans": "goals",
    "procedural_skills": "procedural_skills",
    "skills": "procedural_skills",
    "knowledge_relations": "knowledge_relations",
    "relations": "knowledge_relations",
    "memories": "memories",
}

_COUNT_SECTIONS = [
    "agents",
    "lorebook_entries",
    "agent_lorebook_knowledge",
    "entity_states",
    "goals",
    "procedural_skills",
    "knowledge_relations",
    "memories",
]

_PLURAL_CATEGORY_HINTS = {
    "animals": "animal",
    "plants": "plant",
    "places": "place",
    "artifacts": "artifact",
    "artefacts": "artifact",
    "magic": "magic",
    "cultures": "culture",
    "factions": "faction",
    "characters": "character",
    "locations": "location",
    "items": "item",
    "rules": "rule",
    "history": "history",
}


def slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text or "item"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _merge_defaults(item: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults or {})
    merged.update(dict(item or {}))
    return merged


def _load_yaml(text: str, path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional local package
        raise RuntimeError(
            f"YAML import requested for {path}, but PyYAML is not installed. "
            "Use JSON for now or install pyyaml."
        ) from exc

    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML brain pack must be an object/dict: {path}")
    return loaded


def parse_lorebook_markdown_text(
    text: str,
    *,
    world_id: str = "default",
    visibility: str = "narrator_only",
    importance: int = 5,
    default_category: str = "general",
    source_name: str = "",
) -> list[dict[str, Any]]:
    """Parse a simple markdown/txt lorebook format.

    Supported pattern:
    - ## CATEGORY
    - ### Entry title
    - Free text content until the next ## or ### heading.

    This matches the user's older example.txt style while keeping the new
    canonical import format JSON/YAML-first.
    """

    entries: list[dict[str, Any]] = []
    current_category = default_category
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if not current_title:
            return
        content = " ".join(line.strip() for line in current_lines if line.strip()).strip()
        if not content:
            current_title = None
            current_lines = []
            return
        category_key = slugify(current_category)
        category = _PLURAL_CATEGORY_HINTS.get(category_key, category_key or default_category)
        title = current_title.strip()
        entries.append(
            {
                "world_id": world_id,
                "entry_key": slugify(title),
                "title": title,
                "content": content,
                "category": category,
                "visibility": visibility,
                "importance": importance,
                "tags": [category_key] if category_key else [],
                "metadata": {"source_format": "markdown_lorebook", "source_file": source_name} if source_name else {"source_format": "markdown_lorebook"},
            }
        )
        current_title = None
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if current_title:
                current_lines.append("")
            continue
        if stripped.startswith("#") and not stripped.startswith("##"):
            continue
        if stripped.startswith("## ") and not stripped.startswith("### "):
            flush()
            current_category = stripped[3:].strip() or default_category
            continue
        if stripped.startswith("### "):
            flush()
            current_title = stripped[4:].strip()
            current_lines = []
            continue
        if current_title:
            current_lines.append(stripped)

    flush()
    return entries


def load_brain_pack_file(path: str | Path, *, world_id: str | None = None) -> dict[str, Any]:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    suffix = file_path.suffix.lower()

    if suffix == ".json":
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise ValueError(f"JSON brain pack must be an object/dict: {file_path}")
        return loaded

    if suffix in {".yaml", ".yml"}:
        return _load_yaml(text, file_path)

    if suffix in {".txt", ".md", ".markdown"}:
        inferred_world_id = world_id or slugify(file_path.stem)
        return {
            "schema_version": 1,
            "world_id": inferred_world_id,
            "defaults": {"lorebook": {"visibility": "narrator_only", "importance": 5}},
            "lorebook_entries": parse_lorebook_markdown_text(
                text,
                world_id=inferred_world_id,
                visibility="narrator_only",
                importance=5,
                source_name=file_path.name,
            ),
            "metadata": {"source_file": str(file_path), "source_format": "markdown_lorebook"},
        }

    raise ValueError(f"Unsupported brain pack file type: {file_path.suffix}. Use .json, .yaml/.yml, .txt, or .md.")



_KNOWN_RELATION_NODE_TYPES = {
    "memory",
    "lorebook",
    "entity_state",
    "goal",
    "procedural_skill",
    "skill",
    "agent",
    "entity",
    "faction",
    "quest",
    "location",
    "object",
    "concept",
    "plan_step",
}

_STRICTLY_RESOLVABLE_NODE_TYPES = {"memory", "lorebook", "entity_state", "goal", "procedural_skill", "skill", "agent"}


def _clean_agent_id_from_item(item: dict[str, Any]) -> str:
    return str(item.get("agent_id") or item.get("id") or "").strip()


def _validation_error_text(exc: ValidationError) -> str:
    pieces = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", [])) or "body"
        pieces.append(f"{loc}: {error.get('msg', 'invalid value')}")
    return "; ".join(pieces) or str(exc)

class BrainPackImportService:
    """Import scenario/brain packs into Mozok.

    The pack format is intentionally sparse: every top-level section is optional.
    A pack can contain only lorebook entries, only goals, only skills, etc.
    """

    def __init__(self, db: Session):
        self.db = db

    def normalize_pack(self, pack: dict[str, Any], *, base_dir: str | Path | None = None) -> dict[str, Any]:
        if not isinstance(pack, dict):
            raise ValueError("Brain pack must be a dict/object.")

        normalized: dict[str, Any] = {}
        for key, value in pack.items():
            normalized[_SECTION_ALIASES.get(key, key)] = value

        world_id = str(normalized.get("world_id") or "default")
        normalized["world_id"] = world_id
        defaults = dict(normalized.get("defaults") or {})
        lorebook_defaults = dict(defaults.get("lorebook") or {})

        # Support external lorebook markdown/text files from a JSON/YAML pack.
        entries = list(_as_list(normalized.get("lorebook_entries")))
        for file_spec in _as_list(normalized.get("lorebook_files")):
            if isinstance(file_spec, str):
                file_spec = {"path": file_spec}
            if not isinstance(file_spec, dict):
                continue
            rel_path = file_spec.get("path")
            if not rel_path:
                continue
            source_path = Path(rel_path)
            if not source_path.is_absolute() and base_dir is not None:
                source_path = Path(base_dir) / source_path
            text = source_path.read_text(encoding="utf-8")
            entries.extend(
                parse_lorebook_markdown_text(
                    text,
                    world_id=str(file_spec.get("world_id") or world_id),
                    visibility=str(file_spec.get("visibility") or lorebook_defaults.get("visibility") or "narrator_only"),
                    importance=int(file_spec.get("importance") or lorebook_defaults.get("importance") or 5),
                    default_category=str(file_spec.get("category") or "general"),
                    source_name=source_path.name,
                )
            )

        normalized["lorebook_entries"] = entries
        for section in _COUNT_SECTIONS:
            normalized[section] = _as_list(normalized.get(section))
        return normalized

    def import_pack(
        self,
        pack: dict[str, Any],
        *,
        dry_run: bool = True,
        base_dir: str | Path | None = None,
        validate_relations: bool = False,
        atomic: bool = True,
    ) -> BrainPackImportReport:
        normalized = self.normalize_pack(pack, base_dir=base_dir)
        world_id = str(normalized.get("world_id") or "default")
        report = BrainPackImportReport(dry_run=bool(dry_run), atomic=bool(atomic), world_id=world_id)
        report.counts = {section: len(normalized.get(section) or []) for section in _COUNT_SECTIONS}

        report.warnings.extend(self.preflight_warnings(normalized))
        report.errors.extend(self.preflight_errors(normalized, validate_relations=validate_relations))

        if dry_run:
            for section in _COUNT_SECTIONS:
                for item in normalized.get(section) or []:
                    report.actions.append(
                        BrainPackImportAction(section=section, action="would_upsert", key=self._item_key(section, item))
                    )
            self._import_memories(normalized, report, dry_run=True)
            return report

        if report.errors:
            report.actions.append(
                BrainPackImportAction(
                    section="preflight",
                    action="aborted",
                    key="",
                    message="Import was not started because preflight validation reported errors.",
                )
            )
            return report

        if atomic:
            report = self._import_pack_atomic(normalized, report, validate_relations=validate_relations)
        else:
            self._import_pack_sections(normalized, report, validate_relations=validate_relations)

        if not report.errors:
            self._import_memories(normalized, report, dry_run=False)
        elif normalized.get("memories"):
            report.warnings.append("Skipped memory import because scenario import reported errors.")

        return report

    def _import_memories(self, pack: dict[str, Any], report: BrainPackImportReport, *, dry_run: bool) -> None:
        """Import the optional `memories` section through MemoryService.

        This is intentionally separate from the structural scenario sections.
        MemoryService owns SQL memory creation, embeddings, FAISS indexing,
        duplicate checks, and maintenance side effects.
        """

        if not pack.get("memories"):
            return

        memory_service = None
        if not dry_run:
            try:
                from mozok.core.bot_core import get_memory_service

                memory_service = get_memory_service(self.db)
            except Exception as exc:  # noqa: BLE001 - report cleanly instead of crashing the whole API.
                report.errors.append(f"memory import setup failed: {exc}")
                report.memory_import = {
                    "dry_run": dry_run,
                    "seen": 0,
                    "created": 0,
                    "skipped_duplicates": 0,
                    "skipped_invalid": 0,
                    "created_ids": [],
                    "errors": [str(exc)],
                    "preview": [],
                }
                return

        importer = BrainPackMemoryImporter(db=self.db, memory_service=memory_service)
        memory_result = importer.import_pack_memories(
            pack,
            dry_run=dry_run,
            allow_duplicates=False,
            source_label="scenario_import",
        )
        report.memory_import = memory_result.to_dict()

        if memory_result.created:
            self._record_action(
                report,
                "memories",
                "imported",
                str(memory_result.created),
                message=f"Imported {memory_result.created} indexed memories through MemoryService.",
            )
        elif dry_run and memory_result.seen:
            self._record_action(
                report,
                "memories",
                "would_import",
                str(memory_result.seen),
                message=f"Would import {memory_result.seen} memories through MemoryService.",
            )

        if memory_result.skipped_duplicates:
            self._record_action(
                report,
                "memories",
                "skipped_duplicates",
                str(memory_result.skipped_duplicates),
            )
        if memory_result.skipped_invalid:
            self._record_action(
                report,
                "memories",
                "skipped_invalid",
                str(memory_result.skipped_invalid),
            )
        for error in memory_result.errors:
            report.errors.append(f"memory import: {error}")

    def _import_pack_sections(
        self,
        normalized: dict[str, Any],
        report: BrainPackImportReport,
        *,
        validate_relations: bool,
    ) -> None:
        self._import_agents(normalized, report)
        self._import_lorebook(normalized, report)
        self._import_agent_lorebook_knowledge(normalized, report)
        self._import_entity_states(normalized, report)
        self._import_goals(normalized, report)
        self._import_procedural_skills(normalized, report)
        self._import_knowledge_relations(normalized, report, validate_relations=validate_relations)

    def _import_pack_atomic(
        self,
        normalized: dict[str, Any],
        report: BrainPackImportReport,
        *,
        validate_relations: bool,
    ) -> BrainPackImportReport:
        """Import the whole pack as one logical transaction.

        Existing service methods call ``commit()`` internally. For atomic brain
        packs we temporarily turn those commits into ``flush()`` calls, then do
        one real commit at the end. If any section records an error, everything
        is rolled back.
        """

        real_commit = self.db.commit
        real_rollback = self.db.rollback
        real_commit_attr = getattr(self.db, "commit")
        real_rollback_attr = getattr(self.db, "rollback")

        def flush_instead_of_commit():
            self.db.flush()

        try:
            self.db.commit = flush_instead_of_commit  # type: ignore[method-assign]
            self._import_pack_sections(normalized, report, validate_relations=validate_relations)

            self.db.commit = real_commit_attr  # type: ignore[method-assign]
            self.db.rollback = real_rollback_attr  # type: ignore[method-assign]
            if report.errors:
                real_rollback()
                report.actions.append(
                    BrainPackImportAction(
                        section="atomic",
                        action="rolled_back",
                        key="",
                        message="Atomic import rolled back because one or more section imports failed.",
                    )
                )
            else:
                real_commit()
                report.actions.append(
                    BrainPackImportAction(
                        section="atomic",
                        action="committed",
                        key="",
                        message="Atomic import committed successfully.",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self.db.commit = real_commit_attr  # type: ignore[method-assign]
            self.db.rollback = real_rollback_attr  # type: ignore[method-assign]
            real_rollback()
            report.errors.append(f"atomic import failed and was rolled back: {exc}")
            report.actions.append(
                BrainPackImportAction(
                    section="atomic",
                    action="rolled_back",
                    key="",
                    message="Atomic import failed unexpectedly and was rolled back.",
                )
            )
        finally:
            self.db.commit = real_commit_attr  # type: ignore[method-assign]
            self.db.rollback = real_rollback_attr  # type: ignore[method-assign]

        return report

    def preflight_warnings(self, pack: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        if pack.get("memories"):
            warnings.append("memories will be imported through MemoryService, including embeddings and FAISS indexing.")
        if not pack.get("world_id"):
            warnings.append("world_id is missing; importer will use 'default'.")
        return warnings

    def preflight_errors(self, pack: dict[str, Any], *, validate_relations: bool) -> list[str]:
        errors: list[str] = []
        errors.extend(self._validate_duplicate_keys(pack))
        errors.extend(self._validate_payload_shapes(pack))
        if validate_relations:
            errors.extend(self._validate_relation_nodes_preflight(pack))
        return errors

    def _validate_duplicate_keys(self, pack: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        def check(section: str, key_fn) -> None:
            seen: dict[tuple[Any, ...], int] = {}
            for index, item in enumerate(pack.get(section) or []):
                if not isinstance(item, dict):
                    continue
                key = key_fn(item)
                if not all(str(part or "").strip() for part in key):
                    continue
                if key in seen:
                    errors.append(f"[{section}][{index}] Duplicate key {key!r}; first seen at [{section}][{seen[key]}].")
                else:
                    seen[key] = index

        world_id = str(pack.get("world_id") or "default")
        check("agents", lambda item: (str(item.get("agent_id") or item.get("id") or "").strip(),))
        check("lorebook_entries", lambda item: (str(item.get("world_id") or world_id), str(item.get("entry_key") or "").strip()))
        check("entity_states", lambda item: (str(item.get("agent_id") or "").strip(), str(item.get("entity_id") or "").strip(), str(item.get("state_kind") or "").strip()))
        check("goals", lambda item: (str(item.get("agent_id") or "").strip(), str(item.get("goal_key") or "").strip()))
        check("procedural_skills", lambda item: (str(item.get("agent_id") or "").strip(), str(item.get("skill_key") or "").strip()))
        check(
            "knowledge_relations",
            lambda item: (
                str(item.get("agent_id") or "").strip(),
                str(item.get("world_id") or world_id).strip(),
                str(item.get("source_type") or "").strip(),
                str(item.get("source_id") or "").strip(),
                str(item.get("relation_type") or "").strip(),
                str(item.get("target_type") or "").strip(),
                str(item.get("target_id") or "").strip(),
            ),
        )
        return errors

    def _validate_payload_shapes(self, pack: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        world_id = str(pack.get("world_id") or "default")
        defaults = dict(pack.get("defaults") or {})
        lorebook_defaults = dict(defaults.get("lorebook") or {})

        def require_object(section: str, index: int, item: Any) -> bool:
            if not isinstance(item, dict):
                errors.append(f"[{section}][{index}] Entry must be an object/dict.")
                return False
            return True

        for index, item in enumerate(pack.get("agents") or []):
            if require_object("agents", index, item):
                if not str(item.get("agent_id") or item.get("id") or "").strip():
                    errors.append(f"[agents][{index}] Missing required field: agent_id or id.")

        for index, item in enumerate(pack.get("lorebook_entries") or []):
            if require_object("lorebook_entries", index, item):
                payload = _merge_defaults(item, lorebook_defaults)
                payload.setdefault("world_id", world_id)
                try:
                    LorebookEntryUpsert(**payload)
                except ValidationError as exc:
                    errors.append(f"[lorebook_entries][{index}] {_validation_error_text(exc)}")

        for index, item in enumerate(pack.get("agent_lorebook_knowledge") or []):
            if require_object("agent_lorebook_knowledge", index, item):
                payload = dict(item)
                payload.setdefault("world_id", world_id)
                try:
                    AgentLorebookKnowledgeUpsert(**payload)
                except ValidationError as exc:
                    errors.append(f"[agent_lorebook_knowledge][{index}] {_validation_error_text(exc)}")

        for section, schema in [
            ("entity_states", EntityStateUpsert),
            ("goals", AgentGoalUpsert),
            ("procedural_skills", AgentProceduralSkillUpsert),
            ("knowledge_relations", KnowledgeRelationUpsert),
        ]:
            for index, item in enumerate(pack.get(section) or []):
                if not require_object(section, index, item):
                    continue
                payload = dict(item)
                if section == "knowledge_relations":
                    payload.setdefault("world_id", world_id)
                try:
                    schema(**payload)
                except ValidationError as exc:
                    errors.append(f"[{section}][{index}] {_validation_error_text(exc)}")

        return errors

    def _pack_node_index(self, pack: dict[str, Any]) -> set[tuple[str, str, str, str]]:
        """Return nodes available inside the pack as (agent_id, world_id, type, id)."""

        world_id = str(pack.get("world_id") or "default")
        nodes: set[tuple[str, str, str, str]] = set()
        for item in pack.get("agents") or []:
            if isinstance(item, dict):
                agent_id = str(item.get("agent_id") or item.get("id") or "").strip()
                if agent_id:
                    nodes.add(("*", world_id, "agent", agent_id))
        for item in pack.get("lorebook_entries") or []:
            if isinstance(item, dict):
                item_world = str(item.get("world_id") or world_id)
                key = str(item.get("entry_key") or "").strip()
                if key:
                    nodes.add(("*", item_world, "lorebook", key))
        for item in pack.get("entity_states") or []:
            if isinstance(item, dict):
                agent_id = str(item.get("agent_id") or "").strip()
                entity_id = str(item.get("entity_id") or "").strip()
                if agent_id and entity_id:
                    nodes.add((agent_id, world_id, "entity_state", entity_id))
        for item in pack.get("goals") or []:
            if isinstance(item, dict):
                agent_id = str(item.get("agent_id") or "").strip()
                goal_key = str(item.get("goal_key") or "").strip()
                if agent_id and goal_key:
                    nodes.add((agent_id, world_id, "goal", goal_key))
        for item in pack.get("procedural_skills") or []:
            if isinstance(item, dict):
                agent_id = str(item.get("agent_id") or "").strip()
                skill_key = str(item.get("skill_key") or "").strip()
                if agent_id and skill_key:
                    nodes.add((agent_id, world_id, "procedural_skill", skill_key))
                    nodes.add((agent_id, world_id, "skill", skill_key))
        return nodes

    def _node_exists_in_pack_or_db(
        self,
        *,
        pack_nodes: set[tuple[str, str, str, str]],
        agent_id: str,
        world_id: str,
        node_type: str,
        node_id: str,
    ) -> bool:
        safe_type = str(node_type or "").strip()
        safe_id = str(node_id or "").strip()
        if not safe_type or not safe_id:
            return False
        if safe_type not in _STRICTLY_RESOLVABLE_NODE_TYPES:
            return True
        if (agent_id, world_id, safe_type, safe_id) in pack_nodes or ("*", world_id, safe_type, safe_id) in pack_nodes:
            return True
        if safe_type == "skill" and (agent_id, world_id, "procedural_skill", safe_id) in pack_nodes:
            return True
        if safe_type == "procedural_skill" and (agent_id, world_id, "skill", safe_id) in pack_nodes:
            return True
        resolution = KnowledgeRelationService(self.db).resolve_node(
            agent_id=agent_id,
            world_id=world_id,
            node_type=safe_type,
            node_id=safe_id,
        )
        return bool(resolution.found)

    def _validate_relation_nodes_preflight(self, pack: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        world_id = str(pack.get("world_id") or "default")
        pack_nodes = self._pack_node_index(pack)
        for index, item in enumerate(pack.get("knowledge_relations") or []):
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("agent_id") or "").strip()
            item_world_id = str(item.get("world_id") or world_id).strip()
            source_type = str(item.get("source_type") or "").strip()
            source_id = str(item.get("source_id") or "").strip()
            target_type = str(item.get("target_type") or "").strip()
            target_id = str(item.get("target_id") or "").strip()
            if source_type in _STRICTLY_RESOLVABLE_NODE_TYPES and not self._node_exists_in_pack_or_db(
                pack_nodes=pack_nodes,
                agent_id=agent_id,
                world_id=item_world_id,
                node_type=source_type,
                node_id=source_id,
            ):
                errors.append(f"[knowledge_relations][{index}] source {source_type}:{source_id} not found in pack or database.")
            if target_type in _STRICTLY_RESOLVABLE_NODE_TYPES and not self._node_exists_in_pack_or_db(
                pack_nodes=pack_nodes,
                agent_id=agent_id,
                world_id=item_world_id,
                node_type=target_type,
                node_id=target_id,
            ):
                errors.append(f"[knowledge_relations][{index}] target {target_type}:{target_id} not found in pack or database.")
        return errors

    def _item_key(self, section: str, item: Any) -> str:
        if not isinstance(item, dict):
            return str(item)[:80]
        return str(
            item.get("id")
            or item.get("agent_id")
            and (item.get("skill_key") or item.get("goal_key") or item.get("entity_id"))
            or item.get("entry_key")
            or item.get("title")
            or item.get("source_id")
            or item.get("path")
            or ""
        )

    def _record_action(self, report: BrainPackImportReport, section: str, action: str, key: str, message: str = "") -> None:
        report.actions.append(BrainPackImportAction(section=section, action=action, key=key, message=message))

    def _record_error(self, report: BrainPackImportReport, section: str, item: Any, exc: Exception) -> None:
        report.errors.append(f"{section} {self._item_key(section, item)!r}: {exc}")

    def _import_agents(self, pack: dict[str, Any], report: BrainPackImportReport) -> None:
        service = AgentService(self.db)
        for item in pack.get("agents") or []:
            try:
                if not isinstance(item, dict):
                    raise ValueError("agent entry must be an object")
                agent_id = str(item.get("agent_id") or item.get("id") or "").strip()
                if not agent_id:
                    raise ValueError("agent_id or id is required")
                existing = service.get_agent(agent_id)
                if existing is None:
                    service.create_agent(
                        agent_id=agent_id,
                        name=str(item.get("name") or agent_id),
                        description=str(item.get("description") or ""),
                        personality=str(item.get("personality") or ""),
                        system_prompt=str(item.get("system_prompt") or ""),
                        state=dict(item.get("state") or {}),
                        metadata=dict(item.get("metadata") or {}),
                    )
                    self._record_action(report, "agents", "created", agent_id)
                else:
                    existing.name = str(item.get("name") or existing.name or agent_id)
                    existing.description = str(item.get("description") if item.get("description") is not None else existing.description or "")
                    existing.personality = str(item.get("personality") if item.get("personality") is not None else existing.personality or "")
                    existing.system_prompt = str(item.get("system_prompt") if item.get("system_prompt") is not None else existing.system_prompt or "")
                    if "state" in item:
                        existing.state_json = dict(item.get("state") or {})
                    if "metadata" in item:
                        existing.metadata_json = dict(item.get("metadata") or {})
                    self.db.commit()
                    self.db.refresh(existing)
                    self._record_action(report, "agents", "updated", agent_id)
            except Exception as exc:  # noqa: BLE001
                self._record_error(report, "agents", item, exc)

    def _import_lorebook(self, pack: dict[str, Any], report: BrainPackImportReport) -> None:
        service = LorebookService(self.db)
        world_id = str(pack.get("world_id") or "default")
        defaults = dict((pack.get("defaults") or {}).get("lorebook") or {})
        for item in pack.get("lorebook_entries") or []:
            try:
                if not isinstance(item, dict):
                    raise ValueError("lorebook entry must be an object")
                payload = _merge_defaults(item, defaults)
                payload.setdefault("world_id", world_id)
                entry = service.upsert_entry(LorebookEntryUpsert(**payload))
                self._record_action(report, "lorebook_entries", "upserted", entry.entry_key)
            except (ValidationError, Exception) as exc:  # noqa: BLE001
                self._record_error(report, "lorebook_entries", item, exc)

    def _import_agent_lorebook_knowledge(self, pack: dict[str, Any], report: BrainPackImportReport) -> None:
        service = LorebookService(self.db)
        world_id = str(pack.get("world_id") or "default")
        for item in pack.get("agent_lorebook_knowledge") or []:
            try:
                if not isinstance(item, dict):
                    raise ValueError("agent lorebook knowledge entry must be an object")
                payload = dict(item)
                payload.setdefault("world_id", world_id)
                link = service.upsert_agent_knowledge(AgentLorebookKnowledgeUpsert(**payload))
                self._record_action(report, "agent_lorebook_knowledge", "upserted", str(link.id))
            except (ValidationError, Exception) as exc:  # noqa: BLE001
                self._record_error(report, "agent_lorebook_knowledge", item, exc)

    def _import_entity_states(self, pack: dict[str, Any], report: BrainPackImportReport) -> None:
        service = EntityStateService(self.db)
        for item in pack.get("entity_states") or []:
            try:
                if not isinstance(item, dict):
                    raise ValueError("entity state entry must be an object")
                record = service.upsert(EntityStateUpsert(**item))
                self._record_action(report, "entity_states", "upserted", f"{record.agent_id}:{record.entity_id}:{record.state_kind}")
            except (ValidationError, Exception) as exc:  # noqa: BLE001
                self._record_error(report, "entity_states", item, exc)

    def _import_goals(self, pack: dict[str, Any], report: BrainPackImportReport) -> None:
        service = GoalService(self.db)
        for item in pack.get("goals") or []:
            try:
                if not isinstance(item, dict):
                    raise ValueError("goal entry must be an object")
                record = service.upsert(AgentGoalUpsert(**item))
                self._record_action(report, "goals", "upserted", f"{record.agent_id}:{record.goal_key}")
            except (ValidationError, Exception) as exc:  # noqa: BLE001
                self._record_error(report, "goals", item, exc)

    def _import_procedural_skills(self, pack: dict[str, Any], report: BrainPackImportReport) -> None:
        service = ProceduralSkillService(self.db)
        for item in pack.get("procedural_skills") or []:
            try:
                if not isinstance(item, dict):
                    raise ValueError("procedural skill entry must be an object")
                record = service.upsert(AgentProceduralSkillUpsert(**item))
                self._record_action(report, "procedural_skills", "upserted", f"{record.agent_id}:{record.skill_key}")
            except (ValidationError, Exception) as exc:  # noqa: BLE001
                self._record_error(report, "procedural_skills", item, exc)

    def _import_knowledge_relations(
        self,
        pack: dict[str, Any],
        report: BrainPackImportReport,
        *,
        validate_relations: bool,
    ) -> None:
        service = KnowledgeRelationService(self.db)
        world_id = str(pack.get("world_id") or "default")
        for item in pack.get("knowledge_relations") or []:
            try:
                if not isinstance(item, dict):
                    raise ValueError("knowledge relation entry must be an object")
                payload = dict(item)
                payload.setdefault("world_id", world_id)
                if validate_relations:
                    payload["validate_nodes"] = True
                record = service.upsert(KnowledgeRelationUpsert(**payload))
                self._record_action(report, "knowledge_relations", "upserted", str(record.id))
            except (ValidationError, Exception) as exc:  # noqa: BLE001
                self._record_error(report, "knowledge_relations", item, exc)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a Mozok brain/scenario pack from JSON, YAML, or markdown/txt lorebook.")
    parser.add_argument("path", help="Path to .json/.yaml/.yml brain pack, or .txt/.md lorebook file.")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without writing to the database.")
    parser.add_argument("--world-id", default=None, help="Override world_id for direct .txt/.md imports.")
    parser.add_argument("--validate-relations", action="store_true", help="Require known relation source/target nodes to exist.")
    parser.add_argument("--no-atomic", action="store_true", help="Allow partial imports instead of rolling the whole pack back on errors.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON report.")
    return parser
