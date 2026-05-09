from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BrainPackImportAction(BaseModel):
    section: str
    action: str
    key: str = ""
    message: str = ""


class BrainPackImportReport(BaseModel):
    dry_run: bool = True
    atomic: bool = True
    world_id: str = "default"
    counts: dict[str, int] = Field(default_factory=dict)
    actions: list[BrainPackImportAction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class BrainPackImportRequest(BaseModel):
    """Import an inline brain/scenario pack through the API.

    For local files, prefer scripts/import_brain_pack.py. The API intentionally
    accepts an already-loaded dict so a future UI can send the package directly
    without granting arbitrary server-file access.
    """

    pack: dict[str, Any]
    dry_run: bool = True
    validate_relations: bool = False
    atomic: bool = True
