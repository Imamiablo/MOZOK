from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord
from mozok.knowledge_relations.models import KnowledgeRelationRecord
from mozok.memory.policy import fresh_default_memory_policy
from mozok.schemas.knowledge_relations import KnowledgeRelationPatch, KnowledgeRelationRead, KnowledgeRelationUpsert


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_key(value: str, fallback: str = "item") -> str:
    clean = " ".join(str(value or "").strip().split())
    return clean or fallback


def _clean_text(value: str, max_chars: int | None = None) -> str:
    clean = " ".join(str(value or "").strip().split())
    if max_chars is not None and len(clean) > max_chars:
        return clean[: max_chars - 3] + "..."
    return clean


def _clamp_unit(value: float | int | None, fallback: float = 1.0) -> float:
    try:
        number = float(fallback if value is None else value)
    except (TypeError, ValueError):
        number = float(fallback)
    return max(0.0, min(1.0, number))


def format_knowledge_relation_for_prompt_line(relation: KnowledgeRelationRecord | KnowledgeRelationRead | Any) -> str:
    """Format one relation edge as a compact prompt/debug line."""

    source_type = _clean_key(getattr(relation, "source_type", "source"), "source")
    source_id = _clean_key(getattr(relation, "source_id", ""), "unknown")
    relation_type = _clean_key(getattr(relation, "relation_type", "related_to"), "related_to")
    target_type = _clean_key(getattr(relation, "target_type", "target"), "target")
    target_id = _clean_key(getattr(relation, "target_id", ""), "unknown")
    strength = _clamp_unit(getattr(relation, "strength", 1.0), 1.0)
    confidence = _clamp_unit(getattr(relation, "confidence", 1.0), 1.0)
    description = _clean_text(getattr(relation, "description", ""), 260)

    line = (
        f"- {source_type}:{source_id} {relation_type} {target_type}:{target_id} "
        f"| strength={strength:.2f} confidence={confidence:.2f}"
    )
    if description:
        line += f" | {description}"
    return line


class KnowledgeRelationService:
    """CRUD/service layer for generic knowledge graph edges."""

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

    def upsert(self, data: KnowledgeRelationUpsert) -> KnowledgeRelationRecord:
        agent_id = _clean_key(data.agent_id, "default_agent")
        world_id = _clean_key(data.world_id, "default")
        source_type = _clean_key(data.source_type, "source")
        source_id = _clean_key(data.source_id, "unknown")
        relation_type = _clean_key(data.relation_type, "related_to")
        target_type = _clean_key(data.target_type, "target")
        target_id = _clean_key(data.target_id, "unknown")
        self._ensure_agent(agent_id)

        record = (
            self.db.query(KnowledgeRelationRecord)
            .filter(
                KnowledgeRelationRecord.agent_id == agent_id,
                KnowledgeRelationRecord.world_id == world_id,
                KnowledgeRelationRecord.source_type == source_type,
                KnowledgeRelationRecord.source_id == source_id,
                KnowledgeRelationRecord.relation_type == relation_type,
                KnowledgeRelationRecord.target_type == target_type,
                KnowledgeRelationRecord.target_id == target_id,
            )
            .one_or_none()
        )

        now = utc_now()
        if record is None:
            record = KnowledgeRelationRecord(
                agent_id=agent_id,
                world_id=world_id,
                source_type=source_type,
                source_id=source_id,
                relation_type=relation_type,
                target_type=target_type,
                target_id=target_id,
                created_at=now,
            )
            self.db.add(record)

        record.strength = _clamp_unit(data.strength, 1.0)
        record.confidence = _clamp_unit(data.confidence, 1.0)
        record.description = data.description.strip()
        record.evidence_json = dict(data.evidence or {})
        record.metadata_json = dict(data.metadata or {})
        record.active = True
        record.updated_at = now

        self.db.commit()
        self.db.refresh(record)
        return record

    def patch(self, relation_id: int, data: KnowledgeRelationPatch) -> KnowledgeRelationRecord | None:
        record = self.db.get(KnowledgeRelationRecord, int(relation_id))
        if record is None:
            return None

        if data.strength is not None:
            record.strength = _clamp_unit(data.strength, record.strength)
        if data.confidence is not None:
            record.confidence = _clamp_unit(data.confidence, record.confidence)
        if data.description is not None:
            record.description = data.description.strip()
        if data.evidence is not None:
            record.evidence_json = dict(data.evidence or {})
        if data.metadata is not None:
            record.metadata_json = dict(data.metadata or {})
        if data.active is not None:
            record.active = bool(data.active)

        record.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(record)
        return record

    def soft_delete(self, relation_id: int) -> bool:
        record = self.db.get(KnowledgeRelationRecord, int(relation_id))
        if record is None:
            return False
        record.active = False
        record.updated_at = utc_now()
        self.db.commit()
        return True

    def list_relations(
        self,
        agent_id: str,
        world_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        include_inactive: bool = False,
        limit: int = 50,
    ) -> list[KnowledgeRelationRecord]:
        query = self.db.query(KnowledgeRelationRecord).filter(
            KnowledgeRelationRecord.agent_id == _clean_key(agent_id, "default_agent")
        )
        if world_id:
            query = query.filter(KnowledgeRelationRecord.world_id == _clean_key(world_id, "default"))
        if not include_inactive:
            query = query.filter(KnowledgeRelationRecord.active == True)  # noqa: E712
        if source_type:
            query = query.filter(KnowledgeRelationRecord.source_type == _clean_key(source_type, "source"))
        if source_id:
            query = query.filter(KnowledgeRelationRecord.source_id == _clean_key(source_id, "unknown"))
        if target_type:
            query = query.filter(KnowledgeRelationRecord.target_type == _clean_key(target_type, "target"))
        if target_id:
            query = query.filter(KnowledgeRelationRecord.target_id == _clean_key(target_id, "unknown"))
        if relation_type:
            query = query.filter(KnowledgeRelationRecord.relation_type == _clean_key(relation_type, "related_to"))

        return (
            query.order_by(
                KnowledgeRelationRecord.strength.desc(),
                KnowledgeRelationRecord.confidence.desc(),
                KnowledgeRelationRecord.updated_at.desc(),
            )
            .limit(max(1, min(int(limit), 200)))
            .all()
        )

    def format_context_lines(
        self,
        agent_id: str,
        world_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 10,
    ) -> list[str]:
        records = self.list_relations(
            agent_id=agent_id,
            world_id=world_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            relation_type=relation_type,
            include_inactive=False,
            limit=limit,
        )
        return [format_knowledge_relation_for_prompt_line(record) for record in records]


def reads_from_records(records: Iterable[KnowledgeRelationRecord]) -> list[KnowledgeRelationRead]:
    return [KnowledgeRelationRead.from_record(record) for record in records]
