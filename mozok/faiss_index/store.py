from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import faiss


class FaissMemoryIndex:
    """FAISS index wrapper.

    Important design choice:
    - SQL stores true memory records.
    - FAISS stores vectors and maps vector rows to SQL memory IDs.
    - If this index becomes inconsistent, rebuild it from SQL.
    """

    def __init__(self, index_path: str, mapping_path: str):
        self.index_path = Path(index_path)
        self.mapping_path = Path(mapping_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.mapping_path.parent.mkdir(parents=True, exist_ok=True)

        self.index: faiss.Index | None = None
        self.row_to_memory_id: list[int] = []

        self._load_if_exists()

    def _load_if_exists(self) -> None:
        if self.index_path.exists() and self.mapping_path.exists():
            self.index = faiss.read_index(str(self.index_path))
            self.row_to_memory_id = json.loads(self.mapping_path.read_text(encoding="utf-8"))

    def _ensure_index(self, dim: int) -> None:
        if self.index is None:
            # Inner product works well with normalized embeddings.
            self.index = faiss.IndexFlatIP(dim)

    def add(self, memory_id: int, vector: np.ndarray) -> None:
        vector = self._as_2d_float32(vector)
        self._ensure_index(vector.shape[1])
        self.index.add(vector)
        self.row_to_memory_id.append(memory_id)
        self.save()

    def search(self, vector: np.ndarray, limit: int = 5) -> list[tuple[int, float]]:
        if self.index is None or self.index.ntotal == 0:
            return []

        vector = self._as_2d_float32(vector)
        search_limit = min(max(limit, 1), self.index.ntotal)

        scores, rows = self.index.search(vector, search_limit)

        results: list[tuple[int, float]] = []
        for row, score in zip(rows[0], scores[0]):
            if row < 0:
                continue
            memory_id = self.row_to_memory_id[row]
            results.append((memory_id, float(score)))
        return results

    def save(self) -> None:
        if self.index is not None:
            faiss.write_index(self.index, str(self.index_path))
        self.mapping_path.write_text(json.dumps(self.row_to_memory_id), encoding="utf-8")

    def reset(self, dim: int) -> None:
        self.index = faiss.IndexFlatIP(dim)
        self.row_to_memory_id = []
        self.save()

    @staticmethod
    def _as_2d_float32(vector: np.ndarray) -> np.ndarray:
        arr = np.asarray(vector, dtype="float32")
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr
