from sqlalchemy.orm import Session
from mozok.config import get_settings
from mozok.embeddings.factory import get_embedding_service
from mozok.faiss_index.store import FaissMemoryIndex
from mozok.llm.ollama_openai import OllamaOpenAIClient
from mozok.memory.service import MemoryService
from mozok.schemas.chat import ChatResponse
from mozok.schemas.memory import MemoryCreate
from mozok.core.prompt_builder import build_system_prompt


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
        self.memory = get_memory_service(db)
        self.llm = OllamaOpenAIClient()

    def chat(self, agent_id: str, message: str) -> ChatResponse:
        memories = self.memory.search(agent_id=agent_id, query=message, limit=5)
        system_prompt = build_system_prompt(agent_id, memories)

        response_text = self.llm.chat(system_prompt=system_prompt, user_message=message)

        # Store the user message and the bot response as episodic memories.
        self.memory.add_memory(
            MemoryCreate(
                agent_id=agent_id,
                content=f"User said: {message}",
                memory_type="dialogue",
                importance=5,
            )
        )
        self.memory.add_memory(
            MemoryCreate(
                agent_id=agent_id,
                content=f"Bot replied: {response_text}",
                memory_type="dialogue",
                importance=5,
            )
        )

        return ChatResponse(
            agent_id=agent_id,
            response=response_text,
            used_memory_ids=[m.id for m in memories],
        )
