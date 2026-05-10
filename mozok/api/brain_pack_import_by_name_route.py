"""FastAPI route for importing local brain packs by safe pack name.

This route deliberately does not import a concrete scenario-import service class
at module import time. MOZOK's scenario importer class name changed during rapid
patching, so the endpoint discovers a compatible importer dynamically when the
request is executed.
"""

from __future__ import annotations

import inspect
from importlib import import_module
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.scenario_import.brain_pack_file_loader import (
    BrainPackLoadError,
    BrainPackNameError,
    BrainPackNotFoundError,
    load_brain_pack_by_name,
)
from mozok.schemas.brain_pack_import_by_name import BrainPackImportByNameRequest


router = APIRouter(tags=["brain-packs"])

_IMPORT_METHOD_NAMES: tuple[str, ...] = (
    "import_pack",
    "import_brain_pack",
    "import_scenario_pack",
    "import_scenario",
)

_PREFERRED_SERVICE_CLASS_NAMES: tuple[str, ...] = (
    "ScenarioImportService",
    "BrainPackImportService",
    "BrainPackImporter",
    "ScenarioImporter",
    "ScenarioImportManager",
)


def _has_import_method(obj: Any) -> bool:
    return any(callable(getattr(obj, name, None)) for name in _IMPORT_METHOD_NAMES)


def _instantiate_service(service_cls: type[Any], db: Session) -> Any:
    """Instantiate a service class using common MOZOK constructor styles."""

    attempts: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...] = (
        ((db,), {}),
        ((), {"db": db}),
        ((), {"session": db}),
        ((), {"db_session": db}),
        ((), {}),
    )

    last_exc: Exception | None = None
    for args, kwargs in attempts:
        try:
            return service_cls(*args, **kwargs)
        except TypeError as exc:
            last_exc = exc
            continue

    raise TypeError(f"Could not instantiate {service_cls.__name__}: {last_exc}")


def _discover_scenario_import_service(db: Session) -> Any:
    """Return a scenario importer service instance or module-level importer.

    This keeps `/brain-packs/import-by-name` compatible even if the scenario
    importer class is called `BrainPackImportService` instead of
    `ScenarioImportService`.
    """

    module = import_module("mozok.scenario_import.service")

    # 1) Preferred class names first, if present.
    for class_name in _PREFERRED_SERVICE_CLASS_NAMES:
        candidate = getattr(module, class_name, None)
        if isinstance(candidate, type) and _has_import_method(candidate):
            return _instantiate_service(candidate, db)

    # 2) Any class in the service module with a compatible import method.
    for candidate in vars(module).values():
        if isinstance(candidate, type) and candidate.__module__ == module.__name__ and _has_import_method(candidate):
            return _instantiate_service(candidate, db)

    # 3) Module-level function fallback.
    if _has_import_method(module):
        return module

    raise LookupError(
        "Could not find a scenario brain-pack importer in mozok.scenario_import.service. "
        "Expected a class or module function with one of: "
        + ", ".join(_IMPORT_METHOD_NAMES)
    )


def _get_import_method(importer: Any) -> Callable[..., Any]:
    for method_name in _IMPORT_METHOD_NAMES:
        method = getattr(importer, method_name, None)
        if callable(method):
            return method
    raise LookupError("Scenario importer has no compatible import method.")


def _call_import_method(
    method: Callable[..., Any],
    pack: dict[str, Any],
    *,
    dry_run: bool,
    validate_relations: bool,
    atomic: bool,
) -> Any:
    """Call the importer while respecting its current method signature."""

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        # Last-resort compatibility path.
        return method(pack, dry_run=dry_run, validate_relations=validate_relations, atomic=atomic)

    params = signature.parameters
    accepts_var_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())

    kwargs: dict[str, Any] = {}
    for name, value in {
        "dry_run": dry_run,
        "validate_relations": validate_relations,
        "atomic": atomic,
    }.items():
        if accepts_var_kwargs or name in params:
            kwargs[name] = value

    pack_param_names = ("pack", "brain_pack", "scenario_pack", "data", "payload", "document")
    for name in pack_param_names:
        if name in params and params[name].kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            kwargs[name] = pack
            return method(**kwargs)

    # Bound methods normally expose `pack` as the first positional argument.
    return method(pack, **kwargs)


@router.post("/brain-packs/import-by-name")
def import_brain_pack_by_name(
    request: BrainPackImportByNameRequest,
    db: Session = Depends(get_db),
):
    """Import a local brain pack from `data/brain_packs/` by safe file name.

    This endpoint is intentionally separate from `/brain-packs/import`:
    - `/brain-packs/import` accepts a full brain-pack JSON object.
    - `/brain-packs/import-by-name` loads a local `.json/.yaml/.yml` file by safe name.
    """

    try:
        pack, loaded_from = load_brain_pack_by_name(request.pack_name)
    except BrainPackNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BrainPackNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BrainPackLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        importer = _discover_scenario_import_service(db)
        method = _get_import_method(importer)
        result = _call_import_method(
            method,
            pack,
            dry_run=request.dry_run,
            validate_relations=request.validate_relations,
            atomic=request.atomic,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - expose a clean API error instead of a server traceback.
        raise HTTPException(status_code=500, detail=f"Brain pack import failed: {exc}") from exc

    if isinstance(result, dict):
        result.setdefault("brain_pack_file", str(loaded_from))
        result.setdefault("pack_name", request.pack_name)
        return result

    return {
        "pack_name": request.pack_name,
        "brain_pack_file": str(loaded_from),
        "result": result,
    }
