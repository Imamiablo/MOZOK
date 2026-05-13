# 38 - Action Planning, Self-Model, and Belief Revision MVP

## Summary

This patch adds the next cognitive-backbone pieces after Agent Mode Profiles:

- Action Planning / Tool Intent Layer
- Self-Model / Reflective State
- Belief Revision / Contradiction Handling

The patch is deliberately adapter-neutral and safe-by-default. It creates plans,
state previews, and reviewable proposals, but it does not execute tools, mutate
external worlds, rewrite memories, or claim biological consciousness.

## Changed files

- `mozok/action_planning/`
- `mozok/self_model/`
- `mozok/belief_revision/`
- `mozok/api/action_planning_routes.py`
- `mozok/api/self_model_routes.py`
- `mozok/api/belief_revision_routes.py`
- `mozok/api/main.py`
- `tests/unit/test_action_self_belief_v38.py`
- `ROADMAP.md`

## Action Planning / Tool Intent Layer

New endpoints:

- `POST /agents/{agent_id}/actions/plan`
- `POST /agents/{agent_id}/actions/propose`

The planner turns user messages, cognitive broadcasts, sensory inputs, agent
mode, and adapter-provided tool specs into ranked action intents.

It supports generic action kinds:

- `speak`
- `tool_call`
- `game_command`
- `world_event`
- `memory_operation`
- `no_op`

The planner returns intents only. External systems still decide how to execute
approved actions.

## Self-Model / Reflective State

New endpoints:

- `POST /agents/{agent_id}/self-model/preview`
- `POST /agents/{agent_id}/self-model/propose-update`

The self-model is an operational state summary:

- mode
- current task
- active focus
- confidence / uncertainty
- current limitations
- current needs
- behavioural constraints

It can be previewed read-only or stored as a safe change proposal.

## Belief Revision / Contradiction Handling

New endpoints:

- `POST /agents/{agent_id}/belief-revision/preview`
- `POST /agents/{agent_id}/belief-revision/propose`

The MVP uses conservative lexical overlap and negation/supersession markers to
flag possible:

- `supports`
- `contradicts`
- `supersedes`
- `uncertain`

It does not delete or rewrite memories. When requested, it creates a reviewable
change proposal that stores a compact preview in agent metadata.

## Tests

Added unit tests for:

- action intent generation without execution
- action proposal storage
- self-model preview and proposal creation
- contradiction detection
- OpenAPI route registration

## Notes

Reflection Loop was already implemented in version 36. This patch connects the
next neighbouring systems around it rather than reimplementing reflection.
