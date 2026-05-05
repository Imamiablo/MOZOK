from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord
from mozok.entity_state.models import AgentEntityStateRecord
from mozok.memory.policy import fresh_default_memory_policy
from mozok.schemas.entity_state import EntityStatePatch, EntityStateRead, EntityStateUpsert


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_key(value: str, fallback: str = "entity") -> str:
    clean = " ".join(str(value or "").strip().split())
    return clean or fallback


def format_entity_state_for_prompt_line(state: AgentEntityStateRecord | EntityStateRead | Any) -> str:
    """Format one entity-state record as a compact prompt/debug line.

    Kept deliberately simple and deterministic; no LLM needed.
    """

    entity_name = _clean_key(getattr(state, "entity_name", "") or getattr(state, "entity_id", "entity"), "entity")
    entity_id = _clean_key(getattr(state, "entity_id", ""), entity_name)
    state_kind = _clean_key(getattr(state, "state_kind", "entity_state"), "entity_state")
    role = _clean_key(getattr(state, "role", ""), "")
    entity_type = _clean_key(getattr(state, "entity_type", "entity"), "entity")

    attributes = getattr(state, "attributes", None)
    if attributes is None:
        attributes = getattr(state, "attributes_json", None)
    attributes = dict(attributes or {})

    notes = _clean_key(getattr(state, "notes", ""), "")

    bits: list[str] = [f"{entity_name} ({entity_id})", f"kind={state_kind}", f"type={entity_type}"]
    if role:
        bits.append(f"role={role}")

    if attributes:
        # Keep prompt lines short: stable sorted keys, compact values.
        attr_bits = []
        for key in sorted(attributes.keys())[:8]:
            value = attributes[key]
            if isinstance(value, (list, tuple)):
                value_text = ", ".join(str(v) for v in value[:5])
            elif isinstance(value, dict):
                value_text = "{" + ", ".join(f"{k}: {v}" for k, v in list(value.items())[:5]) + "}"
            else:
                value_text = str(value)
            attr_bits.append(f"{key}={value_text}")
        bits.append("attributes: " + "; ".join(attr_bits))

    if notes:
        bits.append(f"notes: {notes[:260]}")

    return "- " + " | ".join(bits)


class EntityStateService:
    """CRUD/service layer for agent entity states.

    This is deliberately separate from MemoryService. Entity state is structured
    state about a subject, not a raw/episodic/semantic/core memory fragment.
    """

    def __init__(self, db: Session):
        self.db = db

    def _ensure_agent(self, agent_id: str) -> AgentRecord:
        clean_agent_id = _clean_key(agent_id, "default_agent")
        agent = self.db.get(AgentRecord, clean_agent_id)
        if agent is not None:
            return agent

        agent = AgentRecord(
            id=clean_agent_id,
            name=clean_agent_id,
            description="Default Mozok agent.",
            personality="Helpful, curious, and remembers relevant past events.",
            system_prompt="Use memories when relevant. Do not invent memories.",
            state_json={},
            metadata_json={
                "memory_policy": fresh_default_memory_policy(),
                "memory_maintenance": {},
            },
        )
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def upsert(self, data: EntityStateUpsert) -> AgentEntityStateRecord:
        agent_id = _clean_key(data.agent_id, "default_agent")
        entity_id = _clean_key(data.entity_id, "entity")
        state_kind = _clean_key(data.state_kind, "entity_state")
        self._ensure_agent(agent_id)

        record = (
            self.db.query(AgentEntityStateRecord)
            .filter(
                AgentEntityStateRecord.agent_id == agent_id,
                AgentEntityStateRecord.entity_id == entity_id,
                AgentEntityStateRecord.state_kind == state_kind,
            )
            .one_or_none()
        )

        now = utc_now()
        if record is None:
            record = AgentEntityStateRecord(
                agent_id=agent_id,
                entity_id=entity_id,
                state_kind=state_kind,
                created_at=now,
            )
            self.db.add(record)

        record.entity_name = data.entity_name.strip() or entity_id
        record.entity_type = data.entity_type.strip() or "entity"
        record.role = data.role.strip()
        record.attributes_json = dict(data.attributes or {})
        record.notes = data.notes.strip()
        record.metadata_json = dict(data.metadata or {})
        record.active = True
        record.updated_at = now

        self.db.commit()
        self.db.refresh(record)
        return record

    def patch(self, state_id: int, data: EntityStatePatch) -> AgentEntityStateRecord | None:
        record = self.db.get(AgentEntityStateRecord, int(state_id))
        if record is None:
            return None

        if data.entity_name is not None:
            record.entity_name = data.entity_name.strip() or record.entity_id
        if data.entity_type is not None:
            record.entity_type = data.entity_type.strip() or "entity"
        if data.role is not None:
            record.role = data.role.strip()
        if data.attributes is not None:
            record.attributes_json = dict(data.attributes or {})
        if data.notes is not None:
            record.notes = data.notes.strip()
        if data.metadata is not None:
            record.metadata_json = dict(data.metadata or {})
        if data.active is not None:
            record.active = bool(data.active)

        record.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_states(
        self,
        agent_id: str,
        state_kind: str | None = None,
        entity_id: str | None = None,
        include_inactive: bool = False,
        limit: int = 50,
    ) -> list[AgentEntityStateRecord]:
        query = self.db.query(AgentEntityStateRecord).filter(
            AgentEntityStateRecord.agent_id == _clean_key(agent_id, "default_agent")
        )
        if not include_inactive:
            query = query.filter(AgentEntityStateRecord.active == True)  # noqa: E712
        if state_kind:
            query = query.filter(AgentEntityStateRecord.state_kind == _clean_key(state_kind, "entity_state"))
        if entity_id:
            query = query.filter(AgentEntityStateRecord.entity_id == _clean_key(entity_id, "entity"))

        return (
            query.order_by(AgentEntityStateRecord.state_kind.asc(), AgentEntityStateRecord.updated_at.desc())
            .limit(max(1, min(int(limit), 200)))
            .all()
        )

    def soft_delete(self, state_id: int) -> bool:
        record = self.db.get(AgentEntityStateRecord, int(state_id))
        if record is None:
            return False
        record.active = False
        record.updated_at = utc_now()
        self.db.commit()
        return True

    def format_context_lines(
        self,
        agent_id: str,
        state_kind: str | None = None,
        entity_id: str | None = None,
        limit: int = 10,
    ) -> list[str]:
        states = self.list_states(
            agent_id=agent_id,
            state_kind=state_kind,
            entity_id=entity_id,
            include_inactive=False,
            limit=limit,
        )
        return [format_entity_state_for_prompt_line(state) for state in states]


def reads_from_records(records: Iterable[AgentEntityStateRecord]) -> list[EntityStateRead]:
    return [EntityStateRead.from_record(record) for record in records]
