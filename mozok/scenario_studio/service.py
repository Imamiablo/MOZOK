from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mozok.scenario_studio.schemas import (
    ScenarioStudioBuildRequest,
    ScenarioStudioBuildResponse,
    ScenarioStudioSaveRequest,
    ScenarioStudioSaveResponse,
    ScenarioStudioValidationMessage,
)


def _slug(value: str, fallback: str = "scenario") -> str:
    clean = re.sub(r"[^a-zA-Z0-9_\-]+", "_", str(value or "").strip()).strip("_").lower()
    return clean or fallback


class ScenarioStudioService:
    """Small helper that turns a friendly scenario draft into a brain pack.

    It does not import automatically. The returned JSON can be dry-run imported
    through the existing brain-pack importer or saved under data/brain_packs.
    """

    def build(self, request: ScenarioStudioBuildRequest) -> ScenarioStudioBuildResponse:
        messages = self._validate(request)
        pack = self._brain_pack(request, messages)
        evaluation = self._evaluation_stub(request) if request.include_demo_evaluation_stub else None
        return ScenarioStudioBuildResponse(
            world_id=request.world_id,
            title=request.title,
            valid=not any(item.level == "error" for item in messages),
            brain_pack=pack,
            evaluation_pack=evaluation,
            messages=messages,
        )

    def save(self, request: ScenarioStudioSaveRequest, root: Path | None = None) -> ScenarioStudioSaveResponse:
        built = self.build(request)
        base = root or Path("data") / "brain_packs"
        base.mkdir(parents=True, exist_ok=True)
        filename = _slug(request.filename.removesuffix(".json"), "scenario_studio_pack") + ".json"
        path = base / filename
        if path.exists() and not request.overwrite:
            messages = list(built.messages)
            messages.append(
                ScenarioStudioValidationMessage(
                    level="error",
                    section="file",
                    message=f"File already exists: {path}. Set overwrite=true to replace it.",
                )
            )
            return ScenarioStudioSaveResponse(**built.model_dump(), saved=False, path=str(path), messages=messages, valid=False)
        path.write_text(json.dumps(built.brain_pack, indent=2, ensure_ascii=False), encoding="utf-8")
        return ScenarioStudioSaveResponse(**built.model_dump(), saved=True, path=str(path))

    def _validate(self, request: ScenarioStudioBuildRequest) -> list[ScenarioStudioValidationMessage]:
        messages: list[ScenarioStudioValidationMessage] = []
        agent_ids = {agent.agent_id for agent in request.agents}
        if not request.agents:
            messages.append(ScenarioStudioValidationMessage(level="warning", section="agents", message="Scenario has no agents."))
        for goal in request.goals:
            if goal.agent_id not in agent_ids:
                messages.append(ScenarioStudioValidationMessage(level="warning", section="goals", message=f"Goal {goal.goal_key} references unknown agent {goal.agent_id}."))
        for skill in request.procedural_skills:
            if skill.agent_id not in agent_ids:
                messages.append(ScenarioStudioValidationMessage(level="warning", section="procedural_skills", message=f"Skill {skill.skill_key} references unknown agent {skill.agent_id}."))
        lore_keys = {entry.entry_key for entry in request.lorebook_entries}
        for goal in request.goals:
            missing = [key for key in goal.related_lorebook_keys if key not in lore_keys]
            if missing:
                messages.append(ScenarioStudioValidationMessage(level="warning", section="goals", message=f"Goal {goal.goal_key} references missing lore: {missing}."))
        return messages

    def _brain_pack(self, request: ScenarioStudioBuildRequest, messages: list[ScenarioStudioValidationMessage]) -> dict[str, Any]:
        relations = [item.model_dump() for item in request.knowledge_relations]
        if request.auto_link_goals_to_lore:
            for goal in request.goals:
                for key in goal.related_lorebook_keys:
                    relations.append(
                        {
                            "agent_id": goal.agent_id,
                            "source_type": "goal",
                            "source_id": goal.goal_key,
                            "relation_type": "depends_on",
                            "target_type": "lorebook",
                            "target_id": key,
                            "strength": 0.8,
                            "confidence": 0.8,
                            "description": "Scenario Studio auto-link: goal depends on lore.",
                        }
                    )
        if request.auto_link_skills_to_goals:
            for skill in request.procedural_skills:
                for goal_key in skill.related_goal_keys:
                    relations.append(
                        {
                            "agent_id": skill.agent_id,
                            "source_type": "procedural_skill",
                            "source_id": skill.skill_key,
                            "relation_type": "supports",
                            "target_type": "goal",
                            "target_id": goal_key,
                            "strength": 0.85,
                            "confidence": 0.8,
                            "description": "Scenario Studio auto-link: skill supports goal.",
                        }
                    )

        return {
            "schema_version": 1,
            "world_id": request.world_id,
            "title": request.title,
            "summary": request.summary,
            "metadata": {"created_by": "scenario_studio_mvp", **request.metadata},
            "agents": [
                {
                    "agent_id": agent.agent_id,
                    "name": agent.name,
                    "description": agent.description or agent.role,
                    "personality": agent.personality,
                    "system_prompt": agent.system_prompt,
                    "metadata": {"agent_mode": agent.mode, "role": agent.role} if agent.mode else {"role": agent.role},
                }
                for agent in request.agents
            ],
            "lorebook_entries": [entry.model_dump() for entry in request.lorebook_entries],
            "entity_states": [state.model_dump() for state in request.entity_states],
            "goals": [
                {
                    "agent_id": goal.agent_id,
                    "goal_key": goal.goal_key,
                    "title": goal.title,
                    "goal_type": "scenario",
                    "status": "active",
                    "priority": goal.priority,
                    "description": goal.description,
                    "related_entity_ids": goal.related_entity_ids,
                    "related_lorebook_keys": goal.related_lorebook_keys,
                }
                for goal in request.goals
            ],
            "procedural_skills": [
                {
                    "agent_id": skill.agent_id,
                    "skill_key": skill.skill_key,
                    "title": skill.title,
                    "skill_type": "scenario",
                    "status": "active",
                    "priority": skill.priority,
                    "description": skill.description,
                    "trigger": {"keywords": skill.keywords},
                    "procedure": skill.procedure,
                    "related_goal_keys": skill.related_goal_keys,
                    "related_entity_ids": skill.related_entity_ids,
                    "related_lorebook_keys": skill.related_lorebook_keys,
                }
                for skill in request.procedural_skills
            ],
            "knowledge_relations": relations,
            "memories": [memory.model_dump() for memory in request.memories],
            "studio_messages": [message.model_dump() for message in messages],
        }

    def _evaluation_stub(self, request: ScenarioStudioBuildRequest) -> dict[str, Any]:
        first_agent = request.agents[0].agent_id if request.agents else "demo_agent"
        first_lore = request.lorebook_entries[0].title if request.lorebook_entries else request.title
        return {
            "pack_name": f"{_slug(request.world_id)}_smoke_eval",
            "cases": [
                {
                    "case_id": "scenario_studio_smoke",
                    "agent_id": first_agent,
                    "world_id": request.world_id,
                    "message": f"What do you know about {first_lore}?",
                    "enable_cognitive_field": True,
                    "expectations": {"prompt_contains": [first_lore] if first_lore else []},
                }
            ],
        }
