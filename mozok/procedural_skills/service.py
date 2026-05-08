from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord
from mozok.memory.policy import fresh_default_memory_policy
from mozok.procedural_skills.models import AgentProceduralSkillRecord
from mozok.schemas.procedural_skills import (
    AgentProceduralSkillPatch,
    AgentProceduralSkillRead,
    AgentProceduralSkillUpsert,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_key(value: str, fallback: str = "item") -> str:
    clean = " ".join(str(value or "").strip().split())
    return clean or fallback


def _compact(value: Any, max_chars: int = 240) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _trigger_text(trigger: dict[str, Any]) -> str:
    if not trigger:
        return ""
    if trigger.get("when"):
        return _compact(trigger.get("when"), 220)
    if trigger.get("keywords"):
        keywords = trigger.get("keywords")
        if isinstance(keywords, list):
            return "keywords: " + ", ".join(str(item) for item in keywords[:8])
    return _compact(trigger, 220)


def _procedure_text(procedure: list[Any]) -> str:
    if not procedure:
        return ""
    steps: list[str] = []
    for item in procedure[:6]:
        if isinstance(item, dict):
            text = item.get("description") or item.get("step") or item.get("text") or item
        else:
            text = item
        steps.append(_compact(text, 160))
    return "; ".join(step for step in steps if step)


def _example_text(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return ""
    first = examples[0] or {}
    good = first.get("good_response") or first.get("example") or first.get("response")
    situation = first.get("situation")
    if good and situation:
        return f"example: if {situation}, good response: {good}"
    if good:
        return f"example good response: {good}"
    return _compact(first, 220)


def format_procedural_skill_for_prompt_line(skill: AgentProceduralSkillRecord | AgentProceduralSkillRead | Any) -> str:
    """Format one procedural skill as a compact prompt/debug line."""

    skill_key = _clean_key(getattr(skill, "skill_key", "skill"), "skill")
    title = _clean_key(getattr(skill, "title", "") or skill_key, skill_key)
    skill_type = _clean_key(getattr(skill, "skill_type", "general"), "general")
    status = _clean_key(getattr(skill, "status", "active"), "active")
    priority = getattr(skill, "priority", 0)
    description = _compact(getattr(skill, "description", ""), 260)

    trigger = getattr(skill, "trigger", None)
    if trigger is None:
        trigger = getattr(skill, "trigger_json", None)
    trigger = dict(trigger or {})

    procedure = getattr(skill, "procedure", None)
    if procedure is None:
        procedure = getattr(skill, "procedure_json", None)
    procedure = list(procedure or [])

    examples = getattr(skill, "examples", None)
    if examples is None:
        examples = getattr(skill, "examples_json", None)
    examples = list(examples or [])

    notes = _compact(getattr(skill, "notes", ""), 220)

    bits: list[str] = [f"{title} (key={skill_key}, type={skill_type}, status={status}, priority={priority})"]
    if description:
        bits.append(f"description: {description}")
    trig = _trigger_text(trigger)
    if trig:
        bits.append(f"trigger: {trig}")
    proc = _procedure_text(procedure)
    if proc:
        bits.append(f"procedure: {proc}")
    example = _example_text(examples)
    if example:
        bits.append(_compact(example, 260))
    if notes:
        bits.append(f"notes: {notes}")

    return "- " + " | ".join(bits)


class ProceduralSkillService:
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

    def upsert(self, data: AgentProceduralSkillUpsert) -> AgentProceduralSkillRecord:
        agent_id = _clean_key(data.agent_id, "default_agent")
        skill_key = _clean_key(data.skill_key, "skill")
        self._ensure_agent(agent_id)

        record = (
            self.db.query(AgentProceduralSkillRecord)
            .filter(
                AgentProceduralSkillRecord.agent_id == agent_id,
                AgentProceduralSkillRecord.skill_key == skill_key,
            )
            .one_or_none()
        )

        now = utc_now()
        if record is None:
            record = AgentProceduralSkillRecord(
                agent_id=agent_id,
                skill_key=skill_key,
                created_at=now,
            )
            self.db.add(record)

        record.title = data.title.strip() or skill_key
        record.skill_type = data.skill_type.strip() or "general"
        record.status = data.status.strip() or "active"
        record.priority = int(data.priority or 0)
        record.description = data.description.strip()
        record.trigger_json = dict(data.trigger or {})
        record.procedure_json = list(data.procedure or [])
        record.examples_json = list(data.examples or [])
        record.related_goal_keys_json = [str(item) for item in data.related_goal_keys]
        record.related_entity_ids_json = [str(item) for item in data.related_entity_ids]
        record.related_lorebook_keys_json = [str(item) for item in data.related_lorebook_keys]
        record.notes = data.notes.strip()
        record.metadata_json = dict(data.metadata or {})
        record.active = True
        record.updated_at = now

        self.db.commit()
        self.db.refresh(record)
        return record

    def patch(self, skill_id: int, data: AgentProceduralSkillPatch) -> AgentProceduralSkillRecord | None:
        record = self.db.get(AgentProceduralSkillRecord, int(skill_id))
        if record is None:
            return None

        if data.title is not None:
            record.title = data.title.strip() or record.skill_key
        if data.skill_type is not None:
            record.skill_type = data.skill_type.strip() or "general"
        if data.status is not None:
            record.status = data.status.strip() or "active"
        if data.priority is not None:
            record.priority = int(data.priority)
        if data.description is not None:
            record.description = data.description.strip()
        if data.trigger is not None:
            record.trigger_json = dict(data.trigger or {})
        if data.procedure is not None:
            record.procedure_json = list(data.procedure or [])
        if data.examples is not None:
            record.examples_json = list(data.examples or [])
        if data.related_goal_keys is not None:
            record.related_goal_keys_json = [str(item) for item in data.related_goal_keys]
        if data.related_entity_ids is not None:
            record.related_entity_ids_json = [str(item) for item in data.related_entity_ids]
        if data.related_lorebook_keys is not None:
            record.related_lorebook_keys_json = [str(item) for item in data.related_lorebook_keys]
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

    def soft_delete(self, skill_id: int) -> bool:
        record = self.db.get(AgentProceduralSkillRecord, int(skill_id))
        if record is None:
            return False
        record.active = False
        record.updated_at = utc_now()
        self.db.commit()
        return True

    def list_skills(
        self,
        agent_id: str,
        skill_type: str | None = None,
        status: str | None = "active",
        include_inactive: bool = False,
        limit: int = 50,
    ) -> list[AgentProceduralSkillRecord]:
        query = self.db.query(AgentProceduralSkillRecord).filter(
            AgentProceduralSkillRecord.agent_id == _clean_key(agent_id, "default_agent")
        )
        if not include_inactive:
            query = query.filter(AgentProceduralSkillRecord.active == True)  # noqa: E712
        if skill_type:
            query = query.filter(AgentProceduralSkillRecord.skill_type == _clean_key(skill_type, "general"))
        if status:
            query = query.filter(AgentProceduralSkillRecord.status == _clean_key(status, "active"))

        return (
            query.order_by(AgentProceduralSkillRecord.priority.desc(), AgentProceduralSkillRecord.updated_at.desc())
            .limit(max(1, min(int(limit), 200)))
            .all()
        )

    def format_context_lines(
        self,
        agent_id: str,
        skill_type: str | None = None,
        status: str | None = "active",
        limit: int = 10,
    ) -> list[str]:
        records = self.list_skills(
            agent_id=agent_id,
            skill_type=skill_type,
            status=status,
            include_inactive=False,
            limit=limit,
        )
        return [format_procedural_skill_for_prompt_line(record) for record in records]


def reads_from_records(records: Iterable[AgentProceduralSkillRecord]) -> list[AgentProceduralSkillRead]:
    return [AgentProceduralSkillRead.from_record(record) for record in records]
