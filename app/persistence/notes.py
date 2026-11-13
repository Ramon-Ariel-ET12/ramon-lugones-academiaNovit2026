"""Notes, the part they produce and the review attempts.

One note arrives from the plant, becomes a part (one row per equipment and variable)
and may be reviewed several times before it is confirmed. The tablet message and the
operator's reply belong to that same conversation."""

from __future__ import annotations

from datetime import datetime

from psycopg.types.json import Jsonb

from app.persistence.base import DbRepository


class NotesRepository(DbRepository):
    async def create_note(self, note_id: str, ts: datetime, operator: str, walk_id: str,
                          audio_url: str | None, photos: list[str], live: bool) -> bool:
        row = await self.db.fetchrow(
            """INSERT INTO notes (id, ts, operator, walk_id, audio_url, photos, live)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING
               RETURNING id""",
            (note_id, ts, operator, walk_id, audio_url, Jsonb(photos), live),
        )
        return row is not None

    async def reset_stuck_notes(self) -> None:
        await self.db.execute("UPDATE notes SET status = 'received' WHERE status = 'processing'")

    async def pending_notes(self) -> list[dict]:
        return await self.db.fetch(
            """SELECT n.* FROM notes n
               WHERE n.status = 'received'
                 AND NOT EXISTS (SELECT 1 FROM parts p WHERE p.note_id = n.id
                                 AND p.status IN ('confirmed', 'confirmed_with_differences'))
               ORDER BY n.ts, n.received_at"""
        )

    async def set_note_status(self, note_id: str, status: str) -> None:
        await self.db.execute(
            "UPDATE notes SET status = %s, updated_at = now() WHERE id = %s", (status, note_id)
        )

    async def set_transcript(self, note_id: str, transcript: str) -> None:
        await self.db.execute("UPDATE notes SET transcript = %s, updated_at = now() WHERE id = %s",
                              (transcript, note_id))

    async def save_part(self, note_id: str, status: str, rows: list[dict], safety: str | None,
                        attempts: int) -> None:
        await self.db.execute(
            """INSERT INTO parts (note_id, status, rows, safety, attempts)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (note_id) DO UPDATE SET status = EXCLUDED.status, rows = EXCLUDED.rows,
                 safety = EXCLUDED.safety, attempts = EXCLUDED.attempts, updated_at = now()""",
            (note_id, status, Jsonb(rows), safety, attempts),
        )

    async def get_part(self, note_id: str) -> dict | None:
        return await self.db.fetchrow("SELECT * FROM parts WHERE note_id = %s", (note_id,))

    async def add_attempt(self, attempt_id: str, note_id: str, message_id: str | None, kind: str,
                          rows: list[dict]) -> None:
        await self.db.execute(
            """INSERT INTO attempts (id, note_id, message_id, kind, rows)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            (attempt_id, note_id, message_id, kind, Jsonb(rows)),
        )

    async def set_attempt_reply(self, message_id: str, reply: str) -> None:
        await self.db.execute("UPDATE attempts SET reply = %s WHERE message_id = %s", (reply, message_id))

    async def add_tablet_message(self, message_id: str, note_id: str, ts: datetime, kind: str,
                                 payload: dict) -> bool:
        row = await self.db.fetchrow(
            """INSERT INTO tablet_messages (id, note_id, ts, kind, payload)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING RETURNING id""",
            (message_id, note_id, ts, kind, Jsonb(payload)),
        )
        return row is not None

    async def add_reply(self, reply_id: str, message_id: str, note_id: str | None, text: str,
                        ts: datetime | None) -> None:
        await self.db.execute(
            """INSERT INTO replies (id, message_id, note_id, text, ts)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            (reply_id, message_id, note_id, text, ts),
        )

    async def note_ids_for_message(self, message_id: str) -> list[str]:
        row = await self.db.fetchrow("SELECT note_id FROM tablet_messages WHERE id = %s", (message_id,))
        return [row["note_id"]] if row and row["note_id"] else []

