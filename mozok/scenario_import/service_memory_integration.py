"""Integrate brain-pack memory import into the main ScenarioImportService.

This module intentionally patches/wraps ScenarioImportService instead of copying
its whole implementation. MOZOK's scenario importer has grown quickly, and this
keeps the memory-import step small, reusable, and easy to remove/refactor later.

The integration calls BrainPackMemoryImporter after the normal scenario import
method succeeds. Memories are imported through MemoryService, so SQL + embeddings
+ FAISS remain handled by the existing memory pipeline.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from functools import wraps
from typing import Any, Callable

from mozok.scenario_import.memory_importer import BrainPackMemoryImporter


DEFAULT_METHOD_NAMES: tuple[str, ...] = (
    "import_pack",
    "import_brain_pack",
    "import_scenario_pack",
    "import_scenario",
)


def _get_attr_any(obj: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return None


def _get_db(service: Any) -> Any:
    """Best-effort DB/session lookup across previous MOZOK service versions."""

    return _get_attr_any(service, ("db", "session", "db_session", "_db", "_session"))


def _default_memory_service_factory(db: Any) -> Any:
    from mozok.memory.service import MemoryService

    return MemoryService(db)


def _bind_arguments(method: Callable[..., Any], self_obj: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return a loose mapping of argument names to values.

    If signature binding fails, fall back to positional aliases. This keeps the
    wrapper tolerant of small API changes in ScenarioImportService.
    """

    bound: dict[str, Any] = {}
    try:
        signature = inspect.signature(method)
        partial = signature.bind_partial(self_obj, *args, **kwargs)
        bound.update(partial.arguments)
    except Exception:
        pass

    # Do not expose `self` as a possible pack candidate.
    bound.pop("self", None)

    # Add generic positional aliases as a fallback.
    for index, value in enumerate(args):
        bound.setdefault(f"arg{index}", value)

    bound.update(kwargs)
    return bound


def _find_pack(bound_arguments: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in ("pack", "brain_pack", "scenario_pack", "data", "payload", "document", "arg0"):
        value = bound_arguments.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _find_default_agent_id(bound_arguments: Mapping[str, Any], pack: Mapping[str, Any]) -> str | None:
    for key in ("default_agent_id", "agent_id", "fallback_agent_id"):
        value = bound_arguments.get(key)
        if value:
            return str(value)

    defaults = pack.get("defaults")
    if isinstance(defaults, Mapping) and defaults.get("agent_id"):
        return str(defaults["agent_id"])

    for key in ("agent_id", "default_agent_id"):
        value = pack.get(key)
        if value:
            return str(value)
    return None


def _find_bool(bound_arguments: Mapping[str, Any], names: tuple[str, ...], default: bool = False) -> bool:
    for name in names:
        if name in bound_arguments:
            return bool(bound_arguments[name])
    return default


def _result_to_dict(memory_result: Any) -> dict[str, Any]:
    if hasattr(memory_result, "to_dict"):
        return memory_result.to_dict()
    if isinstance(memory_result, Mapping):
        return dict(memory_result)
    return {
        "seen": getattr(memory_result, "seen", 0),
        "created": getattr(memory_result, "created", 0),
        "skipped_duplicates": getattr(memory_result, "skipped_duplicates", 0),
        "skipped_invalid": getattr(memory_result, "skipped_invalid", 0),
        "errors": list(getattr(memory_result, "errors", []) or []),
    }


def _merge_memory_import_report(result: Any, memory_report: dict[str, Any]) -> Any:
    """Attach the memory import report to whatever object the importer returns."""

    if isinstance(result, dict):
        result["memory_import"] = memory_report
        return result

    # Dataclasses/simple objects.
    try:
        setattr(result, "memory_import", memory_report)
        return result
    except Exception:
        pass

    # Pydantic/dataclass objects that carry details/metadata as dict-like fields.
    for attr_name in ("details", "metadata", "extra", "report"):
        container = getattr(result, attr_name, None)
        if isinstance(container, dict):
            container["memory_import"] = memory_report
            return result

    # Last resort: leave the original result untouched. The memory import still
    # happened, but old strict response schemas might not allow a new field.
    return result


def _import_memories_after_main_import(
    service: Any,
    pack: Mapping[str, Any],
    result: Any,
    *,
    dry_run: bool,
    allow_duplicates: bool,
    default_agent_id: str | None,
    memory_service_factory: Callable[[Any], Any] | None = None,
) -> Any:
    if "memories" not in pack:
        return result

    db = _get_db(service)
    memory_service = _get_attr_any(service, ("memory_service", "memories", "_memory_service"))

    if memory_service is None and memory_service_factory is not None:
        memory_service = memory_service_factory(db)
    elif memory_service is None and db is not None:
        memory_service = _default_memory_service_factory(db)

    if memory_service is None and not dry_run:
        memory_report = {
            "dry_run": dry_run,
            "seen": 0,
            "created": 0,
            "skipped_duplicates": 0,
            "skipped_invalid": 0,
            "created_ids": [],
            "errors": [
                "Brain-pack memories were present, but ScenarioImportService did not expose a DB/session or memory_service."
            ],
            "preview": [],
        }
        return _merge_memory_import_report(result, memory_report)

    importer = BrainPackMemoryImporter(db=db, memory_service=memory_service)
    memory_result = importer.import_pack_memories(
        pack,
        default_agent_id=default_agent_id,
        dry_run=dry_run,
        allow_duplicates=allow_duplicates,
        source_label="scenario_import",
    )
    return _merge_memory_import_report(result, _result_to_dict(memory_result))


def install_memory_import_integration(
    service_cls: type[Any],
    *,
    method_names: tuple[str, ...] = DEFAULT_METHOD_NAMES,
    memory_service_factory: Callable[[Any], Any] | None = None,
    force: bool = False,
) -> bool:
    """Wrap the main scenario import method so it also imports `memories`.

    Returns True when at least one method was wrapped.
    """

    installed_any = False

    for method_name in method_names:
        original = getattr(service_cls, method_name, None)
        if original is None or not callable(original):
            continue

        if getattr(original, "_mozok_memory_import_integrated", False) and not force:
            installed_any = True
            continue

        @wraps(original)
        def wrapped(self: Any, *args: Any, __original: Callable[..., Any] = original, **kwargs: Any) -> Any:
            bound = _bind_arguments(__original, self, args, kwargs)
            pack = _find_pack(bound)

            result = __original(self, *args, **kwargs)

            if pack is None:
                return result

            dry_run = _find_bool(bound, ("dry_run", "preview", "validate_only"), default=False)
            allow_duplicates = _find_bool(bound, ("allow_duplicates", "allow_memory_duplicates"), default=False)
            default_agent_id = _find_default_agent_id(bound, pack)

            return _import_memories_after_main_import(
                self,
                pack,
                result,
                dry_run=dry_run,
                allow_duplicates=allow_duplicates,
                default_agent_id=default_agent_id,
                memory_service_factory=memory_service_factory,
            )

        setattr(wrapped, "_mozok_memory_import_integrated", True)
        setattr(service_cls, method_name, wrapped)
        installed_any = True

    return installed_any
