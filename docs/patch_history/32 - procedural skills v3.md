# 32 - Procedural Skills V3

## Summary

This patch turns procedural skills from static prompt snippets into inspectable,
learnable behaviour strategies.

The implementation is intentionally conservative: skills do not rewrite
themselves automatically after every chat turn. Instead, callers can explicitly
record outcomes, review effectiveness, apply learned notes, seed skills from
built-in templates, opt into a shared skill library, and sync reviewed skill
links into the KnowledgeRelation graph.

## Changed files

- `mozok/procedural_skills/models.py`
- `mozok/procedural_skills/service.py`
- `mozok/schemas/procedural_skills.py`
- `mozok/api/procedural_skill_routes.py`
- `mozok/schemas/chat.py`
- `mozok/schemas/context.py`
- `mozok/context/context_builder.py`
- `mozok/core/bot_core.py`
- `mozok/api/main.py`
- `tests/unit/test_procedural_skills_v3.py`
- `ROADMAP.md`

## New API endpoints

- `GET /procedural-skills/templates`
- `POST /agents/{agent_id}/procedural-skills/from-template`
- `POST /procedural-skills/shared/upsert`
- `GET /procedural-skills/shared`
- `POST /procedural-skills/{skill_id}/usage-results`
- `GET /procedural-skills/{skill_id}/usage-results`
- `GET /procedural-skills/{skill_id}/effectiveness`
- `GET /procedural-skills/{skill_id}/relation-suggestions`
- `POST /procedural-skills/{skill_id}/relations/sync`

## Behaviour

### Usage/result tracking

A new `agent_procedural_skill_usage` table stores observed skill outcomes:

- `success`
- `failure`
- `neutral`

Each usage can include session id, context, feedback, score, learned note, and
metadata. This is evidence, not a destructive rewrite of the skill.

### Effectiveness score

The effectiveness endpoint reports:

- usage count
- success count
- failure count
- neutral count
- success rate
- average score
- last-used timestamp

### Learned strategies

`learned_note` is always preserved as evidence on the usage record. If
`apply_learned_note=true`, Mozok also appends a visible `Learned strategy:` line
to the skill notes. This makes updates deliberate and reviewable.

### Shared skill library

Shared/global skills live under the reserved agent id `__shared__`. They are not
included by default, so existing agent isolation remains unchanged. Callers can
opt in with:

- `include_shared=true` on procedural skill API routes
- `include_shared_procedural_skills=true` on `/chat` and `/debug/context`

Local skills override shared skills with the same `skill_key`.

### Skill templates

The first built-in templates are:

- `careful_secret_deflection`
- `step_by_step_tutor`
- `horror_narrator_pacing`

They provide safe starting points for conversation, teaching, and narration
skills.

### KnowledgeRelation integration

Skill relation suggestions are generated from existing skill links:

- skill → goal as `supports`
- skill → lorebook as `about`
- skill → entity_state as `about`

The sync endpoint sends reviewed suggestions through the Knowledge Relations V3
auto-create workflow. Dry-run is supported.

## Tests

Added tests for:

- template listing and skill creation from template
- usage tracking and effectiveness stats
- learned note application
- opt-in shared skill selection
- relation suggestions and dry-run/create graph sync
- OpenAPI route registration

Full test result in the review environment:

```text
145 passed, 3 skipped, 8 warnings
```

## Swagger UI notes

Recommended manual checks:

1. `GET /procedural-skills/templates`
2. `POST /agents/{agent_id}/procedural-skills/from-template`
3. `POST /procedural-skills/{skill_id}/usage-results`
4. `GET /procedural-skills/{skill_id}/effectiveness`
5. `GET /procedural-skills/{skill_id}/relation-suggestions`
6. `POST /procedural-skills/{skill_id}/relations/sync` first with `dry_run=true`, then optionally with `dry_run=false`

No automatic LLM call is required for these checks.
