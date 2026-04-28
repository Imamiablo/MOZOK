from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    agent_id: str = Field(..., examples=["cat_001"])
    content: str
    memory_type: str = "event"
    importance: int = Field(default=5, ge=1, le=10)
    emotional_weight: float = 0.0
    metadata: dict = Field(default_factory=dict)


class MemoryRead(BaseModel):
    id: int
    agent_id: str
    content: str
    memory_type: str
    importance: int
    emotional_weight: float
    metadata: dict

    class Config:
        from_attributes = True


class MemorySearchRequest(BaseModel):
    agent_id: str
    query: str
    limit: int = Field(default=5, ge=1, le=50)
    memory_type: str | None = None


class MemorySearchResult(BaseModel):
    id: int
    content: str
    memory_type: str
    importance: int
    score: float
