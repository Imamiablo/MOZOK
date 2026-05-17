from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mozok_game.engine.pack_validation import (
    ValidationReport,
    list_object_templates,
    list_scenarios,
    load_scenario_spec,
    spawn_object_instance,
    validate_character_card,
    validate_appraisal_pack,
    validate_map_pack,
    validate_object_pack,
    validate_scenario_pack,
    validate_storylet_pack,
)
from mozok_game.engine.world_state import load_world_from_path


PACK_FOLDERS = ["scenarios", "maps", "objects", "agents", "items", "storylets", "drama_atoms", "dialogue", "director_moments", "appraisals"]


@dataclass(slots=True)
class DraftValidationResult:
    report: ValidationReport
    preview_loaded: bool = False
    smoke_ok: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.report.ok and self.preview_loaded and self.smoke_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "preview_loaded": self.preview_loaded,
            "smoke_ok": self.smoke_ok,
            "messages": list(self.messages),
            "validation": self.report.to_dict(),
        }


def list_available_packs(base_dir: Path) -> dict[str, list[str]]:
    packs: dict[str, list[str]] = {}
    for folder in PACK_FOLDERS:
        root = base_dir / "data" / folder
        packs[folder] = sorted(path.stem for path in root.glob("*.json")) if root.exists() else []
    return packs


