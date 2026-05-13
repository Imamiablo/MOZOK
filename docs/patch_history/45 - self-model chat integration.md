# 45 - Self-Model Chat Integration

Integrated the functional self-model into `/chat`.

## Added

- New `ChatRequest` switches:
  - `enable_self_model`
  - `include_self_model_in_prompt`
  - `self_model_confidence`
  - `self_model_uncertainty`
- New `/chat` action-planning controls:
  - `enable_action_planning`
  - `available_tools`
  - `allowed_action_kinds`
  - `execute_selected_action`
  - `action_execution_approval_granted`
- New `ChatResponse` fields:
  - `self_model`
  - `action_plan`
  - `action_execution`

## Behaviour

The self-model is generated after context/perception/cognition, can be injected into the final prompt, can feed action planning, and is passed into reflection metadata.
