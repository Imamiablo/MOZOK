from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord
from mozok.goals.models import AgentGoalRecord
from mozok.memory.policy import fresh_default_memory_policy
from mozok.schemas.goals import AgentGoalPatch, AgentGoalRead, AgentGoalUpsert


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_key(value: str, fallback: str = "goal") -> str:
    clean = " ".join(str(value or "").strip().split())
    return clean or fallback


def _clean_list(values: Iterable[Any] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        clean = _clean_key(str(value), "")
        if clean:
            result.append(clean)
    return result


def _compact_text(text: str, max_chars: int = 240) -> str:
    clean = (text or "").replace("\n", " ").strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3] + "..."


def _format_plan_steps(plan_steps: list[dict[str, Any]], max_steps: int = 5) -> str:
    bits: list[str] = []
    for step in plan_steps[:max_steps]:
        if not isinstance(step, dict):
            bits.append(_compact_text(str(step), 80))
            continue

        status = _clean_key(str(step.get("status", "")), "")
        description = _compact_text(str(step.get("description") or step.get("title") or step.get("step_key") or ""), 100)
        step_key = _clean_key(str(step.get("step_key", "")), "")

        if description and status:
            bits.append(f"{description} [{status}]")
        elif description:
            bits.append(description)
        elif step_key and status:
            bits.append(f"{step_key} [{status}]")
        elif step_key:
            bits.append(step_key)

    return "; ".join(bit for bit in bits if bit)


def format_goal_for_prompt_line(goal: AgentGoalRecord | AgentGoalRead | Any) -> str:
    """Format one goal/plan as a compact prompt/debug line."""

    title = _clean_key(getattr(goal, "title", "") or getattr(goal, "goal_key", "goal"), "goal")
    goal_key = _clean_key(getattr(goal, "goal_key", ""), title)
    goal_type = _clean_key(getattr(goal, "goal_type", "general"), "general")
    status = _clean_key(getattr(goal, "status", "active"), "active")
    priority = getattr(goal, "priority", 0)

    description = _compact_text(getattr(goal, "description", ""), 260)
    notes = _compact_text(getattr(goal, "notes", ""), 220)

    success_criteria = getattr(goal, "success_criteria", None)
    if success_criteria is None:
        success_criteria = getattr(goal, "success_criteria_json", None)
    success_criteria = _clean_list(success_criteria)[:3]

    related_entity_ids = getattr(goal, "related_entity_ids", None)
    if related_entity_ids is None:
        related_entity_ids = getattr(goal, "related_entity_ids_json", None)
    related_entity_ids = _clean_list(related_entity_ids)[:5]

    related_lorebook_keys = getattr(goal, "related_lorebook_keys", None)
    if related_lorebook_keys is None:
        related_lorebook_keys = getattr(goal, "related_lorebook_keys_json", None)
    related_lorebook_keys = _clean_list(related_lorebook_keys)[:5]

    plan_steps = getattr(goal, "plan_steps", None)
    if plan_steps is None:
        plan_steps = getattr(goal, "plan_steps_json", None)
    plan_steps = list(plan_steps or [])

    bits: list[str] = [
        f"{title} (key={goal_key})",
        f"type={goal_type}",
        f"status={status}",
        f"priority={priority}",
    ]
    if related_entity_ids:
        bits.append("related_entities=" + ", ".join(related_entity_ids))
    if related_lorebook_keys:
        bits.append("related_lore=" + ", ".join(related_lorebook_keys))
    if description:
        bits.append(f"description: {description}")
    if success_criteria:
        bits.append("success: " + "; ".join(success_criteria))

    formatted_steps = _format_plan_steps(plan_steps)
    if formatted_steps:
        bits.append("plan: " + formatted_steps)

    if notes:
        bits.append(f"notes: {notes}")

    return "- " + " | ".join(bits)


class GoalService:
    """CRUD/service layer for agent goals/plans."""

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

    def upsert(self, data: AgentGoalUpsert) -> AgentGoalRecord:
        agent_id = _clean_key(data.agent_id, "default_agent")
        goal_key = _clean_key(data.goal_key, "goal")
        self._ensure_agent(agent_id)

        record = (
            self.db.query(AgentGoalRecord)
            .filter(
                AgentGoalRecord.agent_id == agent_id,
                AgentGoalRecord.goal_key == goal_key,
            )
            .one_or_none()
        )

        now = utc_now()
        if record is None:
            record = AgentGoalRecord(
                agent_id=agent_id,
                goal_key=goal_key,
                created_at=now,
            )
            self.db.add(record)

        record.title = data.title.strip() or goal_key
        record.goal_type = data.goal_type.strip() or "general"
        record.status = data.status.strip() or "active"
        record.priority = int(data.priority)
        record.description = data.description.strip()
        record.success_criteria_json = _clean_list(data.success_criteria)
        record.failure_conditions_json = _clean_list(data.failure_conditions)
        record.related_entity_ids_json = _clean_list(data.related_entity_ids)
        record.related_lorebook_keys_json = _clean_list(data.related_lorebook_keys)
        record.plan_steps_json = list(data.plan_steps or [])
        record.notes = data.notes.strip()
        record.metadata_json = dict(data.metadata or {})
        record.active = True
        record.updated_at = now

        self.db.commit()
        self.db.refresh(record)
        return record

    def patch(self, goal_id: int, data: AgentGoalPatch) -> AgentGoalRecord | None:
        record = self.db.get(AgentGoalRecord, int(goal_id))
        if record is None:
            return None

        if data.title is not None:
            record.title = data.title.strip() or record.goal_key
        if data.goal_type is not None:
            record.goal_type = data.goal_type.strip() or "general"
        if data.status is not None:
            record.status = data.status.strip() or "active"
        if data.priority is not None:
            record.priority = int(data.priority)
        if data.description is not None:
            record.description = data.description.strip()
        if data.success_criteria is not None:
            record.success_criteria_json = _clean_list(data.success_criteria)
        if data.failure_conditions is not None:
            record.failure_conditions_json = _clean_list(data.failure_conditions)
        if data.related_entity_ids is not None:
            record.related_entity_ids_json = _clean_list(data.related_entity_ids)
        if data.related_lorebook_keys is not None:
            record.related_lorebook_keys_json = _clean_list(data.related_lorebook_keys)
        if data.plan_steps is not None:
            record.plan_steps_json = list(data.plan_steps or [])
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

    def list_goals(
        self,
        agent_id: str,
        status: str | None = None,
        include_inactive: bool = False,
        limit: int = 50,
    ) -> list[AgentGoalRecord]:
        query = self.db.query(AgentGoalRecord).filter(
            AgentGoalRecord.agent_id == _clean_key(agent_id, "default_agent")
        )
        if not include_inactive:
            query = query.filter(AgentGoalRecord.active == True)  # noqa: E712
        if status:
            query = query.filter(AgentGoalRecord.status == _clean_key(status, "active"))

        return (
            query.order_by(AgentGoalRecord.priority.desc(), AgentGoalRecord.updated_at.desc())
            .limit(max(1, min(int(limit), 200)))
            .all()
        )

    def soft_delete(self, goal_id: int) -> bool:
        record = self.db.get(AgentGoalRecord, int(goal_id))
        if record is None:
            return False
        record.active = False
        record.updated_at = utc_now()
        self.db.commit()
        return True

    def format_context_lines(
        self,
        agent_id: str,
        status: str | None = None,
        limit: int = 10,
    ) -> list[str]:
        goals = self.list_goals(
            agent_id=agent_id,
            status=status,
            include_inactive=False,
            limit=limit,
        )
        return [format_goal_for_prompt_line(goal) for goal in goals]


def reads_from_records(records: Iterable[AgentGoalRecord]) -> list[AgentGoalRead]:
    return [AgentGoalRead.from_record(record) for record in records]