def create_scenario(
    base_dir: Path,
    scenario_id: str,
    title: str,
    map_ref: str = "",
    object_pack_refs: list[str] | None = None,
    character_refs: list[Any] | None = None,
    item_pack_refs: list[str] | None = None,
    overwrite: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    scenario = {
        "scenario_id": scenario_id,
        "title": title,
        "setting": {"summary": str(extra.pop("setting_summary", ""))},
        "tone": dict(extra.pop("tone", {}) or {}),
        "themes": list(extra.pop("themes", []) or []),
        "map_ref": map_ref,
        "object_pack_refs": list(object_pack_refs or []),
        "character_refs": list(character_refs or []),
        "item_pack_refs": list(item_pack_refs or ["items"]),
        **extra,
    }
    save_scenario_spec(base_dir, scenario_id, scenario, overwrite=overwrite)
    return scenario


def duplicate_scenario(base_dir: Path, source_scenario_id: str, new_scenario_id: str, title: str | None = None, overwrite: bool = False) -> dict[str, Any]:
    spec = load_scenario_spec(base_dir, source_scenario_id)
    spec["scenario_id"] = new_scenario_id
    spec["title"] = title or f"{spec.get('title') or source_scenario_id} Copy"
    save_scenario_spec(base_dir, new_scenario_id, spec, overwrite=overwrite)
    return spec


def save_scenario_spec(base_dir: Path, scenario_id: str, spec: dict[str, Any], overwrite: bool = True) -> Path:
    path = _data_ref_path(base_dir, "scenarios", scenario_id)
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def save_pack(base_dir: Path, folder: str, ref: str, data: dict[str, Any] | list[Any], overwrite: bool = True) -> Path:
    if folder not in PACK_FOLDERS:
        raise ValueError(f"Unknown pack folder: {folder}")
    path = _data_ref_path(base_dir, folder, ref)
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def add_object_instance(base_dir: Path, object_pack_ref: str, template_id: str, instance_id: str, position: tuple[int, int] | list[int], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    pack, path = _load_pack_with_path(base_dir, "objects", object_pack_ref)
    templates = list_object_templates(base_dir, object_pack_ref)
    if template_id not in templates:
        raise KeyError(f"Unknown object template: {template_id}")
    instances = pack.setdefault("instances", [])
    if not isinstance(instances, list):
        raise ValueError("Object pack instances must be a list")
    if any(isinstance(item, dict) and item.get("id") == instance_id for item in instances):
        raise ValueError(f"Object instance already exists: {instance_id}")
    instance = spawn_object_instance(template_id, instance_id, position, overrides)
    instances.append(instance)
    _save_json(path, pack)
    return instance


def move_object_instance(base_dir: Path, object_pack_ref: str, instance_id: str, position: tuple[int, int] | list[int]) -> dict[str, Any]:
    pack, path = _load_pack_with_path(base_dir, "objects", object_pack_ref)
    instance = _find_instance(pack, instance_id)
    instance["position"] = [int(position[0]), int(position[1])]
    _save_json(path, pack)
    return instance


def remove_object_instance(base_dir: Path, object_pack_ref: str, instance_id: str) -> bool:
    pack, path = _load_pack_with_path(base_dir, "objects", object_pack_ref)
    instances = pack.get("instances")
    if not isinstance(instances, list):
        return False
    before = len(instances)
    pack["instances"] = [item for item in instances if not (isinstance(item, dict) and item.get("id") == instance_id)]
    changed = len(pack["instances"]) != before
    if changed:
        _save_json(path, pack)
    return changed


def edit_character_override(base_dir: Path, scenario_id: str, character_id: str, overrides: dict[str, Any]) -> dict[str, Any]:
    spec = load_scenario_spec(base_dir, scenario_id)
    refs = spec.setdefault("character_refs", [])
    if not isinstance(refs, list):
        raise ValueError("scenario.character_refs must be a list")
    for index, item in enumerate(refs):
        if isinstance(item, str) and item == character_id:
            refs[index] = {"id": character_id, "overrides": dict(overrides)}
            save_scenario_spec(base_dir, scenario_id, spec)
            return refs[index]
        if isinstance(item, dict) and str(item.get("id") or item.get("ref")) == character_id:
            current = dict(item.get("overrides") or {})
            item["overrides"] = _deep_merge(current, dict(overrides))
            save_scenario_spec(base_dir, scenario_id, spec)
            return item
    entry = {"id": character_id, "overrides": dict(overrides)}
    refs.append(entry)
    save_scenario_spec(base_dir, scenario_id, spec)
    return entry


def validate_all(base_dir: Path) -> ValidationReport:
    report = ValidationReport()
    for scenario in list_scenarios(base_dir):
        report.extend(validate_scenario_pack(base_dir, scenario))
    for path in (base_dir / "data" / "maps").glob("*.json"):
        report.extend(validate_map_pack(path))
    for path in (base_dir / "data" / "objects").glob("*.json"):
        report.extend(validate_object_pack(path))
    for path in (base_dir / "data" / "agents").glob("*.json"):
        report.extend(validate_character_card(path))
    for path in (base_dir / "data" / "storylets").glob("*.json"):
        report.extend(validate_storylet_pack(path))
    for path in (base_dir / "data" / "appraisals").glob("*.json"):
        report.extend(validate_appraisal_pack(path))
    return report


def validate_draft_scenario(base_dir: Path, draft: dict[str, Any]) -> DraftValidationResult:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{draft.get('scenario_id') or 'draft'}.json"
        path.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
        report = validate_scenario_pack(base_dir, path)
        result = DraftValidationResult(report=report)
        if not report.ok:
            result.messages.append("Validation failed before preview load.")
            return result
        try:
            world = load_world_from_path(base_dir, path)
            result.preview_loaded = True
            result.smoke_ok = world.grid.width > 0 and world.grid.height > 0 and bool(world.agents)
            result.messages.append(f"Preview loaded: {world.scenario_title}, agents={len(world.agents)}, objects={len(world.objects)}.")
        except Exception as exc:  # noqa: BLE001 - editor validation should report draft problems.
            result.messages.append(f"Preview load failed: {type(exc).__name__}: {exc}")
        return result


def save_generated_scenario(base_dir: Path, scenario_id: str, draft: dict[str, Any], overwrite: bool = False) -> DraftValidationResult:
    result = validate_draft_scenario(base_dir, draft)
    if result.ok:
        save_scenario_spec(base_dir, scenario_id, draft, overwrite=overwrite)
    return result


def _load_pack_with_path(base_dir: Path, folder: str, ref: str) -> tuple[dict[str, Any], Path]:
    path = _data_ref_path(base_dir, folder, ref)
    return json.loads(path.read_text(encoding="utf-8")), path


def _find_instance(pack: dict[str, Any], instance_id: str) -> dict[str, Any]:
    instances = pack.get("instances")
    if not isinstance(instances, list):
        raise ValueError("Object pack instances must be a list")
    for item in instances:
        if isinstance(item, dict) and item.get("id") == instance_id:
            return item
    raise KeyError(instance_id)


def _data_ref_path(base_dir: Path, folder: str, ref: str) -> Path:
    ref_path = Path(ref)
    if ref_path.suffix:
        return ref_path if ref_path.is_absolute() else base_dir / "data" / folder / ref_path
    return base_dir / "data" / folder / f"{ref}.json"


def _save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(dict(result[key]), value)
        else:
            result[key] = value
    return result
