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
    ) -> ChatResponse:
        agent = self.agent_service.get_or_create_default_agent(agent_id)

        context = self.context_builder.build(
            agent=agent,
            user_message=message,
            session_id=session_id,
            short_term_limit=short_term_limit,
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
        )