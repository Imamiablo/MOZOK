from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from mozok.core.bot_core import BotCore, get_memory_service
from mozok.db.session import get_db
from mozok.schemas.chat import ChatRequest, ChatResponse
from mozok.schemas.memory import (
    MemoryCreate,
    MemoryForgetRequest,
    MemoryForgetResponse,
    MemoryMaintenanceRequest,
    MemoryMaintenanceResponse,
    MemoryPolicyUpdate,
    MemoryRead,
    MemorySearchRequest,
    MemorySearchResult,
)

app = FastAPI(title="Mozok", version="0.2.0")


@app.get("/")
def root():
    return {
        "name": "Mozok",
        "status": "alive",
        "description": "Reusable bot-brain engine using PostgreSQL + FAISS.",
        "memory_model": ["raw", "episodic", "semantic", "core"],
    }


@app.post("/memories", response_model=MemoryRead)
def add_memory(data: MemoryCreate, db: Session = Depends(get_db)):
    memory = get_memory_service(db).add_memory(data)
    return MemoryRead(
        id=memory.id,
        agent_id=memory.agent_id,
        content=memory.content,
        memory_type=memory.memory_type,
        importance=memory.importance,
        emotional_weight=memory.emotional_weight,
        metadata=memory.metadata_json,
    )


@app.post("/memories/search", response_model=list[MemorySearchResult])
def search_memories(data: MemorySearchRequest, db: Session = Depends(get_db)):
    return get_memory_service(db).search(
        agent_id=data.agent_id,
        query=data.query,
        limit=data.limit,
        memory_type=data.memory_type,
    )


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    ok = get_memory_service(db).soft_delete(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": True, "memory_id": memory_id}


@app.post("/memories/{memory_id}/forget", response_model=MemoryForgetResponse)
def forget_memory(memory_id: int, data: MemoryForgetRequest, db: Session = Depends(get_db)):
    result = get_memory_service(db).forget_memory(
        memory_id=memory_id,
        action=data.action,
        reason=data.reason,
        decay_amount=data.decay_amount,
        rebuild_index=data.rebuild_index,
    )
    if not result["changed"] and result["message"] == "Memory not found.":
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryForgetResponse(**result)


@app.post("/memories/rebuild-index")
def rebuild_index(db: Session = Depends(get_db)):
    count = get_memory_service(db).rebuild_index()
    return {"rebuilt": True, "indexed_memories": count}


@app.get("/agents/{agent_id}/memory-policy")
def get_agent_memory_policy(agent_id: str, db: Session = Depends(get_db)):
    return get_memory_service(db).get_memory_policy(agent_id)


@app.patch("/agents/{agent_id}/memory-policy")
def update_agent_memory_policy(agent_id: str, data: MemoryPolicyUpdate, db: Session = Depends(get_db)):
    policy = get_memory_service(db).update_memory_policy(agent_id, data.memory_policy)
    return {"agent_id": agent_id, "memory_policy": policy}


@app.post("/agents/{agent_id}/memory-maintenance", response_model=MemoryMaintenanceResponse)
def run_agent_memory_maintenance(
    agent_id: str,
    data: MemoryMaintenanceRequest | None = None,
    db: Session = Depends(get_db),
):
    request = data or MemoryMaintenanceRequest()
    return get_memory_service(db).run_maintenance(
        agent_id=agent_id,
        trigger=request.trigger,
        rebuild_index=request.rebuild_index,
    )


@app.post("/agents/{agent_id}/sessions/end", response_model=MemoryMaintenanceResponse)
def end_agent_session(agent_id: str, db: Session = Depends(get_db)):
    return get_memory_service(db).end_session(agent_id=agent_id, rebuild_index=True)


@app.post("/chat", response_model=ChatResponse)
def chat(data: ChatRequest, db: Session = Depends(get_db)):
    try:
        return BotCore(db).chat(agent_id=data.agent_id, message=data.message)
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
