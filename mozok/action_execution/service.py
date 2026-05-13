from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from mozok.action_execution.schemas import (
    ActionExecutionListResponse,
    ActionExecutionPermission,
    ActionExecutionRecord,
    ActionExecutionRequest,
    ActionExecutionResponse,
    ActionExecutionResultUpdateRequest,
    ActionToolRegistryEntry,
    ActionToolRegistryResponse,
    ActionToolRegistryUpdateRequest,
)
from mozok.agent.service import AgentService
from mozok.agent_modes.service import AgentModeService
from mozok.db.models import AgentRecord

_RISK_ORDER = {"low": 1, "medium": 2, "high": 3}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ActionExecutionService:
    """Adapter-owned action execution queue and audit trail.

    This layer intentionally does not run arbitrary Python callbacks, game
    commands, desktop actions, or external tools. It validates permissions,
    creates rollback snapshots, records retry metadata, and queues an execution
    record that the owning adapter can consume and complete.
    """

    METADATA_KEY = "action_execution"
    REGISTRY_KEY = "tool_registry"
    EXECUTIONS_KEY = "executions"

    def __init__(self, db: Session):
        self.db = db
        self.agent_service = AgentService(db)

    def _agent(self, agent_id: str) -> AgentRecord:
        return self.agent_service.get_or_create_default_agent(agent_id)

    def _metadata(self, agent: AgentRecord) -> dict[str, Any]:
        return dict(agent.metadata_json or {})

    def _bucket(self, agent: AgentRecord) -> dict[str, Any]:
        metadata = self._metadata(agent)
        bucket = metadata.get(self.METADATA_KEY) or {}
        return dict(bucket) if isinstance(bucket, dict) else {}

    def _save_bucket(self, agent: AgentRecord, bucket: dict[str, Any]) -> None:
        metadata = self._metadata(agent)
        metadata[self.METADATA_KEY] = bucket
        agent.metadata_json = metadata
        agent.updated_at = utc_now()
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)

    def registry(self, agent_id: str) -> ActionToolRegistryResponse:
        agent = self._agent(agent_id)
        tools = [ActionToolRegistryEntry.model_validate(item) for item in self._bucket(agent).get(self.REGISTRY_KEY, [])]
        return ActionToolRegistryResponse(agent_id=agent_id, tool_count=len(tools), tools=tools)

    def update_registry(self, agent_id: str, request: ActionToolRegistryUpdateRequest) -> ActionToolRegistryResponse:
        agent = self._agent(agent_id)
        bucket = self._bucket(agent)
        current = [] if request.replace else list(bucket.get(self.REGISTRY_KEY) or [])
        by_name: dict[str, dict[str, Any]] = {}
        for item in current:
            try:
                entry = ActionToolRegistryEntry.model_validate(item)
            except Exception:
                continue
            by_name[entry.name] = entry.model_dump(mode="json")
        for tool in request.tools:
            by_name[tool.name] = tool.model_dump(mode="json")
        bucket[self.REGISTRY_KEY] = list(by_name.values())
        self._save_bucket(agent, bucket)
        return self.registry(agent_id)

    def list_executions(self, agent_id: str, limit: int = 50) -> ActionExecutionListResponse:
        agent = self._agent(agent_id)
        raw = list(self._bucket(agent).get(self.EXECUTIONS_KEY) or [])
        items = [ActionExecutionRecord.model_validate(item) for item in reversed(raw[-max(1, min(limit, 250)):])]
        return ActionExecutionListResponse(agent_id=agent_id, execution_count=len(items), executions=items)

    def execute(self, agent_id: str, request: ActionExecutionRequest) -> ActionExecutionResponse:
        agent = self._agent(agent_id)
        bucket = self._bucket(agent)
        registry = [ActionToolRegistryEntry.model_validate(item) for item in bucket.get(self.REGISTRY_KEY, [])]
        tools_by_name = {tool.name: tool for tool in registry}

        intent = request.intent
        tool_name = request.tool_name or (intent.tool_name if intent else None)
        action_kind = request.action_kind or (intent.action_kind if intent else "no_op")
        parameters = dict(request.parameters or {})
        if intent and not request.parameters:
            parameters = dict(intent.parameters or {})

        tool = tools_by_name.get(tool_name or "") if tool_name else None
        permission = self._permission(agent=agent, tool=tool, action_kind=action_kind, approval_granted=request.approval_granted)
        retry_attempt = self._retry_attempt(bucket, request.retry_of_execution_id)
        max_retries = int(tool.max_retries if tool else 0)
        now = utc_now()

        status = "dry_run" if request.dry_run else "queued_for_adapter"
        adapter_owned = True if tool is None else bool(tool.adapter_owned)
        notes = ["Mozok did not execute external side effects; adapter ownership is preserved."]
        if permission.decision == "blocked":
            status = "blocked"
        elif permission.decision == "needs_approval":
            status = "blocked"
            notes.append("Execution requires approval_granted=true before queueing.")
        elif action_kind == "no_op":
            status = "completed" if not request.dry_run else "dry_run"
            adapter_owned = False
            notes.append("No-op execution completed inside Mozok because it has no side effect.")

        if request.retry_of_execution_id and retry_attempt > max_retries + 1:
            status = "blocked"
            permission.reasons.append("retry_limit_exceeded")

        rollback_snapshot = self._rollback_snapshot(agent, action_kind=action_kind, tool_name=tool_name, parameters=parameters)
        execution = ActionExecutionRecord(
            execution_id=f"exec_{uuid4().hex[:16]}",
            agent_id=agent_id,
            action_id=intent.action_id if intent else None,
            action_kind=action_kind,
            tool_name=tool_name,
            parameters=parameters,
            status=status,
            permission=permission,
            attempt_count=retry_attempt,
            max_retries=max_retries,
            adapter_owned=adapter_owned,
            adapter_instruction=self._adapter_instruction(status=status, action_kind=action_kind, tool_name=tool_name),
            requested_by=request.requested_by,
            idempotency_key=request.idempotency_key,
            retry_of_execution_id=request.retry_of_execution_id,
            rollback_snapshot=rollback_snapshot,
            metadata=request.metadata,
            notes=notes,
            created_at=now,
            updated_at=now,
        )

        if request.store_execution and not request.dry_run:
            raw = list(bucket.get(self.EXECUTIONS_KEY) or [])
            raw.append(execution.model_dump(mode="json"))
            bucket[self.EXECUTIONS_KEY] = raw[-250:]
            self._save_bucket(agent, bucket)

        return ActionExecutionResponse(agent_id=agent_id, read_only=bool(request.dry_run), execution=execution, notes=notes)

    def update_result(self, agent_id: str, execution_id: str, request: ActionExecutionResultUpdateRequest) -> ActionExecutionResponse | None:
        agent = self._agent(agent_id)
        bucket = self._bucket(agent)
        raw = list(bucket.get(self.EXECUTIONS_KEY) or [])
        updated = False
        execution: ActionExecutionRecord | None = None
        for index, item in enumerate(raw):
            candidate = ActionExecutionRecord.model_validate(item)
            if candidate.execution_id != execution_id:
                continue
            candidate.status = request.status
            candidate.result = dict(request.result or {})
            candidate.notes.extend(request.notes or [])
            candidate.updated_at = utc_now()
            raw[index] = candidate.model_dump(mode="json")
            execution = candidate
            updated = True
            break
        if not updated or execution is None:
            return None
        bucket[self.EXECUTIONS_KEY] = raw
        self._save_bucket(agent, bucket)
        return ActionExecutionResponse(agent_id=agent_id, execution=execution, notes=["Adapter execution result recorded."])

    def _permission(
        self,
        agent: AgentRecord,
        tool: ActionToolRegistryEntry | None,
        action_kind: str,
        approval_granted: bool,
    ) -> ActionExecutionPermission:
        mode = AgentModeService().resolve(agent).profile
        reasons: list[str] = []
        risk = tool.risk_level if tool else "low"
        approval_required = bool(tool.requires_approval) if tool else False

        if action_kind == "speak" or action_kind == "no_op":
            return ActionExecutionPermission(decision="allowed", risk_level="low", approval_required=False, approval_granted=True, reasons=["safe_builtin_action"])

        if tool is None:
            return ActionExecutionPermission(decision="blocked", risk_level="medium", approval_required=True, approval_granted=approval_granted, reasons=["tool_not_registered"])
        if not tool.enabled:
            return ActionExecutionPermission(decision="blocked", risk_level=risk, approval_required=approval_required, approval_granted=approval_granted, reasons=["tool_disabled"])
        if tool.allowed_agent_modes and mode.mode not in tool.allowed_agent_modes:
            return ActionExecutionPermission(decision="blocked", risk_level=risk, approval_required=approval_required, approval_granted=approval_granted, reasons=["agent_mode_not_allowed"])
        if action_kind in {"tool_call", "game_command", "world_event", "memory_operation"} and not mode.can_execute_actions:
            return ActionExecutionPermission(decision="blocked", risk_level=risk, approval_required=approval_required, approval_granted=approval_granted, reasons=["agent_mode_cannot_execute_actions"])
        if approval_required and not approval_granted:
            return ActionExecutionPermission(decision="needs_approval", risk_level=risk, approval_required=True, approval_granted=False, reasons=["approval_required"])
        if _RISK_ORDER.get(risk, 3) >= 3 and not approval_granted:
            return ActionExecutionPermission(decision="needs_approval", risk_level=risk, approval_required=True, approval_granted=False, reasons=["high_risk_requires_approval"])

        reasons.append("registered_tool_allowed")
        return ActionExecutionPermission(decision="allowed", risk_level=risk, approval_required=approval_required, approval_granted=approval_granted, reasons=reasons)

    def _retry_attempt(self, bucket: dict[str, Any], retry_of_execution_id: str | None) -> int:
        if not retry_of_execution_id:
            return 1
        raw = bucket.get(self.EXECUTIONS_KEY) or []
        for item in raw:
            try:
                execution = ActionExecutionRecord.model_validate(item)
            except Exception:
                continue
            if execution.execution_id == retry_of_execution_id:
                return int(execution.attempt_count) + 1
        return 1

    def _rollback_snapshot(self, agent: AgentRecord, action_kind: str, tool_name: str | None, parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent_id": agent.id,
            "action_kind": action_kind,
            "tool_name": tool_name,
            "parameters": deepcopy(parameters),
            "agent_metadata_before": deepcopy(agent.metadata_json or {}),
            "created_at": utc_now().isoformat(),
            "note": "Snapshot is for adapter/UI rollback. Mozok does not reverse external side effects by itself.",
        }

    def _adapter_instruction(self, status: str, action_kind: str, tool_name: str | None) -> str:
        if status == "queued_for_adapter":
            return f"Adapter should execute {action_kind}:{tool_name or 'unnamed'} and report the result back."
        if status == "blocked":
            return "Do not execute; permission, approval, registry, or retry checks failed."
        if status == "dry_run":
            return "Dry run only; no adapter execution should occur."
        return "No adapter execution required."
