from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord, MemoryRecord
from mozok.entity_state.models import AgentEntityStateRecord
from mozok.goals.models import AgentGoalRecord
from mozok.knowledge_relations.models import KnowledgeRelationRecord
from mozok.lorebook.models import LorebookEntryRecord
from mozok.procedural_skills.models import AgentProceduralSkillRecord
from mozok.memory.policy import fresh_default_memory_policy
from mozok.schemas.knowledge_relations import (
    KnowledgeNodeResolution,
    KnowledgeRelationPatch,
    KnowledgeRelationRead,
    KnowledgeRelationUpsert,
)


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


def _try_int(value: str | int | None) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _confidence_label(value: float | int | None) -> str:
    confidence = _clamp_unit(value, 1.0)
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.45:
        return "medium"
    return "low"


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
        f'- {source_type}:"{source_id}" {relation_type} {target_type}:"{target_id}" '
        f"| strength={strength:.2f} confidence={confidence:.2f} ({_confidence_label(confidence)})"
    )
    if description:
        line += f" | reason: {description}"
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

        if data.validate_nodes:
            self.validate_edge_nodes(
                agent_id=agent_id,
                world_id=world_id,
                source_type=source_type,
                source_id=source_id,
                target_type=target_type,
                target_id=target_id,
            )

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

    def list_neighborhood(
        self,
        agent_id: str,
        node_type: str,
        node_id: str,
        world_id: str | None = None,
        direction: str = "both",
        include_inactive: bool = False,
        limit: int = 50,
    ) -> list[KnowledgeRelationRecord]:
        safe_direction = _clean_key(direction, "both").lower()
        safe_type = _clean_key(node_type, "node")
        safe_id = _clean_key(node_id, "unknown")

        query = self.db.query(KnowledgeRelationRecord).filter(
            KnowledgeRelationRecord.agent_id == _clean_key(agent_id, "default_agent")
        )
        if world_id:
            query = query.filter(KnowledgeRelationRecord.world_id == _clean_key(world_id, "default"))
        if not include_inactive:
            query = query.filter(KnowledgeRelationRecord.active == True)  # noqa: E712

        outgoing = and_(
            KnowledgeRelationRecord.source_type == safe_type,
            KnowledgeRelationRecord.source_id == safe_id,
        )
        incoming = and_(
            KnowledgeRelationRecord.target_type == safe_type,
            KnowledgeRelationRecord.target_id == safe_id,
        )
        if safe_direction == "outgoing":
            query = query.filter(outgoing)
        elif safe_direction == "incoming":
            query = query.filter(incoming)
        else:
            query = query.filter(or_(outgoing, incoming))

        return (
            query.order_by(
                KnowledgeRelationRecord.strength.desc(),
                KnowledgeRelationRecord.confidence.desc(),
                KnowledgeRelationRecord.updated_at.desc(),
            )
            .limit(max(1, min(int(limit), 200)))
            .all()
        )

    def list_related_to_nodes(
        self,
        agent_id: str,
        node_refs: Iterable[tuple[str, str]],
        world_id: str | None = None,
        exclude_ids: set[int] | None = None,
        limit: int = 10,
    ) -> list[KnowledgeRelationRecord]:
        """Return one-hop relations touching any selected context node.

        This is deliberately one-hop only. Multi-hop traversal belongs to a later
        budget-aware graph retrieval system.
        """

        cleaned_refs = []
        seen_refs = set()
        for node_type, node_id in node_refs:
            safe_type = _clean_key(node_type, "node")
            safe_id = _clean_key(node_id, "unknown")
            key = (safe_type, safe_id)
            if key not in seen_refs:
                seen_refs.add(key)
                cleaned_refs.append(key)

        if not cleaned_refs:
            return []

        predicates = []
        for node_type, node_id in cleaned_refs[:80]:
            predicates.append(
                and_(
                    KnowledgeRelationRecord.source_type == node_type,
                    KnowledgeRelationRecord.source_id == node_id,
                )
            )
            predicates.append(
                and_(
                    KnowledgeRelationRecord.target_type == node_type,
                    KnowledgeRelationRecord.target_id == node_id,
                )
            )

        query = self.db.query(KnowledgeRelationRecord).filter(
            KnowledgeRelationRecord.agent_id == _clean_key(agent_id, "default_agent"),
            KnowledgeRelationRecord.active == True,  # noqa: E712
            or_(*predicates),
        )
        if world_id:
            query = query.filter(KnowledgeRelationRecord.world_id == _clean_key(world_id, "default"))
        if exclude_ids:
            query = query.filter(~KnowledgeRelationRecord.id.in_(set(exclude_ids)))

        return (
            query.order_by(
                KnowledgeRelationRecord.strength.desc(),
                KnowledgeRelationRecord.confidence.desc(),
                KnowledgeRelationRecord.updated_at.desc(),
            )
            .limit(max(1, min(int(limit), 100)))
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

    def validate_edge_nodes(
        self,
        agent_id: str,
        world_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
    ) -> None:
        source = self.resolve_node(agent_id=agent_id, world_id=world_id, node_type=source_type, node_id=source_id)
        target = self.resolve_node(agent_id=agent_id, world_id=world_id, node_type=target_type, node_id=target_id)
        missing = []
        if not source.found:
            missing.append(f"source {source_type}:{source_id}")
        if not target.found:
            missing.append(f"target {target_type}:{target_id}")
        if missing:
            raise ValueError("Knowledge relation node validation failed: " + ", ".join(missing))

    def resolve_relation(self, relation_id: int) -> tuple[KnowledgeRelationRecord | None, KnowledgeNodeResolution | None, KnowledgeNodeResolution | None]:
        relation = self.db.get(KnowledgeRelationRecord, int(relation_id))
        if relation is None:
            return None, None, None
        source = self.resolve_node(
            agent_id=relation.agent_id,
            world_id=relation.world_id,
            node_type=relation.source_type,
            node_id=relation.source_id,
        )
        target = self.resolve_node(
            agent_id=relation.agent_id,
            world_id=relation.world_id,
            node_type=relation.target_type,
            node_id=relation.target_id,
        )
        return relation, source, target

    def resolve_node(
        self,
        agent_id: str,
        world_id: str | None,
        node_type: str,
        node_id: str,
    ) -> KnowledgeNodeResolution:
        safe_type = _clean_key(node_type, "node")
        safe_id = _clean_key(node_id, "unknown")
        safe_agent_id = _clean_key(agent_id, "default_agent")
        safe_world_id = _clean_key(world_id or "default", "default")

        try:
            if safe_type == "goal":
                return self._resolve_goal(safe_agent_id, safe_id)
            if safe_type == "lorebook":
                return self._resolve_lorebook(safe_world_id, safe_id)
            if safe_type == "entity_state":
                return self._resolve_entity_state(safe_agent_id, safe_id)
            if safe_type == "memory":
                return self._resolve_memory(safe_agent_id, safe_id)
            if safe_type == "procedural_skill" or safe_type == "skill":
                return self._resolve_procedural_skill(safe_agent_id, safe_id)
            if safe_type == "agent":
                return self._resolve_agent(safe_id)
        except Exception as exc:  # defensive: debug resolution should not crash context building
            return KnowledgeNodeResolution(
                found=False,
                node_type=safe_type,
                node_id=safe_id,
                message=f"Resolution failed: {exc}",
            )

        return KnowledgeNodeResolution(
            found=True,
            node_type=safe_type,
            node_id=safe_id,
            title=safe_id,
            summary=f"Custom/unvalidated node type: {safe_type}",
            data={},
        )

    def _resolve_goal(self, agent_id: str, node_id: str) -> KnowledgeNodeResolution:
        record = None
        int_id = _try_int(node_id)
        if int_id is not None:
            record = self.db.get(AgentGoalRecord, int_id)
        if record is None:
            record = (
                self.db.query(AgentGoalRecord)
                .filter(
                    AgentGoalRecord.agent_id == agent_id,
                    AgentGoalRecord.goal_key == node_id,
                    AgentGoalRecord.active == True,  # noqa: E712
                )
                .one_or_none()
            )
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="goal", node_id=node_id, message="Goal not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="goal",
            node_id=node_id,
            title=record.title or record.goal_key,
            summary=_clean_text(record.description or record.notes or record.goal_key, 280),
            data={"id": record.id, "agent_id": record.agent_id, "goal_key": record.goal_key, "status": record.status, "priority": record.priority},
        )

    def _resolve_lorebook(self, world_id: str, node_id: str) -> KnowledgeNodeResolution:
        record = None
        int_id = _try_int(node_id)
        if int_id is not None:
            record = self.db.get(LorebookEntryRecord, int_id)
        if record is None:
            record = (
                self.db.query(LorebookEntryRecord)
                .filter(
                    LorebookEntryRecord.world_id == world_id,
                    LorebookEntryRecord.entry_key == node_id,
                    LorebookEntryRecord.is_active == True,  # noqa: E712
                )
                .one_or_none()
            )
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="lorebook", node_id=node_id, message="Lorebook entry not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="lorebook",
            node_id=node_id,
            title=record.title or record.entry_key,
            summary=_clean_text(record.content or "", 280),
            data={"id": record.id, "world_id": record.world_id, "entry_key": record.entry_key, "category": record.category, "visibility": record.visibility},
        )

    def _resolve_entity_state(self, agent_id: str, node_id: str) -> KnowledgeNodeResolution:
        record = None
        int_id = _try_int(node_id)
        if int_id is not None:
            record = self.db.get(AgentEntityStateRecord, int_id)
        if record is None:
            record = (
                self.db.query(AgentEntityStateRecord)
                .filter(
                    AgentEntityStateRecord.agent_id == agent_id,
                    AgentEntityStateRecord.entity_id == node_id,
                    AgentEntityStateRecord.active == True,  # noqa: E712
                )
                .order_by(AgentEntityStateRecord.updated_at.desc())
                .first()
            )
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="entity_state", node_id=node_id, message="EntityState not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="entity_state",
            node_id=node_id,
            title=record.entity_name or record.entity_id,
            summary=_clean_text(record.notes or str(record.attributes_json or {}), 280),
            data={"id": record.id, "agent_id": record.agent_id, "entity_id": record.entity_id, "state_kind": record.state_kind, "entity_type": record.entity_type},
        )

    def _resolve_procedural_skill(self, agent_id: str, node_id: str) -> KnowledgeNodeResolution:
        record = None
        int_id = _try_int(node_id)
        if int_id is not None:
            record = self.db.get(AgentProceduralSkillRecord, int_id)
        if record is None:
            record = (
                self.db.query(AgentProceduralSkillRecord)
                .filter(
                    AgentProceduralSkillRecord.agent_id == agent_id,
                    AgentProceduralSkillRecord.skill_key == node_id,
                    AgentProceduralSkillRecord.active == True,  # noqa: E712
                )
                .one_or_none()
            )
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="procedural_skill", node_id=node_id, message="Procedural skill not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="procedural_skill",
            node_id=node_id,
            title=record.title or record.skill_key,
            summary=_clean_text(record.description or record.notes or record.skill_key, 280),
            data={"id": record.id, "agent_id": record.agent_id, "skill_key": record.skill_key, "skill_type": record.skill_type, "status": record.status, "priority": record.priority},
        )

    def _resolve_memory(self, agent_id: str, node_id: str) -> KnowledgeNodeResolution:
        int_id = _try_int(node_id)
        if int_id is None:
            return KnowledgeNodeResolution(found=False, node_type="memory", node_id=node_id, message="Memory id must be numeric")
        record = self.db.get(MemoryRecord, int_id)
        if record is None or getattr(record, "agent_id", None) != agent_id or not getattr(record, "active", True):
            return KnowledgeNodeResolution(found=False, node_type="memory", node_id=node_id, message="Memory not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="memory",
            node_id=node_id,
            title=f"Memory {record.id}",
            summary=_clean_text(record.content or "", 280),
            data={"id": record.id, "agent_id": record.agent_id, "memory_type": record.memory_type, "importance": record.importance},
        )

    def _resolve_agent(self, node_id: str) -> KnowledgeNodeResolution:
        record = self.db.get(AgentRecord, node_id)
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="agent", node_id=node_id, message="Agent not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="agent",
            node_id=node_id,
            title=record.name or record.id,
            summary=_clean_text(record.description or record.personality or "", 280),
            data={"id": record.id, "name": record.name},
        )


def reads_from_records(records: Iterable[KnowledgeRelationRecord]) -> list[KnowledgeRelationRead]:
    return [KnowledgeRelationRead.from_record(record) for record in records]
