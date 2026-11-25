"""The photo-analysis queue.

A photo that cannot be analysed (link down, model unavailable) is queued here and
retried; nothing else in the pipeline waits for it.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from app.persistence.base import DbRepository

MAX_ATTEMPTS = 5


class PhotoQueueRepository(DbRepository):
    async def enqueue_photo(self, photo_id: str, photo: str) -> str:
        await self.db.execute(
            """INSERT INTO photo_analysis (id, photo) VALUES (%s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (photo_id, photo),
        )
        return photo_id

    async def pending_photos(self, limit: int = 20) -> list[dict]:
        return await self.db.fetch(
            """SELECT id, photo, attempts FROM photo_analysis
               WHERE status = 'pending' AND attempts < %s ORDER BY created_at LIMIT %s""",
            (MAX_ATTEMPTS, limit),
        )

    async def mark_analysed(self, photo_id: str, result: dict) -> None:
        await self.db.execute(
            """UPDATE photo_analysis SET status = 'done', result = %s, updated_at = now()
               WHERE id = %s""",
            (Jsonb(result), photo_id),
        )

    async def mark_failed(self, photo_id: str) -> None:
        await self.db.execute(
            """UPDATE photo_analysis SET attempts = attempts + 1, updated_at = now(),
                   status = CASE WHEN attempts + 1 >= %s THEN 'failed' ELSE 'pending' END
               WHERE id = %s""",
            (MAX_ATTEMPTS, photo_id),
        )

