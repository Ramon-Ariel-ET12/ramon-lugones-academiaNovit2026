"""The manual index: chunks, embeddings and the two candidate rankings."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from app.persistence.base import DbRepository


def _vector(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"

class RagRepository(DbRepository):
    async def rag_count(self) -> int:
        row = await self.db.fetchrow("SELECT count(*) AS n FROM rag_chunks")
        return int(row["n"]) if row else 0

    async def rag_upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        rows = [
            (
                chunk["id"], chunk["doc"], chunk.get("number", ""), chunk.get("title", ""),
                chunk.get("section_key", ""), chunk.get("page"), chunk.get("current", True),
                chunk.get("manufacturer", ""), Jsonb(chunk.get("equipment", [])),
                chunk["citation"], chunk["text"], chunk["content_hash"], _vector(embedding),
                chunk["text"],
            )
            for chunk, embedding in zip(chunks, embeddings, strict=False)
        ]
        async with self.db.pool.connection() as conn, conn.cursor() as cur:  # type: ignore[union-attr]
            await cur.executemany(
                """INSERT INTO rag_chunks
                     (id, doc, number, title, section_key, page, current, manufacturer, equipment,
                      citation, text, content_hash, embedding, tsv)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector,
                           to_tsvector('spanish', %s))
                   ON CONFLICT (id) DO UPDATE SET
                     text = EXCLUDED.text, content_hash = EXCLUDED.content_hash,
                     embedding = EXCLUDED.embedding, tsv = EXCLUDED.tsv,
                     current = EXCLUDED.current, equipment = EXCLUDED.equipment""",
                rows,
            )

    async def rag_lexical(self, query: str, limit: int = 40) -> list[dict]:
        return await self.db.fetch(
            """SELECT id, citation, doc, title, section_key, current, manufacturer, equipment, text,
                      ts_rank_cd(tsv, websearch_to_tsquery('spanish', %s)) AS score
               FROM rag_chunks
               WHERE current IS NOT FALSE AND tsv @@ websearch_to_tsquery('spanish', %s)
               ORDER BY score DESC LIMIT %s""",
            (query, query, limit),
        )

    async def rag_vector(self, embedding: list[float], limit: int = 40) -> list[dict]:
        return await self.db.fetch(
            """SELECT id, citation, doc, title, section_key, current, manufacturer, equipment, text,
                      1 - (embedding <=> %s::vector) AS score
               FROM rag_chunks WHERE embedding IS NOT NULL AND current IS NOT FALSE
               ORDER BY embedding <=> %s::vector LIMIT %s""",
            (_vector(embedding), _vector(embedding), limit),
        )

    async def rag_refresh_metadata(self, chunks: list[dict]) -> None:
        """Update derived metadata in place, without recomputing embeddings."""
        if not chunks:
            return
        rows = [
            (Jsonb(chunk.get("equipment", [])), chunk.get("manufacturer", ""),
             chunk.get("section_key", ""), chunk.get("current", True), chunk["id"])
            for chunk in chunks
        ]
        async with self.db.pool.connection() as conn, conn.cursor() as cur:  # type: ignore[union-attr]
            await cur.executemany(
                """UPDATE rag_chunks SET
                     equipment = %s::jsonb,
                     manufacturer = %s,
                     section_key = %s,
                     current = %s
                   WHERE id = %s""",
                rows,
            )
