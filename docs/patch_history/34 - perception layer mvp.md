# 34 - Perception Layer MVP

## Summary

Adds an adapter-neutral perception compiler that turns external/system/game/tool/UI/body events into `SensoryInput` objects for the Cognitive Field.

This keeps MOZOK flexible: a chat app, game engine, robot controller, desktop assistant, or simulation can provide its own events without MOZOK assuming a fixed world model.

## Added files

- `mozok/perception/__init__.py`
- `mozok/perception/schemas.py`
- `mozok/perception/service.py`
- `mozok/api/perception_routes.py`
- `tests/unit/test_perception_layer_mvp.py`

## Changed files

- `mozok/api/main.py`
- `mozok/api/cognition_routes.py`
- `mozok/context/context_builder.py`
- `mozok/core/bot_core.py`
- `mozok/schemas/chat.py`
- `mozok/schemas/context.py`
- `mozok/cognition/schemas.py`

## Behaviour

- New endpoint: `POST /perception/compile`.
- `/chat`, `/debug/context`, and Cognitive Field debug can accept `perception_events` and `perception_profile`.
- `perception_events` are compiled into transient sensory inputs before Cognitive Field scoring.
- Direct `sensory_inputs` still work and are preserved.
- The perception layer is read-only: it does not write memories, goals, skills, relations, entity states, or FAISS entries.
- The compiler is deterministic. LLM-based perception rewriting is intentionally deferred until a safe adapter policy exists.

## Flexibility notes

The layer is adapter-neutral. Events can come from:

- game/simulation world events;
- UI or desktop assistant events;
- tool/API results;
- robot/sensor readings;
- chat/file inputs;
- internal/body-like state adapters.

Adapters can pass explicit `channel_hint` values or let the compiler infer a channel from content and event type.

## Tests

Added unit tests for:

- generic event → sensory input compilation;
- preserving direct sensory inputs;
- channel allow/deny behaviour through `PerceptionProfile`.
