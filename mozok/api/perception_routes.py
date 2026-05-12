from __future__ import annotations

from fastapi import APIRouter

from mozok.perception.schemas import PerceptionCompileRequest, PerceptionCompileResponse
from mozok.perception.service import PerceptionCompiler

router = APIRouter(tags=["perception"])


@router.post("/perception/compile", response_model=PerceptionCompileResponse)
def compile_perception(data: PerceptionCompileRequest) -> PerceptionCompileResponse:
    """Compile adapter-neutral events into read-only sensory inputs for Cognitive Field."""
    return PerceptionCompiler().compile(
        events=data.events,
        existing_sensory_inputs=data.existing_sensory_inputs,
        profile=data.profile,
        message=data.message,
    )
