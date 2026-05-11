from __future__ import annotations

import numpy as np

from mozok.embeddings.base import EmbeddingService


class SentenceTransformersEmbeddingService(EmbeddingService):
    """Local embedding backend using sentence-transformers.

    The heavy sentence-transformers dependency is imported lazily so that
    FastAPI/OpenAPI tests and routes that do not embed text can still import
    the application without loading the full ML stack. Actual embedding still
    fails clearly if the dependency is missing or broken.
    """

    def __init__(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # noqa: BLE001 - preserve the real dependency error.
            raise RuntimeError(
                "Could not load sentence-transformers. Install the pinned "
                "requirements in requirements.txt, or set another embedding "
                "provider before creating embeddings."
            ) from exc

        self.model = SentenceTransformer(model_name)

    def embed_text(self, text: str) -> np.ndarray:
        vector = self.model.encode(text, normalize_embeddings=True)
        return np.asarray(vector, dtype="float32")
