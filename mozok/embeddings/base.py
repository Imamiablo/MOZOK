from abc import ABC, abstractmethod
import numpy as np


class EmbeddingService(ABC):
    """Base interface for embedding backends."""

    @abstractmethod
    def embed_text(self, text: str) -> np.ndarray:
        """Return a single float32 vector for text."""
        raise NotImplementedError
