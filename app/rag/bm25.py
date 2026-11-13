"""BM25 baseline (same tokenisation family as the course baseline) and the offline hybrid index."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol

from app.domain.numbers import strip_accents
from app.rag.corpus import canonical
from app.rag.ranking import CANDIDATES, expand_query, rank

STOPWORDS = frozenset(
    """
    a al algo como con cual cuales cuando de del el ella en es esta este esto hay la las le lo los mas me
    mi muy no o otra otras para pero por que se si sin sobre su sus un una uno y ya ante hace hacer tiene son fue ser
    puede qué cuál cuáles cómo cuánto cuántos dónde
    """.split()  # noqa: SIM905
)


def tokens(text: str) -> list[str]:
    text = strip_accents((text or "").lower())
    return [token[:6] for token in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text) if token not in STOPWORDS]


class BM25:
    def __init__(self, chunks: list[dict], k1: float = 1.4, b: float = 0.75):
        self.chunks = [canonical(chunk) for chunk in chunks]
        self.ids = [chunk["citation"] for chunk in self.chunks]
        self.docs = [Counter(tokens(f"{chunk['title']} {chunk['text']}")) for chunk in self.chunks]
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.average = sum(self.lengths) / len(self.lengths) if self.lengths else 1.0
        df = Counter(token for doc in self.docs for token in doc)
        n = len(self.docs)
        self.idf = {token: math.log(1 + (n - count + 0.5) / (count + 0.5)) for token, count in df.items()}
        self.k1, self.b = k1, b

    def search(self, query: str, k: int = 20) -> list[tuple[str, float]]:
        q = tokens(query)
        scored: list[tuple[float, int]] = []
        for index, doc in enumerate(self.docs):
            score = 0.0
            for token in q:
                if token in doc:
                    tf = doc[token]
                    score += self.idf[token] * tf * (self.k1 + 1) / (
                        tf + self.k1 * (1 - self.b + self.b * self.lengths[index] / self.average)
                    )
            if score > 0:
                scored.append((score, index))
        scored.sort(reverse=True)
        return [(self.ids[index], score) for score, index in scored[:k]]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    numerator = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return numerator / (na * nb) if na and nb else 0.0


class Embedder(Protocol):
    """The slice of ``rag.indexer.Embedder`` the index needs (tests inject a stub)."""

    def passages(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class HybridIndex:
    """Offline hybrid retrieval over canonical chunks (BM25 + optional vectors)."""

    def __init__(self, fragments: list[dict], embedder: Embedder | None = None):
        self.chunks = [canonical(fragment) for fragment in fragments]
        self.embedder = embedder
        self._bm25 = BM25(self.chunks)
        self.by_citation = {chunk["citation"]: chunk for chunk in self.chunks}
        self._vectors: list[list[float]] | None = None

    def _ensure_vectors(self) -> bool:
        if self._vectors is not None:
            return True
        if self.embedder is None:
            return False
        try:
            texts = [f"{chunk['title']}\n{chunk['text']}" for chunk in self.chunks]
            self._vectors = self.embedder.passages(texts)
            return True
        except Exception:  # noqa: BLE001
            self._vectors = None
            return False

    def search(self, query: str, k: int = 10, equipment_tags: set[str] | None = None) -> list[dict]:
        rankings = [[citation for citation, _ in self._bm25.search(expand_query(query), CANDIDATES)]]
        if self._ensure_vectors() and self.embedder is not None and self._vectors is not None:
            query_vector = self.embedder.query(query)
            scored = [(cosine(query_vector, vector), chunk["citation"])
                      for vector, chunk in zip(self._vectors, self.chunks, strict=False)]
            scored.sort(reverse=True)
            rankings.append([citation for _, citation in scored[:CANDIDATES]])
        return rank(rankings, self.by_citation, query, equipment_tags or set(), k)

    def citations(self, query: str, k: int = 10) -> list[str]:
        return [hit["citation"] for hit in self.search(query, k)]
