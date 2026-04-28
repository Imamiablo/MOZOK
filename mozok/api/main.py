from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from mozok.core.bot_core import BotCore, get_memory_service
from mozok.db.session import get_db
from mozok.schemas.chat import ChatRequest, ChatResponse
from mozok.schemas.memory import (
    MemoryCreate,
    MemoryRead,
    MemorySearchRequest,
    MemorySearchResult,
)

app = FastAPI(title="Mozok", version="0.1.0")


@app.get("/")
def root():
    return {
        "name": "Mozok",
        "status": "alive",
        "description": "Reusable bot-brain engine using PostgreSQL + FAISS.",
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


@app.post("/memories/rebuild-index")
def rebuild_index(db: Session = Depends(get_db)):
    count = get_memory_service(db).rebuild_index()
    return {"rebuilt": True, "indexed_memories": count}


@app.post("/chat", response_model=ChatResponse)
def chat(data: ChatRequest, db: Session = Depends(get_db)):
    return BotCore(db).chat(agent_id=data.agent_id, message=data.message)
