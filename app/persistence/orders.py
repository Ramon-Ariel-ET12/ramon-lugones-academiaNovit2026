"""Work orders and the decision that approved or held each one.

The states are the contract's: an order only leaves ``PendienteAprobacion`` through the
planner, so the open states are what the duplicate and resume checks look at."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from app.persistence.base import DbRepository

TERMINAL_ORDER_STATES = {"Rechazada", "Cerrada", "Certificada"}
OPEN_ORDER_STATES = {"Borrador", "PendienteAprobacion", "Aprobada", "Ejecutada", "Observada"}

class OrdersRepository(DbRepository):
    async def upsert_order(self, order_id: str, equipment: str, tasks: list[str], state: str,
                           payload: dict) -> None:
        await self.db.execute(
            """INSERT INTO orders (id, equipment, tasks, state, payload)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state, payload = EXCLUDED.payload,
                 tasks = EXCLUDED.tasks, updated_at = now()""",
            (order_id, equipment, Jsonb(tasks), state, Jsonb(payload)),
        )

    async def open_order(self, equipment: str, tasks: list[str]) -> dict | None:
        wanted = set(tasks)
        for row in await self.db.fetch(
            "SELECT id, equipment, tasks, state FROM orders WHERE state = ANY(%s) AND equipment = %s",
            (list(OPEN_ORDER_STATES), equipment),
        ):
            if set(row["tasks"] or []) == wanted:
                return row
        return None

    async def open_orders(self) -> list[dict]:
        return await self.db.fetch(
            "SELECT id, equipment, tasks, state, payload FROM orders WHERE state = ANY(%s) ORDER BY created_at",
            (list(OPEN_ORDER_STATES),),
        )

    async def orders_by_id(self, order_id: str) -> dict | None:
        return await self.db.fetchrow("SELECT * FROM orders WHERE id = %s", (order_id,))

    async def record_decision(self, order_id: str, decision: str, reasons: list[str],
                              plant_state: dict) -> None:
        await self.db.execute(
            "INSERT INTO decisions (order_id, decision, reasons, plant_state) VALUES (%s, %s, %s, %s)",
            (order_id, decision, Jsonb(reasons), Jsonb(plant_state)),
        )

