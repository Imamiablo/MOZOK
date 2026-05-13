from __future__ import annotations

from fastapi import APIRouter, Request

from mozok.runtime_integration.schemas import RuntimeIntegrationStatus
from mozok.runtime_integration.service import RuntimeIntegrationService

router = APIRouter(tags=["runtime integration"])


@router.get("/runtime/integration/status", response_model=RuntimeIntegrationStatus)
def runtime_integration_status(request: Request) -> RuntimeIntegrationStatus:
    return RuntimeIntegrationService().status(request.app)
