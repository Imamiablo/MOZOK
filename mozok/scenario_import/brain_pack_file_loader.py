"""Safe local brain-pack file loading helpers.

This module is intentionally small and dependency-light. It lets the API import
brain packs by a *safe pack name* from data/brain_packs without allowing arbitrary
filesystem paths.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

try:  # YAML stays optional; JSON works without PyYAML.
    import yaml  # type: ignore
except Exception:  # pragma: no cover - environment-dependent optional dependency.
    yaml = None  # type: ignore


DEFAULT_BRAIN_PACKS_DIR = Path("data") / "brain_packs"
_ALLOWED_SUFFIXES = (".json", ".yaml", ".yml")
_SAFE_PACK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class BrainPackNameError(ValueError):
    """Raised when a requested brain-pack name is unsafe or malformed."""


class BrainPackNotFoundError(FileNotFoundError):
    """Raised when no matching brain-pack file exists in data/brain_packs."""


class BrainPackLoadError(ValueError):
    """Raised when a found brain-pack file cannot be parsed into a dict."""


def normalise_brain_pack_name(pack_name: str) -> str:
    """Validate and normalise a user-provided brain-pack name.

    Accepted examples:
    - cyberpunk_demo_brain_pack
    - cyberpunk_demo_brain_pack.json
    - demo-pack.v1

    Rejected examples:
    - ../secrets
    - C:/Users/me/file.json
    - nested/folder/pack
    - pack\\name
    - .env
    """

    name = str(pack_name or "").strip()
    if not name:
        raise BrainPackNameError("pack_name is required.")

    if any(part in name for part in ("/", "\\", ":")):
        raise BrainPackNameError(
            "pack_name must be a simple file name, not a path. Use names like 'cyberpunk_demo_brain_pack'."
        )

    if ".." in name:
        raise BrainPackNameError("pack_name must not contain '..'.")

    if not _SAFE_PACK_NAME_RE.fullmatch(name):
        raise BrainPackNameError(
            "pack_name may only contain letters, numbers, underscores, hyphens, and dots, and must start with a letter or number."
        )

    suffix = Path(name).suffix.lower()
    if suffix and suffix not in _ALLOWED_SUFFIXES:
        raise BrainPackNameError("pack_name extension must be .json, .yaml, or .yml if an extension is provided.")

    return name


def candidate_brain_pack_paths(pack_name: str, *, base_dir: Path | str = DEFAULT_BRAIN_PACKS_DIR) -> list[Path]:
    """Return safe candidate paths inside the configured brain-packs directory."""

    safe_name = normalise_brain_pack_name(pack_name)
    root = Path(base_dir)
    suffix = Path(safe_name).suffix.lower()

    if suffix in _ALLOWED_SUFFIXES:
        return [root / safe_name]

    return [root / f"{safe_name}{suffix}" for suffix in _ALLOWED_SUFFIXES]


def find_brain_pack_file(pack_name: str, *, base_dir: Path | str = DEFAULT_BRAIN_PACKS_DIR) -> Path:
    """Find a brain-pack file by safe name inside data/brain_packs."""

    candidates = candidate_brain_pack_paths(pack_name, base_dir=base_dir)
    for path in candidates:
        if path.is_file():
            return path

    searched = ", ".join(str(path) for path in candidates)
    raise BrainPackNotFoundError(f"Brain pack '{pack_name}' was not found. Searched: {searched}")


def load_brain_pack_file(path: Path) -> dict[str, Any]:
    """Load a brain-pack dict from a known-safe JSON/YAML file path."""

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")

    try:
        if suffix == ".json":
            loaded = json.loads(text)
        elif suffix in {".yaml", ".yml"}:
            if yaml is None:
                raise BrainPackLoadError("PyYAML is not installed, so YAML brain packs cannot be loaded.")
            loaded = yaml.safe_load(text)  # type: ignore[union-attr]
        else:
            raise BrainPackLoadError(f"Unsupported brain-pack extension: {suffix}")
    except BrainPackLoadError:
        raise
    except Exception as exc:  # noqa: BLE001 - converted to a clean API error by callers.
        raise BrainPackLoadError(f"Failed to parse brain pack '{path}': {exc}") from exc

    if not isinstance(loaded, Mapping):
        raise BrainPackLoadError(f"Brain pack '{path}' must contain a JSON/YAML object at the top level.")

    return dict(loaded)


def load_brain_pack_by_name(
    pack_name: str,
    *,
    base_dir: Path | str = DEFAULT_BRAIN_PACKS_DIR,
) -> tuple[dict[str, Any], Path]:
    """Load a brain pack by safe name from data/brain_packs.

    Returns `(pack_dict, path_used)` so API responses can show which local file
    was selected.
    """

    path = find_brain_pack_file(pack_name, base_dir=base_dir)
    return load_brain_pack_file(path), path
