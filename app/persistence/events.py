"""Events published to the plant and the sensor episodes that produced them."""

from __future__ import annotations

from datetime import datetime

from psycopg.types.json import Jsonb

from app.persistence.base import DbRepository


class EventsRepository(DbRepository):
    async def insert_event(self, event: dict, context: dict | None = None) -> bool:
        row = await self.db.fetchrow(
            """INSERT INTO events (id, ts, type, equipment, origin, part_id, note_ids, summary, context)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING RETURNING id""",
            (
                event["id"], event["ts"], event["tipo"], event.get("equipo"), event["origen"],
                event.get("parte_id"), Jsonb(event.get("nota_ids", [])), event["resumen"],
                Jsonb(context) if context is not None else None,
            ),
        )
        return row is not None

    async def update_event_context(self, event_id: str, context: dict) -> None:
        await self.db.execute("UPDATE events SET context = %s WHERE id = %s", (Jsonb(context), event_id))

    async def sensor_episodes(self) -> list[dict]:
        return await self.db.fetch(
            "SELECT tag, variable, active, since, event_id FROM sensor_state WHERE active"
        )

    async def set_sensor_event(self, tag: str, variable: str, event_id: str | None, since: datetime | None) -> None:
        await self.db.execute(
            """INSERT INTO sensor_state (tag, variable, active, since, event_id)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (tag, variable) DO UPDATE SET active = EXCLUDED.active,
                 since = EXCLUDED.since, event_id = EXCLUDED.event_id, updated_at = now()""",
            (tag, variable, event_id is not None, since, event_id),
        )

