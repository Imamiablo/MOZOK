"""Schemas for importing local brain-pack files by safe name."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BrainPackImportByNameRequest(BaseModel):
    pack_name: str = Field(
        ...,
        description="Safe brain-pack file name from data/brain_packs, with or without .json/.yaml/.yml extension.",
        examples=["cyberpunk_demo_brain_pack"],
    )
    dry_run: bool = Field(default=True, description="Preview the import without writing to the database/FAISS.")
    validate_relations: bool = Field(default=True, description="Validate knowledge relation nodes before importing.")
    atomic: bool = Field(default=True, description="Attempt to treat the scenario import as one all-or-nothing operation.")
