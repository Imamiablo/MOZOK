"""Brain Pack memory import helpers.

This module deliberately keeps the memory import logic outside the main
ScenarioImportService so it can be tested independently and reused from CLI/API.

Goal:
- read `memories` entries from a brain pack;
- create real Memory records through MemoryService;
- let MemoryService handle embeddings + FAISS sync;
- support dry-run and exact-duplicate protection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


MEMORY_TYPE_ALIASES: dict[str, str] = {
    "fact": "semantic",
    "preference": "semantic",
    "knowledge": "semantic",
    "summary": "semantic",
    "event": "episodic",
    "episode": "episodic",
    "dialogue": "raw",
    "message": "raw",
    "chat": "raw",
    "profile": "core",
    "identity": "core",
}

VALID_MEMORY_TYPES = {"raw", "episodic", "semantic", "core"}


@dataclass(slots=True)
class MemoryImportItem:
    agent_id: str
    content: str
    memory_type: str = "semantic"
    importance: float = 0.5
    emotional_weight: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None


@dataclass(slots=True)
class MemoryImportResult:
    dry_run: bool
    seen: int = 0
    created: int = 0
    skipped_duplicates: int = 0
    skipped_invalid: int = 0
    created_ids: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    preview: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "seen": self.seen,
            "created": self.created,
            "skipped_duplicates": self.skipped_duplicates,
            "skipped_invalid": self.skipped_invalid,
            "created_ids": self.created_ids,
            "errors": self.errors,
            "preview": self.preview,
        }


def normalise_memory_type(value: Any) -> str:
    memory_type = str(value or "semantic").strip().lower()
    memory_type = MEMORY_TYPE_ALIASES.get(memory_type, memory_type)
    if memory_type not in VALID_MEMORY_TYPES:
        return "semantic"
    return memory_type


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def iter_memory_items(
    pack: Mapping[str, Any],
    *,
    default_agent_id: str | None = None,
) -> Iterable[MemoryImportItem]:
    """Yield normalised memory import items from a brain-pack dict.

    Supported item shapes:

    ```json
    {"agent_id": "npc_alice", "content": "Alice knows the old well.", "memory_type": "semantic"}
    ```

    or legacy-ish aliases:

    ```json
    {"agent": "npc_alice", "text": "...", "type": "fact"}
    ```
    """

    defaults = pack.get("defaults") or {}
    if not isinstance(defaults, Mapping):
        defaults = {}

    fallback_agent_id = (
        default_agent_id
        or defaults.get("agent_id")
        or pack.get("agent_id")
        or pack.get("default_agent_id")
    )

    raw_memories = pack.get("memories") or []
    if isinstance(raw_memories, Mapping):
        # Allows {"npc_alice": [{...}, {...}], "npc_bob": [...]}.
        expanded: list[dict[str, Any]] = []
        for agent_id, values in raw_memories.items():
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
                for value in values:
                    if isinstance(value, Mapping):
                        expanded.append({"agent_id": agent_id, **dict(value)})
                    else:
                        expanded.append({"agent_id": agent_id, "content": str(value)})
            elif isinstance(values, Mapping):
                expanded.append({"agent_id": agent_id, **dict(values)})
            elif values:
                expanded.append({"agent_id": agent_id, "content": str(values)})
        raw_memories = expanded

    if not isinstance(raw_memories, Sequence) or isinstance(raw_memories, (str, bytes, bytearray)):
        return

    for raw in raw_memories:
        if isinstance(raw, str):
            raw = {"content": raw}
        if not isinstance(raw, Mapping):
            continue

        content = raw.get("content") or raw.get("text") or raw.get("memory")
        agent_id = raw.get("agent_id") or raw.get("agent") or fallback_agent_id
        if not agent_id or not content:
            continue

        metadata = raw.get("metadata") or raw.get("meta") or {}
        if not isinstance(metadata, Mapping):
            metadata = {"raw_metadata": metadata}

        yield MemoryImportItem(
            agent_id=str(agent_id),
            content=str(content),
            memory_type=normalise_memory_type(raw.get("memory_type") or raw.get("type")),
            importance=_safe_float(raw.get("importance"), 0.5),
            emotional_weight=_safe_float(raw.get("emotional_weight"), 0.0),
            metadata=dict(metadata),
            session_id=(str(raw.get("session_id")) if raw.get("session_id") else None),
        )


class BrainPackMemoryImporter:
    """Imports brain-pack memories through the existing MemoryService.

    The importer is intentionally adapter-based: different previous MOZOK patches
    used slightly different service method names. It tries common method names and
    passes keyword arguments. That keeps this patch compatible with the current
    project without forcing another broad refactor.
    """

    def __init__(self, db: Any, memory_service: Any):
        self.db = db
        self.memory_service = memory_service

    def import_pack_memories(
        self,
        pack: Mapping[str, Any],
        *,
        default_agent_id: str | None = None,
        dry_run: bool = False,
        allow_duplicates: bool = False,
        source_label: str = "brain_pack_import",
    ) -> MemoryImportResult:
        result = MemoryImportResult(dry_run=dry_run)

        for item in iter_memory_items(pack, default_agent_id=default_agent_id):
            result.seen += 1

            if not item.agent_id or not item.content.strip():
                result.skipped_invalid += 1
                continue

            item.metadata = {
                "source": source_label,
                **item.metadata,
            }

            preview_row = {
                "agent_id": item.agent_id,
                "memory_type": item.memory_type,
                "content": item.content,
                "importance": item.importance,
                "emotional_weight": item.emotional_weight,
                "session_id": item.session_id,
                "metadata": item.metadata,
            }
            result.preview.append(preview_row)

            if not allow_duplicates and self._exact_duplicate_exists(item):
                result.skipped_duplicates += 1
                continue

            if dry_run:
                continue

            try:
                record = self._create_memory(item)
            except Exception as exc:  # noqa: BLE001 - import report should collect per-row failures.
                result.errors.append(f"{item.agent_id}: {exc}")
                continue

            result.created += 1
            result.created_ids.append(getattr(record, "id", None) or getattr(record, "memory_id", None))

        return result

    def _exact_duplicate_exists(self, item: MemoryImportItem) -> bool:
        """Best-effort exact duplicate check.

        This deliberately avoids semantic/embedding duplicate detection. Dedup V2
        is a separate roadmap item; this protects only against importing the exact
        same text for the same agent/type more than once.
        """

        if self.db is None:
            return False

        try:
            from mozok.db.models import MemoryRecord  # type: ignore
        except Exception:
            return False

        try:
            query = self.db.query(MemoryRecord).filter(
                MemoryRecord.agent_id == item.agent_id,
                MemoryRecord.content == item.content,
                MemoryRecord.memory_type == item.memory_type,
            )
            status_column = getattr(MemoryRecord, "status", None)
            if status_column is not None:
                query = query.filter(status_column != "deleted")
            return query.first() is not None
        except Exception:
            return False

    def _create_memory(self, item: MemoryImportItem) -> Any:
        kwargs = {
            "agent_id": item.agent_id,
            "content": item.content,
            "memory_type": item.memory_type,
            "importance": item.importance,
            "emotional_weight": item.emotional_weight,
            "metadata": item.metadata,
            "session_id": item.session_id,
        }

        # Prefer common service method names used by MOZOK patches.
        for method_name in ("add_memory", "create_memory", "store_memory", "remember"):
            method = getattr(self.memory_service, method_name, None)
            if method is None:
                continue
            try:
                return method(**kwargs)
            except TypeError:
                # Some older service methods may not accept session_id.
                kwargs_without_none = {k: v for k, v in kwargs.items() if v is not None}
                try:
                    return method(**kwargs_without_none)
                except TypeError:
                    kwargs_minimal = {
                        "agent_id": item.agent_id,
                        "content": item.content,
                        "memory_type": item.memory_type,
                        "importance": item.importance,
                        "emotional_weight": item.emotional_weight,
                        "metadata": item.metadata,
                    }
                    return method(**kwargs_minimal)

        raise AttributeError(
            "MemoryService does not expose add_memory/create_memory/store_memory/remember. "
            "Wire BrainPackMemoryImporter._create_memory to the local MemoryService API."
        )
