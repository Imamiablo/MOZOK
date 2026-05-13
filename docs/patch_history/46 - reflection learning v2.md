# 46 - Reflection Learning V2

Expanded reflection from memory/metadata/skill evidence into first-class learning proposals.

## Added

- `ReflectionGoalUpdateHint`
- `ReflectionEntityStateUpdateHint`
- `ReflectionBeliefRevisionTrigger`
- Reflection proposals for:
  - goal updates
  - entity-state updates
  - belief-revision triggers
- Change proposal operation types:
  - `update_goal`
  - `update_entity_state`
  - `add_knowledge_relation`

## Safety

Reflection still proposes changes rather than silently mutating important long-term state. Reviewed proposal application owns the actual mutation.
