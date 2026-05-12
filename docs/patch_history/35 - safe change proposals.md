# 35 - Safe Change Proposals

## Summary

Adds a generic review/apply layer for Mozok self-updates. Cognitive Field, future reflection, maintenance, deduplication, and skill learning can now express intended changes as safe proposals instead of mutating SQL/FAISS directly.

## Added

- `mozok/change_proposals/schemas.py`
- `mozok/change_proposals/service.py`
- `mozok/api/change_proposal_routes.py`
- Unit tests for create/list/apply/reject/auto policy behaviour.

## API

- `POST /agents/{agent_id}/change-proposals`
- `GET /agents/{agent_id}/change-proposals`
- `POST /agents/{agent_id}/change-proposals/apply`
- `POST /agents/{agent_id}/change-proposals/reject`
- `POST /agents/{agent_id}/change-proposals/auto-apply`

## Behaviour

- Proposals are stored in `AgentRecord.metadata_json["change_proposals"]` for backwards compatibility.
- Supports `manual_review`, `apply_low_risk`, `auto_with_rollback`, and `dry_run_only` modes.
- Each applied proposal records a lightweight rollback snapshot.
- Supported MVP operations:
  - `add_memory`
  - `update_agent_metadata`
  - `record_skill_usage_result`
  - `no_op`

## Safety

Cognitive broadcast remains read-only. This patch gives later cognitive/reflection layers a safe path to request changes without applying them silently.
