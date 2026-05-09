from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.scenario_import.schemas import BrainPackImportReport, BrainPackImportRequest
from mozok.scenario_import.service import BrainPackImportService

router = APIRouter(tags=["brain-packs"])


@router.post("/brain-packs/import", response_model=BrainPackImportReport)
def import_brain_pack(request: BrainPackImportRequest, db: Session = Depends(get_db)):
    return BrainPackImportService(db).import_pack(
        request.pack,
        dry_run=request.dry_run,
        validate_relations=request.validate_relations,
    )
