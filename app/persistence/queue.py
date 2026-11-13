"""The outbound queue that survives a link outage, plus the usage accounting.

Everything that has to leave the plant is enqueued here and acknowledged only when the
cloud replica has stored it."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from app.persistence.base import DbRepository


class QueueRepository(DbRepository):
    async def enqueue(self, topic: str, payload: dict) -> None:
        await self.db.execute("INSERT INTO sync_queue (topic, payload) VALUES (%s, %s)",
                              (topic, Jsonb(payload)))

    async def pending_sync(self, limit: int = 50) -> list[dict]:
        return await self.db.fetch(
            "SELECT id, topic, payload, attempts FROM sync_queue WHERE acked = false ORDER BY id LIMIT %s",
            (limit,),
        )

    async def pending_count(self) -> int:
        row = await self.db.fetchrow("SELECT count(*) AS n FROM sync_queue WHERE acked = false")
        return int(row["n"]) if row else 0

    async def ack_sync(self, ids: list[int]) -> None:
        if not ids:
            return
        await self.db.execute("UPDATE sync_queue SET acked = true WHERE id = ANY(%s)", (ids,))

    async def bump_sync(self, ids: list[int]) -> None:
        if not ids:
            return
        await self.db.execute("UPDATE sync_queue SET attempts = attempts + 1 WHERE id = ANY(%s)", (ids,))

    async def record_usage(self, model: str, task: str, input_tokens: int, output_tokens: int,
                           latency_ms: int, cost_usd: float = 0.0) -> None:
        await self.db.execute(
            """INSERT INTO usage_log (model, task, input_tokens, output_tokens, latency_ms, cost_usd)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (model, task, input_tokens, output_tokens, latency_ms, cost_usd),
        )

    async def usage_summary(self) -> dict:
        row = await self.db.fetchrow(
            """SELECT coalesce(sum(input_tokens),0) AS input, coalesce(sum(output_tokens),0) AS output,
                      coalesce(sum(latency_ms),0) AS latency, count(*) AS calls FROM usage_log"""
        )
        return row or {"input": 0, "output": 0, "latency": 0, "calls": 0}

