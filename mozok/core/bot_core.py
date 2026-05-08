from sqlalchemy.orm import Session

from mozok.agent.service import AgentService
from mozok.config import get_settings
from mozok.context.context_builder import ContextBuilder
from mozok.embeddings.factory import get_embedding_service
from mozok.faiss_index.store import FaissMemoryIndex
from mozok.llm.ollama_openai import OllamaOpenAIClient
from mozok.memory.service import MemoryService
from mozok.memory.short_term_memory import SHORT_TERM_MEMORY
from mozok.schemas.chat import ChatResponse
from mozok.schemas.memory import MemoryCreate


def get_memory_service(db: Session) -> MemoryService:
    settings = get_settings()
    embedding_service = get_embedding_service()
    vector_index = FaissMemoryIndex(
        index_path=settings.faiss_index_path,
        mapping_path=settings.faiss_mapping_path,
    )
    return MemoryService(db, embedding_service, vector_index)


class BotCore:
    """High-level bot core.

    This is what game/chat/desktop-pet adapters should eventually call.
    """

    def __init__(self, db: Session):
        self.db = db
        self.memory = get_memory_service(db)
        self.llm = OllamaOpenAIClient()
        self.agent_service = AgentService(db)
        self.context_builder = ContextBuilder(db=db, memory_service=self.memory)

    def chat(
        self,
        agent_id: str,
        message: str,
        session_id: str = "default",
        short_term_limit: int = 20,
        enforce_token_budget: bool = True,
        max_prompt_tokens: int = 6000,
        reserved_response_tokens: int = 1000,
        allow_core_trimming: bool = False,
        world_id: str = "default",
        lorebook_limit: int = 10,
        include_public_lore: bool = True,
        include_narrator_only_lore: bool = False,
        include_entity_states: bool = True,
        entity_state_limit: int = 10,
        entity_state_kind: str | None = None,
        entity_state_entity_id: str | None = None,
    ) -> ChatResponse:
        agent = self.agent_service.get_or_create_default_agent(agent_id)

        context = self.context_builder.build(
            agent=agent,
            user_message=message,
            session_id=session_id,
            short_term_limit=short_term_limit,
            enforce_token_budget=enforce_token_budget,
            max_prompt_tokens=max_prompt_tokens,
            reserved_response_tokens=reserved_response_tokens,
            allow_core_trimming=allow_core_trimming,
            world_id=world_id,
            lorebook_limit=lorebook_limit,
            include_public_lore=include_public_lore,
            include_narrator_only_lore=include_narrator_only_lore,
            include_entity_states=include_entity_states,
            entity_state_limit=entity_state_limit,
            entity_state_kind=entity_state_kind,
            entity_state_entity_id=entity_state_entity_id,
        )

        system_prompt = context.to_system_prompt()
        response_text = self.llm.chat(system_prompt=system_prompt, user_message=message)

        # Update short-term working memory after the model responds.
        SHORT_TERM_MEMORY.add_message(
            agent_id=agent_id,
            session_id=session_id,
            role="user",
            content=message,
        )
        SHORT_TERM_MEMORY.add_message(
            agent_id=agent_id,
            session_id=session_id,
            role="assistant",
            content=response_text,
        )

        # Raw dialogue is useful for later consolidation, but it should not be
        # treated as an important long-term fact. Maintenance can later summarize
        # raw dialogue into semantic memories and archive the noisy originals.
        self.memory.add_memory(
            MemoryCreate(
                agent_id=agent_id,
                session_id=session_id,
                content=f"User said: {message}",
                memory_type="raw",
                importance=2,
                metadata={"speaker": "user"},
            )
        )
        self.memory.add_memory(
            MemoryCreate(
                agent_id=agent_id,
                session_id=session_id,
                content=f"Bot replied: {response_text}",
                memory_type="raw",
                importance=2,
                metadata={"speaker": "bot"},
            )
        )

        return ChatResponse(
            agent_id=agent_id,
            session_id=session_id,
            response=response_text,
            used_memory_ids=context.used_memory_ids(),
            used_short_term_messages_count=context.used_short_term_count(),
            used_lorebook_entry_ids=context.used_lorebook_entry_ids(),
            used_lorebook_entries_count=len(context.lorebook_items),
            used_entity_state_ids=context.used_entity_state_ids(),
            used_entity_states_count=len(context.entity_state_items),
            dedup_removed_memories_count=context.dedup_removed_count(),
            context_budget=context.context_budget.to_dict() if context.context_budget else None,
        )
