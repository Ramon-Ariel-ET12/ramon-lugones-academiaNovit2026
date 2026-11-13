"""Manual retrieval: pgvector hybrid in production, in-memory hybrid offline."""

from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.domain.equipment import EquipmentIndex, preprocess
from app.domain.models import PlantSnapshot
from app.domain.numbers import tokenize
from app.persistence.repository import Repository
from app.rag.bm25 import HybridIndex
from app.rag.corpus import bundled_fragments
from app.rag.indexer import Embedder
from app.rag.ranking import expand_query, rank

log = logging.getLogger(__name__)

DB_CANDIDATES = 40


def equipment_tags(query: str, snapshot: PlantSnapshot) -> set[str]:
    index = EquipmentIndex(snapshot)
    return {mention.tag for mention in index.find_mentions(tokenize(preprocess(query)))}


class ManualSearch:
    def __init__(self, repo: Repository, settings: Settings, snapshot: PlantSnapshot):
        self.repo = repo
        self.settings = settings
        self.snapshot = snapshot
        self.embedder = Embedder(settings.embedding_model)
        self._memory: HybridIndex | None = None

    def _memory_index(self) -> HybridIndex:
        if self._memory is None:
            self._memory = HybridIndex(bundled_fragments(self.settings), self.embedder)
        return self._memory

    async def search(self, query: str, k: int = 8) -> list[dict]:
        tags = equipment_tags(query, self.snapshot)
        try:
            if await self.repo.rag_count() > 0:
                return await self._search_db(query, k, tags)
        except Exception as exc:  # noqa: BLE001
            log.warning("database retrieval failed, using memory: %s", exc)
        return self._memory_index().search(query, k, tags)

    async def _search_db(self, query: str, k: int, tags: set[str]) -> list[dict]:
        lexical_rows = await self.repo.rag_lexical(expand_query(query), DB_CANDIDATES)
        rankings = [[row["citation"] for row in lexical_rows]]
        rows_by_citation = {row["citation"]: row for row in lexical_rows}
        try:
            query_vector = await asyncio.to_thread(self.embedder.query, query)
            vector_rows = await self.repo.rag_vector(query_vector, DB_CANDIDATES)
            rankings.append([row["citation"] for row in vector_rows])
            rows_by_citation.update({row["citation"]: row for row in vector_rows})
        except Exception as exc:  # noqa: BLE001
            log.warning("vector search unavailable: %s", exc)
        return rank(rankings, rows_by_citation, query, tags, k)
