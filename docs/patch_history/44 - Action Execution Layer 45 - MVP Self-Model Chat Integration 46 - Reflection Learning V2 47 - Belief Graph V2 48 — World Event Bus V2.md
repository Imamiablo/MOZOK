# MOZOK patch 44-48

Copy the contents of this archive into the root of your existing `mozok` project and allow files to be replaced.

## Includes

- 44 — Action Execution Layer MVP
- 45 — Self-Model Chat Integration
- 46 — Reflection Learning V2
- 47 — Belief Graph V2
- 48 — World Event Bus V2

## After copying

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
```

If you use PostgreSQL with existing tables, restart Mozok through your normal launcher so `scripts/init_db.py` / `Base.metadata.create_all(...)` can create the new `world_events` table. `create_all` will not destroy existing tables.

## Swagger UI checks

Open `http://127.0.0.1:8000/docs` and check:

1. `GET /runtime/integration/status`
   - Should include the new action execution and world-event routes.
2. `POST /agents/{agent_id}/action-tools`
   - Register a tool such as `move_to_location`.
3. `POST /agents/{agent_id}/actions/execute`
   - Try once without approval for a medium-risk tool: it should be blocked / needs approval.
   - Try again with `approval_granted=true`: it should queue `queued_for_adapter`.
4. `POST /agents/{agent_id}/actions/executions/{execution_id}/result`
   - Report a fake adapter result and confirm status becomes `completed`.
5. `POST /world-events` then `POST /world-events/consume`, `POST /world-events/ack`, `POST /world-events/expire`.
6. `POST /chat`
   - Use `enable_self_model=true` and `enable_action_planning=true` with `available_tools`.
   - Check that `self_model` and `action_plan` appear in the response.
7. `POST /agents/{agent_id}/belief-revision/preview`
   - Use a claim that contradicts an existing semantic memory.
   - Check `belief_graph.edges` and recommended relation payloads.

## Notes

- External tools/game commands are still adapter-owned. Mozok queues and records execution requests; it does not perform arbitrary external side effects itself.
- Reflection learning still creates safe proposals. Goal/entity/belief changes are applied only through the reviewed proposal workflow.
