from __future__ import annotations

from fastapi import FastAPI

from mozok.runtime_integration.schemas import RuntimeIntegrationStatus


REQUIRED_RUNTIME_ROUTES = [
    "/runtime/integration/status",
    "/agents/{agent_id}/tick",
    "/world-events",
    "/world-events/search",
    "/world-events/consume",
    "/world-events/ack",
    "/agents/{agent_id}/action-tools",
    "/agents/{agent_id}/actions/execute",
    "/evaluation-packs/run",
]


class RuntimeIntegrationService:
    """Small route/OpenAPI sanity layer for late V2 runtime patches."""

    def status(self, app: FastAPI) -> RuntimeIntegrationStatus:
        paths = set(app.openapi().get("paths", {}).keys())
        missing = [path for path in REQUIRED_RUNTIME_ROUTES if path not in paths]
        return RuntimeIntegrationStatus(
            status="ok" if not missing else "missing_routes",
            route_count=len(paths),
            required_routes=list(REQUIRED_RUNTIME_ROUTES),
            missing_routes=missing,
            notes=[
                "This endpoint is read-only and exists as a Swagger/OpenAPI smoke check.",
                "It verifies that the runtime, action-execution, world-event, and evaluation-pack routers are visible to FastAPI.",
            ],
        )
