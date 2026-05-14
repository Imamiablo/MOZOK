from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.visual_graph.schemas import VisualKnowledgeGraphRequest, VisualKnowledgeGraphResponse
from mozok.visual_graph.service import VisualKnowledgeGraphService

router = APIRouter(tags=["visual knowledge graph"])


@router.post("/agents/{agent_id}/knowledge-graph/visual", response_model=VisualKnowledgeGraphResponse)
def build_visual_knowledge_graph(agent_id: str, data: VisualKnowledgeGraphRequest, db: Session = Depends(get_db)) -> VisualKnowledgeGraphResponse:
    return VisualKnowledgeGraphService(db).build(agent_id, data)
