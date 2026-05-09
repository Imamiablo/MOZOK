# Patch 18 — Procedural Skills MVP

## Goal

Add a first-class Procedural Skills layer to Mozok.

Procedural skills describe **how an agent performs tasks or handles situations**. They are not memories and not goals:

- Memory = what the agent remembers.
- Goal/Plan = what the agent wants to do.
- Procedural Skill = how the agent tends to do it.

Examples:

- `deflect_dangerous_questions` for an NPC hiding a secret.
- `explain_programming_step_by_step` for an assistant.
- `maintain_horror_pacing` for a narrator.

## Added

- `mozok/procedural_skills/models.py`
- `mozok/procedural_skills/service.py`
- `mozok/schemas/procedural_skills.py`
- `mozok/api/procedural_skill_routes.py`
- API tests for procedural skills
- ContextBuilder unit tests for procedural skill prompt integration

## Endpoints

```text
POST   /procedural-skills/upsert
PATCH  /procedural-skills/{skill_id}
DELETE /procedural-skills/{skill_id}
GET    /agents/{agent_id}/procedural-skills
GET    /agents/{agent_id}/procedural-skills/context
```

## Context integration

Procedural skills can now be included in:

- `/debug/context`
- `/chat`
- `ContextPackage.to_system_prompt()`
- pipeline step counts
- debug sections
- token budget trimming

## Request fields added

- `include_procedural_skills`
- `procedural_skill_limit`
- `procedural_skill_type`
- `procedural_skill_status`

## Response/debug fields added

- `used_procedural_skill_ids`
- `used_procedural_skills_count`
- `sections.procedural_skills`

## Knowledge Relations compatibility

Knowledge Relations V2 can now resolve nodes of type:

- `procedural_skill`
- `skill`

This allows edges like:

```text
procedural_skill:deflect_dangerous_questions supports goal:hide_tunnel_secret
```

## Still TODO / later V2 ideas

- Trigger-based skill selection from the current user message.
- Skill selection using related active goals.
- Embedding-based skill retrieval.
- Skill libraries/templates shared across agents.
- Auto-learning/refining skills from repeated successful behavior.
