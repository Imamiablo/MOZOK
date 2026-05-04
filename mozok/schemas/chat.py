from typing import Any

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

    enforce_token_budget: bool = Field(
        default=True,
        description="If true, trim selected context so the prompt stays within the configured approximate token budget.",
    )
    max_prompt_tokens: int = Field(
        default=6000,
        ge=100,
        le=200000,
        description="Approximate total model-side budget for prompt + reserved response.",
    )
    reserved_response_tokens: int = Field(
        default=1000,
        ge=0,
        le=100000,
        description="Approximate tokens reserved for the model response. The prompt target is max_prompt_tokens - reserved_response_tokens.",
    )
    allow_core_trimming: bool = Field(
        default=False,
        description="If false, core/profile memories are protected from token-budget trimming.",
    )


class ChatResponse(BaseModel):
    agent_id: str
    session_id: str
    response: str
    used_memory_ids: list[int]
    used_short_term_messages_count: int = 0
    dedup_removed_memories_count: int = 0
    context_budget: dict[str, Any] | None = None
