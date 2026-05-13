# 37 - Agent Mode Profiles

## Summary

Adds a lightweight operating-mode layer for agents. Agent mode is not personality; it is a runtime policy bundle for deciding what kind of agent Mozok is currently running: assistant, roleplay character, simulacra NPC, narrator, world director, or tool agent.

This keeps Mozok flexible for different adapters: chatbots, assistants, roleplay bots, game NPCs, narrators, tool agents, and future simulacra runtimes.

## Added

- `mozok/agent_modes/`
  - `schemas.py`
  - `profiles.py`
  - `service.py`
- `mozok/api/agent_mode_routes.py`
- `tests/unit/test_agent_mode_profiles.py`

## Built-in modes

- `assistant`
- `roleplay_character`
- `simulacra_npc`
- `narrator`
- `world_director`
- `tool_agent`

Each mode can define:

- narrator-only lore visibility defaults
- allowed entity-state kinds
- cognitive-field default behaviour
- perception default behaviour
- reflection default behaviour
- autonomous tick/action permissions
- prompt guidance
- open-ended adapter metadata

## New endpoints

- `GET /agent-modes`
- `GET /agent-modes/{mode}`
- `POST /agents/{agent_id}/agent-mode/resolve`

## Context integration

`/chat` and `/debug/context` now accept:

- `agent_mode`
- `apply_agent_mode_defaults`
- `agent_mode_profile_overrides`

ContextBuilder resolves the mode using:

1. request override
2. `agent.metadata_json["agent_mode"]` or `agent.metadata_json["mode"]`
3. `assistant` fallback

The resolved mode appears in debug output and is rendered into the prompt as neutral operating-mode guidance.

## Behaviour

- Narrator-like modes can default-enable narrator-only lore access.
- Assistant mode filters out social-relationship entity states by default while preserving assistant-user profile states.
- Simulacra/roleplay/narrator modes can default-enable Cognitive Field.
- Reflection can be default-enabled by mode, but important long-term changes still go through the Safe Change Proposal layer.

## Notes

This patch intentionally does not add a new database table. Persistent project-specific mode settings can already live in `AgentRecord.metadata_json`. A later scenario-import standardisation patch can add first-class top-level brain-pack sections for shared mode profiles and inheritance.
