from __future__ import annotations

from pydantic import BaseModel, Field


class RuntimeIntegrationStatus(BaseModel):
    status: str = "ok"
    read_only: bool = True
    version_scope: str = "39-42"
    route_count: int = 0
    required_routes: list[str] = Field(default_factory=list)
    missing_routes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
