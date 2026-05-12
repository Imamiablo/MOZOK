# 33 - Cognitive Field MVP

## Summary

Adds an opt-in Cognitive Field layer inspired by resonance/competition/broadcast architecture. It is intentionally documented as a functional attention and state-selection layer, not as a claim that MOZOK implements biological or phenomenal consciousness.

## Behaviour

For one turn, the Cognitive Field can create candidate thoughts from:

- the current user message;
- transient sensory/tool/world inputs;
- selected core/semantic/episodic/raw memories;
- active goals;
- procedural skills;
- entity states;
- lorebook entries;
- knowledge relations.

Each candidate receives score parts for:

- attention weight;
- sensory weight;
- memory resonance;
- goal relevance;
- emotional weight;
- procedural skill relevance;
- relation graph support;
- contradiction penalty;
- risk penalty;
- confidence.

The highest-scoring candidate becomes the read-only broadcast focus for the turn.

## API changes

Added opt-in request fields to `/chat` and `/debug/context`:

- `enable_cognitive_field`
- `sensory_inputs`
- `attention_focus_keywords`
- `cognitive_max_candidates`
- `cognitive_broadcast_top_n`
- `cognitive_min_score`

Added dedicated read-only debug endpoint:

- `POST /agents/{agent_id}/cognition/field/debug`

## Safety model

The broadcast does not mutate SQL, FAISS, memories, goals, entity states, skills, or knowledge relations. It is soft prompt/attention guidance only. Durable updates should be handled by a later reflection/change-proposal layer.

## Changed files

- `mozok/cognition/__init__.py`
- `mozok/cognition/schemas.py`
- `mozok/cognition/service.py`
- `mozok/api/cognition_routes.py`
- `mozok/api/main.py`
- `mozok/context/context_builder.py`
- `mozok/core/bot_core.py`
- `mozok/schemas/chat.py`
- `mozok/schemas/context.py`
- `tests/unit/test_cognitive_field_mvp.py`
- `ROADMAP.md`

## Tests

Added focused unit/OpenAPI tests for:

- sensory attention and memory resonance scoring;
- ContextBuilder prompt/debug integration;
- opt-in behaviour preserving the existing pipeline shape when disabled;
- OpenAPI registration for the dedicated cognition endpoint and `/debug/context` request fields.

## Manual Swagger UI check

Use `POST /agents/{agent_id}/cognition/field/debug` with a message and optional sensory inputs. Expected behaviour:

- response has `read_only: true`;
- response has `architecture: resonance_competition_broadcast`;
- `candidates` lists scored candidate thoughts;
- `broadcast.selected_thought_id` identifies the winning state;
- no memory/goal/skill/relation changes are applied.
