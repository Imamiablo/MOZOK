from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mozok_game.engine.pressure import default_pressure_field


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    message: str
    path: str = ""


@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def error(self, message: str, path: str = "") -> None:
        self.issues.append(ValidationIssue("error", message, path))

    def warning(self, message: str, path: str = "") -> None:
        self.issues.append(ValidationIssue("warning", message, path))

    def extend(self, other: "ValidationReport") -> None:
        self.issues.extend(other.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [
                {"severity": issue.severity, "message": issue.message, "path": issue.path}
                for issue in self.issues
            ],
        }


GENERIC_LEGEND_SYMBOLS = {".", "#", "~", "S", "@"}
KNOWN_STORYLET_EFFECTS = {
    "log",
    "agent_need_delta_if_unprotected",
    "agent_need_delta",
    "agent_social_delta",
    "agent_relationship_delta",
    "all_agent_need_delta",
    "flash",
    "flash_all_agents",
    "set_world_flag",
    "set_object_state",
    "set_location_access",
    "spawn_object",
    "claim",
    "create_goal",
    "create_commitment",
    "schedule_followup_storylet",
    "choice_offer",
}


def list_scenarios(base_dir: Path) -> list[str]:
    return sorted(path.stem for path in (base_dir / "data" / "scenarios").glob("*.json"))


def load_scenario_spec(base_dir: Path, scenario_id: str) -> dict[str, Any]:
    return _load_json(_data_ref_path(base_dir, "scenarios", scenario_id))


def list_object_templates(base_dir: Path, object_pack_ref: str) -> dict[str, dict[str, Any]]:
    pack = _load_json(_data_ref_path(base_dir, "objects", object_pack_ref))
    templates = pack.get("templates")
    if isinstance(templates, dict):
        return {str(key): dict(value) for key, value in templates.items() if isinstance(value, dict)}
    result: dict[str, dict[str, Any]] = {}
    for item in pack.get("objects", []) if isinstance(pack.get("objects"), list) else []:
        if isinstance(item, dict) and item.get("kind"):
            result[str(item["kind"])] = dict(item)
    return result


