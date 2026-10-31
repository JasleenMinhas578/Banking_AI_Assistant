"""Embeddings from Ollama's nomic-embed-text: 768 numbers per text, local and free."""

from typing import Protocol

import httpx2


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(self, model: str, base_url: str, timeout_seconds: float = 60.0) -> None:
        self.model = model
        self.base_url = base_url
        self.timeout = timeout_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx2.AsyncClient(timeout=self.timeout) as http:
            response = await http.post(
                f"{self.base_url}/api/embed", json={"model": self.model, "input": texts}
            )
            response.raise_for_status()
        return [list(map(float, vector)) for vector in response.json()["embeddings"]]
