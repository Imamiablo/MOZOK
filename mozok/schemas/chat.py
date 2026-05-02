from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    agent_id: str = Field(..., examples=["cat_001"])
    message: str
    session_id: str = Field(
        "default",
        description="Conversation/session key for short-term working memory.",
        examples=["default", "game_session_001"],
    )
    short_term_limit: int = Field(
        20,
        ge=0,
        le=40,
        description="How many recent short-term messages to include in the prompt. Use 0 to disable.",
    )


class ChatResponse(BaseModel):
    agent_id: str
    session_id: str
    response: str
    used_memory_ids: list[int]
    used_short_term_messages_count: int
