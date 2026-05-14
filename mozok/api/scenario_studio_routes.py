from __future__ import annotations

from fastapi import APIRouter

from mozok.scenario_studio.schemas import ScenarioStudioBuildRequest, ScenarioStudioBuildResponse, ScenarioStudioSaveRequest, ScenarioStudioSaveResponse
from mozok.scenario_studio.service import ScenarioStudioService

router = APIRouter(tags=["scenario studio"])


@router.post("/scenario-studio/build", response_model=ScenarioStudioBuildResponse)
def build_scenario_pack(data: ScenarioStudioBuildRequest) -> ScenarioStudioBuildResponse:
    return ScenarioStudioService().build(data)


@router.post("/scenario-studio/save", response_model=ScenarioStudioSaveResponse)
def save_scenario_pack(data: ScenarioStudioSaveRequest) -> ScenarioStudioSaveResponse:
    return ScenarioStudioService().save(data)
