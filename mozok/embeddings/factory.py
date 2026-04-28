from mozok.config import get_settings
from mozok.embeddings.base import EmbeddingService
from mozok.embeddings.sentence_transformers_service import SentenceTransformersEmbeddingService


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service

    if _embedding_service is not None:
        return _embedding_service

    settings = get_settings()

    if settings.embedding_provider == "sentence_transformers":
        _embedding_service = SentenceTransformersEmbeddingService(settings.embedding_model)
        return _embedding_service

    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")
