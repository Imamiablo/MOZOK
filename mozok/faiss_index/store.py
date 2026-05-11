from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def _load_faiss():
    try:
        import faiss
    except Exception as exc:  # noqa: BLE001 - preserve the real dependency error.
        raise RuntimeError(
            "Could not import faiss. Install requirements.txt before using "
            "semantic memory indexing/search."
        ) from exc
    return faiss


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

        self.index: Any | None = None
        self.row_to_memory_id: list[int] = []

        self._load_if_exists()

    def _load_if_exists(self) -> None:
        if self.index_path.exists() and self.mapping_path.exists():
            faiss = _load_faiss()
            self.index = faiss.read_index(str(self.index_path))
            self.row_to_memory_id = json.loads(self.mapping_path.read_text(encoding="utf-8"))

    def _ensure_index(self, dim: int) -> None:
        if self.index is None:
            # Inner product works well with normalised embeddings.
            faiss = _load_faiss()
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
            try:
                memory_id = self.row_to_memory_id[row]
            except IndexError:
                continue
            results.append((memory_id, float(score)))
        return results

    def clear(self) -> None:
        """Remove all vectors and persist an empty mapping.

        FAISS cannot create a truly empty dimensionless index, so we remove the
        stored index file and keep the in-memory index unset until the next add().
        """

        self.index = None
        self.row_to_memory_id = []
        if self.index_path.exists():
            self.index_path.unlink()
        self.mapping_path.write_text(json.dumps(self.row_to_memory_id), encoding="utf-8")

    def save(self) -> None:
        if self.index is not None:
            faiss = _load_faiss()
            faiss.write_index(self.index, str(self.index_path))
        self.mapping_path.write_text(json.dumps(self.row_to_memory_id), encoding="utf-8")

    def reset(self, dim: int) -> None:
        faiss = _load_faiss()
        self.index = faiss.IndexFlatIP(dim)
        self.row_to_memory_id = []
        self.save()

    @staticmethod
    def _as_2d_float32(vector: np.ndarray) -> np.ndarray:
        arr = np.asarray(vector, dtype="float32")
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr
