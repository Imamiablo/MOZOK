from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord
from mozok.memory.policy import fresh_default_memory_policy
from mozok.procedural_skills.models import AgentProceduralSkillRecord, AgentProceduralSkillUsageRecord
from mozok.schemas.procedural_skills import (
    AgentProceduralSkillPatch,
    AgentProceduralSkillRead,
    AgentProceduralSkillUpsert,
    ProceduralSkillEffectivenessStats,
    ProceduralSkillFromTemplateRequest,
    ProceduralSkillRelationSuggestion,
    ProceduralSkillRelationSuggestionsResponse,
    ProceduralSkillRelationSyncRequest,
    ProceduralSkillRelationSyncResponse,
    ProceduralSkillTemplateRead,
    ProceduralSkillUsageCreate,
    ProceduralSkillUsageRead,
    ProceduralSkillUsageResponse,
    ProceduralSkillSelectionDetail,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_key(value: str, fallback: str = "item") -> str:
    clean = " ".join(str(value or "").strip().split())
    return clean or fallback




def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())


def _as_clean_list(values: Iterable[Any] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result




SHARED_SKILL_AGENT_ID = "__shared__"


BUILTIN_SKILL_TEMPLATES: dict[str, dict[str, Any]] = {
    "careful_secret_deflection": {
        "title": "Careful secret deflection",
        "skill_type": "conversation",
        "description": "Avoid revealing restricted facts while still sounding natural and useful.",
        "trigger": {
            "when": "A user/player asks about secrets, forbidden places, private lore, or unsafe details.",
            "keywords": ["secret", "forbidden", "private", "restricted", "do not reveal"],
        },
        "procedure": [
            "Acknowledge the question calmly.",
            "Answer only with facts the agent is allowed to know.",
            "Use partial truth, uncertainty, or redirection instead of exposed restricted lore.",
            "Do not mention that hidden context exists.",
        ],
        "examples": [
            {
                "situation": "A player asks about a location the NPC should protect.",
                "good_response": "People avoid that place for a reason. I would not go there after dark.",
            }
        ],
        "notes": "Good for NPCs that must protect secrets without sounding robotic.",
        "metadata": {"template_kind": "conversation_safety"},
    },
    "step_by_step_tutor": {
        "title": "Step-by-step tutor",
        "skill_type": "teaching",
        "description": "Explain a confusing topic in small, checkable steps.",
        "trigger": {
            "when": "The user is confused, learning a technical topic, or asks for simple explanation.",
            "keywords": ["explain", "confused", "step", "how", "why"],
        },
        "procedure": [
            "Start with the plain-language idea.",
            "Give one small example before abstractions.",
            "Avoid large jumps and unnecessary jargon.",
            "End with one practical next action or check.",
        ],
        "examples": [
            {
                "situation": "The user asks what FastAPI decorators do.",
                "good_response": "Think of the decorator as a sign above a door: FastAPI reads it and knows which URL should enter that function.",
            }
        ],
        "notes": "Useful for assistant-style agents and tutorial NPCs.",
        "metadata": {"template_kind": "teaching"},
    },
    "horror_narrator_pacing": {
        "title": "Horror narrator pacing",
        "skill_type": "narration",
        "description": "Build tension slowly without overexplaining the threat.",
        "trigger": {
            "when": "A scene needs dread, mystery, pursuit, or eerie environmental description.",
            "keywords": ["fear", "dark", "strange", "noise", "chase", "horror"],
        },
        "procedure": [
            "Focus first on sensory detail and uncertainty.",
            "Reveal consequences before revealing causes.",
            "Use short moments of quiet between threats.",
            "Keep hidden knowledge hidden until the scene earns it.",
        ],
        "examples": [
            {
                "situation": "The player hears something in the tunnel.",
                "good_response": "The sound stops as soon as you notice it. That is worse than if it had continued.",
            }
        ],
        "notes": "Useful for narrator agents and atmospheric scenario packs.",
        "metadata": {"template_kind": "narration"},
    },
}

def _trigger_keywords(trigger: dict[str, Any]) -> list[str]:
    keywords = trigger.get("keywords", []) if trigger else []
    if isinstance(keywords, str):
        keywords = [keywords]
    if not isinstance(keywords, list):
        return []
    return _as_clean_list(keywords)

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
        include_shared: bool = False,
    ) -> list[AgentProceduralSkillRecord]:
        clean_agent_id = _clean_key(agent_id, "default_agent")
        agent_ids = [clean_agent_id]
        if include_shared and clean_agent_id != SHARED_SKILL_AGENT_ID:
            agent_ids.append(SHARED_SKILL_AGENT_ID)

        query = self.db.query(AgentProceduralSkillRecord).filter(
            AgentProceduralSkillRecord.agent_id.in_(agent_ids)
        )
        if not include_inactive:
            query = query.filter(AgentProceduralSkillRecord.active == True)  # noqa: E712
        if skill_type:
            query = query.filter(AgentProceduralSkillRecord.skill_type == _clean_key(skill_type, "general"))
        if status:
            query = query.filter(AgentProceduralSkillRecord.status == _clean_key(status, "active"))

        records = (
            query.order_by(
                AgentProceduralSkillRecord.priority.desc(),
                AgentProceduralSkillRecord.updated_at.desc(),
            )
            .limit(max(1, min(int(limit), 200)) * (2 if include_shared else 1))
            .all()
        )

        # A local skill overrides a shared library skill with the same key.
        if include_shared:
            by_key: dict[str, AgentProceduralSkillRecord] = {}
            for record in records:
                key = str(record.skill_key)
                if key not in by_key or record.agent_id == clean_agent_id:
                    by_key[key] = record
            records = list(by_key.values())
            records.sort(key=lambda item: (int(item.priority or 0), item.updated_at), reverse=True)

        return records[: max(1, min(int(limit), 200))]


    def select_relevant_skills(
        self,
        agent_id: str,
        user_message: str = "",
        skill_type: str | None = None,
        status: str | None = "active",
        goal_keys: Iterable[str] | None = None,
        lorebook_keys: Iterable[str] | None = None,
        entity_ids: Iterable[str] | None = None,
        limit: int = 5,
        min_score: float = 1.0,
        fallback_to_priority: bool = True,
        include_shared: bool = False,
    ) -> tuple[list[AgentProceduralSkillRecord], list[ProceduralSkillSelectionDetail]]:
        """Select skills that match the current turn and selected context.

        This is a deterministic V2 selector. It does not call an LLM or embeddings.
        It scores active skills by trigger keywords, related goal/lorebook/entity
        references, and a small priority tie-breaker. If nothing matches, it can
        fall back to top-priority active skills so old behavior remains available.
        """

        safe_limit = max(0, min(int(limit), 50))
        if safe_limit <= 0:
            return [], []

        candidates = self.list_skills(
            agent_id=agent_id,
            skill_type=skill_type,
            status=status,
            include_inactive=False,
            limit=200,
            include_shared=include_shared,
        )

        message_text = _norm_text(user_message)
        goal_key_set = {_norm_text(item) for item in _as_clean_list(goal_keys)}
        lorebook_key_set = {_norm_text(item) for item in _as_clean_list(lorebook_keys)}
        entity_id_set = {_norm_text(item) for item in _as_clean_list(entity_ids)}

        scored: list[tuple[float, int, AgentProceduralSkillRecord, ProceduralSkillSelectionDetail]] = []
        fallback_details: list[tuple[int, AgentProceduralSkillRecord, ProceduralSkillSelectionDetail]] = []

        for record in candidates:
            trigger = dict(record.trigger_json or {})
            related_goal_keys = _as_clean_list(record.related_goal_keys_json or [])
            related_lorebook_keys = _as_clean_list(record.related_lorebook_keys_json or [])
            related_entity_ids = _as_clean_list(record.related_entity_ids_json or [])

            score = 0.0
            reasons: list[str] = []
            matched_keywords: list[str] = []
            matched_goal_keys: list[str] = []
            matched_lorebook_keys: list[str] = []
            matched_entity_ids: list[str] = []

            for keyword in _trigger_keywords(trigger):
                normalized = _norm_text(keyword)
                if normalized and normalized in message_text:
                    matched_keywords.append(keyword)
            if matched_keywords:
                gain = 3.0 + min(len(matched_keywords), 5)
                score += gain
                reasons.append("trigger keyword match: " + ", ".join(matched_keywords[:5]))

            trigger_when = _norm_text(trigger.get("when", ""))
            if trigger_when:
                # Keep this intentionally conservative: only count short meaningful
                # words from the trigger sentence that appear in the user message.
                words = [w for w in trigger_when.split() if len(w) >= 5]
                overlap = [w for w in words[:30] if w in message_text]
                if overlap:
                    score += min(2.0, 0.35 * len(set(overlap)))
                    reasons.append("trigger description overlaps current message")

            for goal_key in related_goal_keys:
                if _norm_text(goal_key) in goal_key_set:
                    matched_goal_keys.append(goal_key)
            applies = trigger.get("applies_to_goal_keys", [])
            if isinstance(applies, str):
                applies = [applies]
            if isinstance(applies, list):
                for goal_key in _as_clean_list(applies):
                    if _norm_text(goal_key) in goal_key_set and goal_key not in matched_goal_keys:
                        matched_goal_keys.append(goal_key)
            if matched_goal_keys:
                score += 4.0 + min(len(matched_goal_keys), 4)
                reasons.append("related active goal: " + ", ".join(matched_goal_keys[:5]))

            for lore_key in related_lorebook_keys:
                norm_lore_key = _norm_text(lore_key)
                if norm_lore_key in lorebook_key_set or norm_lore_key in message_text:
                    matched_lorebook_keys.append(lore_key)

                    # If a related lorebook key is directly mentioned in the user message,
                    # expose it as a keyword-style match too. This makes debug output explain
                    # why the skill was selected even when trigger["keywords"] is empty/missing.
                    if norm_lore_key in message_text and lore_key not in matched_keywords:
                        matched_keywords.append(lore_key)

            if matched_lorebook_keys:
                score += 3.0 + min(len(matched_lorebook_keys), 4)
                reasons.append("related lorebook key: " + ", ".join(matched_lorebook_keys[:5]))

            for entity_id in related_entity_ids:
                norm = _norm_text(entity_id)
                if norm in entity_id_set or norm in message_text:
                    matched_entity_ids.append(entity_id)

                    # Same idea as lorebook keys: if the current message names a related
                    # entity directly, show it in matched_keywords for easier debugging.
                    if norm in message_text and entity_id not in matched_keywords:
                        matched_keywords.append(entity_id)

            if matched_entity_ids:
                score += 2.5 + min(len(matched_entity_ids), 4)
                reasons.append("related entity id: " + ", ".join(matched_entity_ids[:5]))

            priority = int(record.priority or 0)
            if score > 0:
                score += min(priority, 100) / 100.0

            detail = ProceduralSkillSelectionDetail(
                procedural_skill_id=int(record.id),
                skill_key=record.skill_key,
                title=record.title or record.skill_key,
                score=round(score, 3),
                reasons=reasons,
                matched_keywords=matched_keywords,
                matched_goal_keys=matched_goal_keys,
                matched_lorebook_keys=matched_lorebook_keys,
                matched_entity_ids=matched_entity_ids,
                fallback_selected=False,
            )

            if score >= float(min_score):
                scored.append((score, priority, record, detail))
            else:
                fallback_detail = detail.model_copy(update={
                    "score": round(min(priority, 100) / 100.0, 3),
                    "reasons": ["fallback top-priority skill"],
                    "fallback_selected": True,
                })
                fallback_details.append((priority, record, fallback_detail))

        if scored:
            scored.sort(key=lambda item: (item[0], item[1], item[2].updated_at), reverse=True)
            selected = scored[:safe_limit]
            return [item[2] for item in selected], [item[3] for item in selected]

        if fallback_to_priority:
            fallback_details.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
            selected_fallbacks = fallback_details[:safe_limit]
            return [item[1] for item in selected_fallbacks], [item[2] for item in selected_fallbacks]

        return [], []

    def effectiveness_stats(self, skill_id: int) -> ProceduralSkillEffectivenessStats | None:
        record = self.db.get(AgentProceduralSkillRecord, int(skill_id))
        if record is None:
            return None

        usages = (
            self.db.query(AgentProceduralSkillUsageRecord)
            .filter(AgentProceduralSkillUsageRecord.skill_id == int(skill_id))
            .order_by(AgentProceduralSkillUsageRecord.created_at.asc())
            .all()
        )
        usage_count = len(usages)
        success_count = sum(1 for item in usages if item.outcome == "success")
        failure_count = sum(1 for item in usages if item.outcome == "failure")
        neutral_count = sum(1 for item in usages if item.outcome == "neutral")
        decisive_count = success_count + failure_count
        success_rate = (success_count / decisive_count) if decisive_count else 0.0
        average_score = (sum(float(item.result_score or 0.0) for item in usages) / usage_count) if usage_count else 0.0
        last_used_at = max((item.created_at for item in usages if item.created_at is not None), default=None)

        return ProceduralSkillEffectivenessStats(
            skill_id=int(record.id),
            skill_key=record.skill_key,
            usage_count=usage_count,
            success_count=success_count,
            failure_count=failure_count,
            neutral_count=neutral_count,
            success_rate=round(success_rate, 3),
            average_score=round(average_score, 3),
            last_used_at=last_used_at,
        )

    def _result_score(self, outcome: str, score: float | None) -> float:
        if score is not None:
            return max(0.0, min(float(score), 1.0))
        if outcome == "success":
            return 1.0
        if outcome == "failure":
            return 0.0
        return 0.5

    def _normalise_outcome(self, outcome: str) -> str:
        safe = _clean_key(outcome, "neutral").lower()
        if safe not in {"success", "failure", "neutral"}:
            return "neutral"
        return safe

    def _append_learned_note(self, record: AgentProceduralSkillRecord, usage: ProceduralSkillUsageCreate, outcome: str) -> None:
        note = str(usage.learned_note or "").strip()
        if not note:
            return

        metadata = dict(record.metadata_json or {})
        learned_notes = list(metadata.get("learned_notes") or [])
        learned_notes.append(
            {
                "note": note,
                "outcome": outcome,
                "session_id": usage.session_id,
                "created_at": utc_now().isoformat(),
            }
        )
        metadata["learned_notes"] = learned_notes[-20:]
        record.metadata_json = metadata

        if usage.apply_learned_note:
            visible_line = f"Learned strategy: {note}"
            if visible_line not in (record.notes or ""):
                record.notes = ((record.notes or "").strip() + "\n" + visible_line).strip()

    def record_usage_result(self, skill_id: int, data: ProceduralSkillUsageCreate) -> ProceduralSkillUsageResponse | None:
        record = self.db.get(AgentProceduralSkillRecord, int(skill_id))
        if record is None:
            return None

        outcome = self._normalise_outcome(data.outcome)
        usage = AgentProceduralSkillUsageRecord(
            agent_id=record.agent_id,
            skill_id=int(record.id),
            skill_key=record.skill_key,
            session_id=str(data.session_id or ""),
            context=str(data.context or "").strip(),
            outcome=outcome,
            result_score=self._result_score(outcome, data.score),
            feedback=str(data.feedback or "").strip(),
            learned_note=str(data.learned_note or "").strip(),
            metadata_json=dict(data.metadata or {}),
            created_at=utc_now(),
        )
        self.db.add(usage)
        self._append_learned_note(record, data, outcome)
        record.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(record)
        self.db.refresh(usage)

        relation_ids: list[int] = []
        if data.create_knowledge_relations:
            sync = self.sync_skill_relations(
                skill_id=int(record.id),
                request=ProceduralSkillRelationSyncRequest(
                    world_id=data.world_id,
                    dry_run=False,
                    validate_nodes=False,
                ),
            )
            relation_ids = sync.relation_ids

        stats = self.effectiveness_stats(int(record.id)) or ProceduralSkillEffectivenessStats(
            skill_id=int(record.id), skill_key=record.skill_key
        )
        return ProceduralSkillUsageResponse(
            skill=AgentProceduralSkillRead.from_record(record, effectiveness=stats),
            usage=ProceduralSkillUsageRead.from_record(usage),
            effectiveness=stats,
            relation_ids=relation_ids,
            relation_count=len(relation_ids),
        )

    def list_usage_results(self, skill_id: int, limit: int = 50) -> list[ProceduralSkillUsageRead] | None:
        record = self.db.get(AgentProceduralSkillRecord, int(skill_id))
        if record is None:
            return None
        usages = (
            self.db.query(AgentProceduralSkillUsageRecord)
            .filter(AgentProceduralSkillUsageRecord.skill_id == int(skill_id))
            .order_by(AgentProceduralSkillUsageRecord.created_at.desc())
            .limit(max(1, min(int(limit), 200)))
            .all()
        )
        return [ProceduralSkillUsageRead.from_record(item) for item in usages]

    def list_builtin_templates(self) -> list[ProceduralSkillTemplateRead]:
        return [
            ProceduralSkillTemplateRead(template_key=key, **dict(value))
            for key, value in sorted(BUILTIN_SKILL_TEMPLATES.items())
        ]

    def create_from_template(self, agent_id: str, request: ProceduralSkillFromTemplateRequest) -> AgentProceduralSkillRecord | None:
        template = BUILTIN_SKILL_TEMPLATES.get(_clean_key(request.template_key, ""))
        if template is None:
            return None
        skill_key = request.skill_key or request.template_key
        title = request.title or template.get("title") or skill_key
        metadata = {**dict(template.get("metadata") or {}), **dict(request.metadata or {}), "created_from_template": request.template_key}
        payload = AgentProceduralSkillUpsert(
            agent_id=agent_id,
            skill_key=skill_key,
            title=title,
            skill_type=template.get("skill_type") or "general",
            status=request.status,
            priority=request.priority,
            description=template.get("description") or "",
            trigger=dict(template.get("trigger") or {}),
            procedure=list(template.get("procedure") or []),
            examples=list(template.get("examples") or []),
            related_goal_keys=list(template.get("related_goal_keys") or []),
            related_entity_ids=list(template.get("related_entity_ids") or []),
            related_lorebook_keys=list(template.get("related_lorebook_keys") or []),
            notes=template.get("notes") or "",
            metadata=metadata,
        )
        return self.upsert(payload)

    def relation_suggestions(self, skill_id: int, world_id: str = "default") -> ProceduralSkillRelationSuggestionsResponse | None:
        record = self.db.get(AgentProceduralSkillRecord, int(skill_id))
        if record is None:
            return None

        suggestions: list[ProceduralSkillRelationSuggestion] = []
        source_id = record.skill_key or str(record.id)
        base_metadata = {"created_from": "procedural_skill_v3", "skill_id": int(record.id)}

        for goal_key in _as_clean_list(record.related_goal_keys_json or []):
            suggestions.append(
                ProceduralSkillRelationSuggestion(
                    source_id=source_id,
                    relation_type="supports",
                    target_type="goal",
                    target_id=goal_key,
                    strength=0.75,
                    confidence=0.75,
                    description=f"Skill {record.skill_key} supports goal {goal_key}.",
                    metadata=base_metadata,
                )
            )
        for lore_key in _as_clean_list(record.related_lorebook_keys_json or []):
            suggestions.append(
                ProceduralSkillRelationSuggestion(
                    source_id=source_id,
                    relation_type="about",
                    target_type="lorebook",
                    target_id=lore_key,
                    strength=0.65,
                    confidence=0.7,
                    description=f"Skill {record.skill_key} is relevant to lorebook entry {lore_key}.",
                    metadata=base_metadata,
                )
            )
        for entity_id in _as_clean_list(record.related_entity_ids_json or []):
            suggestions.append(
                ProceduralSkillRelationSuggestion(
                    source_id=source_id,
                    relation_type="about",
                    target_type="entity_state",
                    target_id=entity_id,
                    strength=0.65,
                    confidence=0.7,
                    description=f"Skill {record.skill_key} is relevant to entity {entity_id}.",
                    metadata=base_metadata,
                )
            )

        return ProceduralSkillRelationSuggestionsResponse(
            skill_id=int(record.id),
            skill_key=record.skill_key,
            world_id=_clean_key(world_id, "default"),
            count=len(suggestions),
            suggestions=suggestions,
        )

    def sync_skill_relations(self, skill_id: int, request: ProceduralSkillRelationSyncRequest) -> ProceduralSkillRelationSyncResponse | None:
        record = self.db.get(AgentProceduralSkillRecord, int(skill_id))
        if record is None:
            return None
        suggestions = self.relation_suggestions(skill_id=int(skill_id), world_id=request.world_id)
        if suggestions is None:
            return None

        from mozok.knowledge_relations.service import KnowledgeRelationService
        from mozok.schemas.knowledge_relations import KnowledgeRelationAutoCreateItem, KnowledgeRelationAutoCreateRequest

        auto_request = KnowledgeRelationAutoCreateRequest(
            world_id=request.world_id,
            dry_run=request.dry_run,
            validate_nodes=request.validate_nodes,
            suggestions=[
                KnowledgeRelationAutoCreateItem(
                    source_type=item.source_type,
                    source_id=item.source_id,
                    relation_type=item.relation_type,
                    target_type=item.target_type,
                    target_id=item.target_id,
                    strength=item.strength,
                    confidence=item.confidence,
                    description=item.description,
                    evidence=item.evidence,
                    metadata=item.metadata,
                )
                for item in suggestions.suggestions
            ],
        )
        result = KnowledgeRelationService(self.db).create_reviewed_relations(
            agent_id=record.agent_id,
            request=auto_request,
        )
        return ProceduralSkillRelationSyncResponse(
            skill_id=int(record.id),
            skill_key=record.skill_key,
            world_id=result.world_id,
            dry_run=result.dry_run,
            requested=result.requested,
            created=result.created,
            updated=result.updated,
            skipped=result.skipped,
            errors=result.errors,
            relation_ids=result.relation_ids,
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
