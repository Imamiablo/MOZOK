# 44 - Action Execution Layer MVP

Added the first adapter-owned execution layer for Mozok actions.

## Added

- `mozok/action_execution/schemas.py`
- `mozok/action_execution/service.py`
- `mozok/api/action_execution_routes.py`
- Per-agent action/tool registry stored in agent metadata.
- Action execution records with:
  - permission decision
  - approval requirement
  - risk level
  - retry metadata
  - rollback snapshot
  - adapter instruction
  - result update workflow

## Routes

- `GET /agents/{agent_id}/action-tools`
- `POST /agents/{agent_id}/action-tools`
- `POST /agents/{agent_id}/actions/execute`
- `GET /agents/{agent_id}/actions/executions`
- `POST /agents/{agent_id}/actions/executions/{execution_id}/result`

## Design note

Mozok still does not execute arbitrary external tools or game commands directly. The execution layer queues reviewed, permission-checked records for the owning adapter to execute and report back.
