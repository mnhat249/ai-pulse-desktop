from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

Vector = NDArray[np.float32]
TEXT_CHARS = 600


class Embedder(Protocol):
    model_name: str

    async def embed(self, texts: list[str]) -> list[Vector]:
        """Trả về vector đã chuẩn hóa độ dài 1, nên tích vô hướng chính là cosine."""
        ...


def embedding_text(title: str, text: str) -> str:
    return f"{title}. {text}"[:TEXT_CHARS].strip()


def normalize(vec: Vector) -> Vector:
    norm = float(np.linalg.norm(vec))
    return vec if norm == 0 else (vec / norm).astype(np.float32)


def to_bytes(vec: Vector) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(blob: bytes) -> Vector:
    return np.frombuffer(blob, dtype=np.float32)


class FastEmbedder:
    """fastembed (ONNX) chạy trên máy; model tải về `cache_dir` ở lần chạy đầu."""

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.model_name = model_name
        self._cache_dir = cache_dir
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            self._cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Nạp model embedding %s (lần đầu sẽ tải về)", self.model_name)
            self._model = TextEmbedding(model_name=self.model_name, cache_dir=str(self._cache_dir))
        return self._model

    def _embed_sync(self, texts: list[str]) -> list[Vector]:
        model = self._load()
        return [normalize(np.asarray(v, dtype=np.float32)) for v in model.embed(texts)]

    async def embed(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)