def spawn_object_instance(template_id: str, instance_id: str, position: tuple[int, int] | list[int], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    data = {
        "id": instance_id,
        "template_id": template_id,
        "position": [int(position[0]), int(position[1])],
    }
    if overrides:
        data.update(dict(overrides))
    return data


def validate_scenario_pack(base_dir: Path, scenario_id_or_path: str | Path) -> ValidationReport:
    report = ValidationReport()
    scenario_path = _resolve_scenario_path(base_dir, scenario_id_or_path)
    data = _try_load_json(report, scenario_path, "scenario")
    if not isinstance(data, dict):
        return report

    if not data.get("scenario_id"):
        report.warning("Scenario has no scenario_id; filename will be used.", str(scenario_path))
    if not data.get("map") and not data.get("map_ref"):
        report.error("Scenario must define map_ref or inline map.rows.", str(scenario_path))

    map_ref = data.get("map_ref")
    if map_ref:
        report.extend(validate_map_pack(_data_ref_path(base_dir, "maps", str(map_ref))))
    elif isinstance(data.get("map"), dict):
        report.extend(validate_map_data(dict(data["map"]), f"{scenario_path}:map"))

    for ref in _as_list(data.get("object_pack_refs")):
        report.extend(validate_object_pack(_data_ref_path(base_dir, "objects", str(ref))))
    for ref in _as_list(data.get("character_refs")):
        character_id = str(ref.get("ref") or ref.get("id") if isinstance(ref, dict) else ref)
        if character_id:
            path = _data_ref_path(base_dir, "agents", character_id)
            if path.exists():
                report.extend(validate_character_card(path))
            elif not isinstance(ref, dict) or not ref.get("name"):
                report.error(f"Character ref '{character_id}' does not exist and has no inline card.", str(path))
    for ref in _as_list(data.get("storylet_pack_refs")):
        report.extend(validate_storylet_pack(_data_ref_path(base_dir, "storylets", str(ref))))
    for folder, key in (
        ("items", "item_pack_refs"),
        ("drama_atoms", "drama_atom_pack_refs"),
        ("dialogue", "dialogue_pack_refs"),
        ("director_moments", "director_moment_pack_refs"),
    ):
        for ref in _as_list(data.get(key)):
            path = _data_ref_path(base_dir, folder, str(ref))
            if not path.exists():
                report.error(f"Missing {folder} pack '{ref}'.", str(path))
    for ref in _as_list(data.get("appraisal_pack_refs")):
        report.extend(validate_appraisal_pack(_data_ref_path(base_dir, "appraisals", str(ref))))
    return report


def validate_map_pack(path: Path) -> ValidationReport:
    report = ValidationReport()
    data = _try_load_json(report, path, "map")
    if not isinstance(data, dict):
        return report
    map_data = dict(data.get("map") or data)
    report.extend(validate_map_data(map_data, str(path)))
    return report


def validate_map_data(map_data: dict[str, Any], path: str = "") -> ValidationReport:
    report = ValidationReport()
    rows = map_data.get("rows")
    if not isinstance(rows, list) or not rows:
        report.error("Map pack must contain non-empty rows.", path)
        return report
    legend = dict(map_data.get("legend") or {})
    tile_defs = dict(map_data.get("tile_defs") or {})
    used_symbols = {char for row in rows if isinstance(row, str) for char in row}
    missing_symbols = sorted(symbol for symbol in used_symbols if symbol not in legend and symbol not in GENERIC_LEGEND_SYMBOLS)
    if missing_symbols:
        report.error(f"Map legend is missing symbols: {', '.join(missing_symbols)}.", path)
    for symbol, raw in legend.items():
        if isinstance(raw, dict):
            kind = str(raw.get("kind") or raw.get("tile") or "")
        elif isinstance(raw, list) and raw:
            kind = str(raw[0])
        else:
            kind = str(raw)
        if kind and kind not in tile_defs:
            report.warning(f"Legend symbol '{symbol}' references tile kind '{kind}' without tile_defs metadata.", path)
    return report


def validate_object_pack(path: Path) -> ValidationReport:
    report = ValidationReport()
    pack = _try_load_json(report, path, "object pack")
    if not isinstance(pack, dict):
        return report
    templates = pack.get("templates")
    instances = pack.get("instances")
    if isinstance(templates, dict) or isinstance(instances, list):
        if not isinstance(templates, dict):
            report.error("Object pack with instances must define templates.", str(path))
            templates = {}
        if not isinstance(instances, list):
            report.error("Object pack with templates must define instances.", str(path))
            instances = []
        for template_id, template in templates.items():
            if not isinstance(template, dict):
                report.error(f"Object template '{template_id}' is not an object.", str(path))
                continue
            _validate_object_shape(report, template, f"{path}:templates.{template_id}", require_position=False)
        for index, instance in enumerate(instances):
            if not isinstance(instance, dict):
                report.error(f"Object instance {index} is not an object.", str(path))
                continue
            template_id = str(instance.get("template_id") or instance.get("template") or "")
            if template_id not in templates:
                report.error(f"Object instance '{instance.get('id', index)}' references unknown template '{template_id}'.", str(path))
            _validate_object_shape(report, instance, f"{path}:instances[{index}]", require_position=True, allow_missing_name=True)
        return report
    objects = pack.get("objects")
    if isinstance(objects, list):
        for index, obj in enumerate(objects):
            if isinstance(obj, dict):
                _validate_object_shape(report, obj, f"{path}:objects[{index}]", require_position=True)
            else:
                report.error(f"Object entry {index} is not an object.", str(path))
    else:
        report.warning("Object pack has no templates/instances or objects list.", str(path))
    return report


def validate_character_card(path: Path) -> ValidationReport:
    report = ValidationReport()
    data = _try_load_json(report, path, "character card")
    if not isinstance(data, dict):
        return report
    for key in ("id", "name", "personality"):
        if not data.get(key):
            report.warning(f"Character card is missing '{key}'.", str(path))
    if "traits" in data and not isinstance(data["traits"], dict):
        report.error("Character traits must be a mapping.", str(path))
    for key in ("values", "fears", "skills", "limits", "temptations"):
        if key in data and not isinstance(data[key], list):
            report.error(f"Character field '{key}' must be a list.", str(path))
    return report


def validate_storylet_pack(path: Path) -> ValidationReport:
    report = ValidationReport()
    raw = _try_load_json(report, path, "storylet pack")
    if not isinstance(raw, (list, dict)):
        return report
    storylets = raw if isinstance(raw, list) else raw.get("storylets", [])
    if not isinstance(storylets, list):
        report.error("Storylet pack must be a list or contain storylets list.", str(path))
        return report
    known_axes = set(default_pressure_field())
    for index, storylet in enumerate(storylets):
        item_path = f"{path}:storylets[{index}]"
        if not isinstance(storylet, dict):
            report.error("Storylet entry is not an object.", item_path)
            continue
        if not storylet.get("id"):
            report.error("Storylet is missing id.", item_path)
        requires = dict(storylet.get("requires") or {})
        for key in ("pressure_gte", "pressure_lte"):
            for axis in dict(requires.get(key) or {}):
                if str(axis) not in known_axes:
                    report.error(f"Unknown pressure axis '{axis}'.", item_path)
        pressure_sum = requires.get("pressure_sum_gt")
        if isinstance(pressure_sum, dict):
            for axis in pressure_sum.get("axes") or []:
                if str(axis) not in known_axes:
                    report.error(f"Unknown pressure axis '{axis}'.", item_path)
        for effect in storylet.get("effects") or []:
            if not isinstance(effect, dict):
                report.error("Storylet effect is not an object.", item_path)
                continue
            effect_type = str(effect.get("type") or "")
            if effect_type not in KNOWN_STORYLET_EFFECTS:
                report.warning(f"Unknown storylet effect type '{effect_type}'.", item_path)
    return report


def validate_appraisal_pack(path: Path) -> ValidationReport:
    report = ValidationReport()
    raw = _try_load_json(report, path, "appraisal pack")
    if not isinstance(raw, (list, dict)):
        return report
    rules = raw if isinstance(raw, list) else raw.get("appraisals", raw.get("rules", []))
    if not isinstance(rules, list):
        report.error("Appraisal pack must be a list or contain appraisals/rules list.", str(path))
        return report
    known_axes = set(default_pressure_field())
    for index, rule in enumerate(rules):
        item_path = f"{path}:appraisals[{index}]"
        if not isinstance(rule, dict):
            report.error("Appraisal rule is not an object.", item_path)
            continue
        if not rule.get("id"):
            report.error("Appraisal rule is missing id.", item_path)
        if not rule.get("concern"):
            report.warning("Appraisal rule has no concern; id will be used.", item_path)
        for axis in dict(rule.get("pressure_weights") or {}):
            if str(axis) not in known_axes:
                report.error(f"Unknown pressure axis '{axis}'.", item_path)
        for axis in rule.get("pressure_axes") or []:
            if str(axis) not in known_axes:
                report.warning(f"Unknown pressure axis '{axis}' in pressure_axes.", item_path)
    return report


def _validate_object_shape(report: ValidationReport, obj: dict[str, Any], path: str, require_position: bool, allow_missing_name: bool = False) -> None:
    if not obj.get("id") and require_position:
        report.error("Object instance is missing id.", path)
    if not allow_missing_name and not obj.get("name"):
        report.warning("Object is missing display name.", path)
    if require_position and not _valid_position(obj.get("position")):
        report.error("Object must define position as [x, y].", path)
    interactions = obj.get("interactions")
    if interactions is not None and not isinstance(interactions, (list, dict)):
        report.error("Object interactions must be a list or mapping.", path)


def _try_load_json(report: ValidationReport, path: Path, label: str) -> Any:
    if not path.exists():
        report.error(f"Missing {label}: {path}", str(path))
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - validation should report malformed data.
        report.error(f"Could not read {label}: {type(exc).__name__}: {exc}", str(path))
        return None


def _valid_position(raw: Any) -> bool:
    return isinstance(raw, list) and len(raw) >= 2 and all(isinstance(value, int) for value in raw[:2])


def _resolve_scenario_path(base_dir: Path, scenario_id_or_path: str | Path) -> Path:
    path = Path(scenario_id_or_path)
    if path.suffix:
        return path if path.is_absolute() else base_dir / path
    return _data_ref_path(base_dir, "scenarios", str(scenario_id_or_path))


def _data_ref_path(base_dir: Path, folder: str, ref: str) -> Path:
    ref_path = Path(ref)
    if ref_path.suffix:
        return ref_path if ref_path.is_absolute() else base_dir / "data" / folder / ref_path
    return base_dir / "data" / folder / f"{ref}.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]
