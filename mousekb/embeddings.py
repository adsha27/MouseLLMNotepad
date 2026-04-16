from __future__ import annotations

import threading
from pathlib import Path

try:
    from fastembed import TextEmbedding
except ImportError:  # pragma: no cover - exercised by fallback behavior
    TextEmbedding = None


EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"


class LocalEmbeddingEngine:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self._model = None
        self._disabled = False

    def embed_text(self, text: str) -> list[float] | None:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return None

        model = self._ensure_model()
        if model is None:
            return None

        try:
            vector = next(iter(model.embed([cleaned], batch_size=1)))
        except Exception:  # pragma: no cover - exercised by fallback behavior
            self._disabled = True
            self._model = None
            return None

        return [float(value) for value in vector.tolist()]

    def _ensure_model(self):
        if self._disabled:
            return None

        with self._lock:
            if self._disabled:
                return None
            if self._model is not None:
                return self._model
            if TextEmbedding is None:
                self._disabled = True
                return None

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            try:
                self._model = TextEmbedding(
                    model_name=EMBEDDING_MODEL_NAME,
                    cache_dir=str(self.cache_dir),
                    lazy_load=True,
                )
            except Exception:  # pragma: no cover - exercised by fallback behavior
                self._disabled = True
                self._model = None
            return self._model
