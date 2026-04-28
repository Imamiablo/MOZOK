import numpy as np
from sentence_transformers import SentenceTransformer
from mozok.embeddings.base import EmbeddingService


class SentenceTransformersEmbeddingService(EmbeddingService):
    """Local embedding backend using sentence-transformers."""

    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)

    def embed_text(self, text: str) -> np.ndarray:
        vector = self.model.encode(text, normalize_embeddings=True)
        return np.asarray(vector, dtype="float32")
