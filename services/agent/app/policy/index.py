"""The policy index: every chunk and FAQ with its vector, saved as one JSON file.

Search is hybrid: cosine similarity (meaning: "go overdrawn" ~ "below $0") and
BM25 keywords (exact terms: "NSF"), merged with reciprocal rank fusion. Fifty
chunks fit in memory many times over, so there is no database to run.
"""

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.policy.chunker import Chunk

_WORD = re.compile(r"[a-z0-9$%.]+")


def tokens(text: str) -> list[str]:
    return [t.strip(".") for t in _WORD.findall(text.lower()) if t.strip(".")]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


@dataclass(frozen=True)
class Faq:
    question: str
    answer: str
    policy_id: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    similarity: float  # cosine, 0..1
    fused: float  # reciprocal rank fusion score across both searches


@dataclass
class PolicyIndex:
    embed_model: str
    chunks: list[Chunk] = field(default_factory=list)
    chunk_vectors: list[list[float]] = field(default_factory=list)
    faqs: list[Faq] = field(default_factory=list)
    faq_vectors: list[list[float]] = field(default_factory=list)
    file_hashes: dict[str, str] = field(default_factory=dict)

    # ---- persistence ---------------------------------------------------------
    def save(self, path: Path) -> None:
        data = {
            "embed_model": self.embed_model,
            "chunks": [asdict(c) for c in self.chunks],
            "chunk_vectors": self.chunk_vectors,
            "faqs": [asdict(f) for f in self.faqs],
            "faq_vectors": self.faq_vectors,
            "file_hashes": self.file_hashes,
        }
        path.write_text(json.dumps(data))

    @classmethod
    def load(cls, path: Path) -> "PolicyIndex":
        data = json.loads(path.read_text())
        return cls(
            embed_model=data["embed_model"],
            chunks=[Chunk(**c) for c in data["chunks"]],
            chunk_vectors=data["chunk_vectors"],
            faqs=[Faq(**f) for f in data["faqs"]],
            faq_vectors=data["faq_vectors"],
            file_hashes=data.get("file_hashes", {}),
        )

    # ---- search ----------------------------------------------------------------
    def faq_match(self, query_vector: list[float]) -> tuple[Faq, float] | None:
        """The closest approved FAQ and how close it is."""
        if not self.faqs:
            return None
        scored = [
            (cosine(query_vector, v), f) for f, v in zip(self.faqs, self.faq_vectors, strict=True)
        ]
        similarity, faq = max(scored, key=lambda s: s[0])
        return faq, similarity

    def search(self, query_vector: list[float], query_text: str, k: int = 3) -> list[Hit]:
        if not self.chunks:
            return []
        sims = [cosine(query_vector, v) for v in self.chunk_vectors]
        by_vector = sorted(range(len(self.chunks)), key=lambda i: -sims[i])[:10]
        by_keyword = sorted(range(len(self.chunks)), key=lambda i: -self._bm25(i, query_text))[:10]
        fused: dict[int, float] = {}
        for ranking in (by_vector, by_keyword):
            for rank, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank)  # reciprocal rank fusion
        best = sorted(fused, key=lambda i: -fused[i])[:k]
        return [Hit(self.chunks[i], sims[i], fused[i]) for i in best]

    def _bm25(self, i: int, query: str, k1: float = 1.5, b: float = 0.75) -> float:
        docs = [tokens(f"{c.title} {c.section} {c.text}") for c in self.chunks]
        avg = sum(len(d) for d in docs) / len(docs)
        doc = docs[i]
        counts = Counter(doc)
        score = 0.0
        for term in set(tokens(query)):
            containing = sum(1 for d in docs if term in d)
            if not containing:
                continue
            idf = math.log(1 + (len(docs) - containing + 0.5) / (containing + 0.5))
            tf = counts[term]
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(doc) / avg))
        return score
