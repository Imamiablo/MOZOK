from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.evaluation_packs.schemas import EvaluationPackRunRequest, EvaluationPackRunResponse
from mozok.evaluation_packs.service import EvaluationPackService

router = APIRouter(tags=["evaluation packs"])


@router.post("/evaluation-packs/run", response_model=EvaluationPackRunResponse)
def run_evaluation_pack(data: EvaluationPackRunRequest, db: Session = Depends(get_db)) -> EvaluationPackRunResponse:
    return EvaluationPackService(db).run(data)
