from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    agent_id: str = Field(..., examples=["cat_001"])
    message: str


class ChatResponse(BaseModel):
    agent_id: str
    response: str
    used_memory_ids: list[int]
