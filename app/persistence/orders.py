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

    async def orders_by_state(self, state: str, limit: int = 20) -> list[dict]:
        return await self.db.fetch(
            "SELECT id, equipment, tasks, state, payload FROM orders WHERE state = %s "
            "ORDER BY updated_at DESC LIMIT %s",
            (state, limit),
        )

    async def orders_by_id(self, order_id: str) -> dict | None:
        return await self.db.fetchrow("SELECT * FROM orders WHERE id = %s", (order_id,))

    async def record_decision(self, order_id: str, decision: str, reasons: list[str],
                              plant_state: dict) -> None:
        await self.db.execute(
            "INSERT INTO decisions (order_id, decision, reasons, plant_state) VALUES (%s, %s, %s, %s)",
            (order_id, decision, Jsonb(reasons), Jsonb(plant_state)),
        )

    # ------------------------------------------------------------ entrega 2

    async def save_analysis(self, order_id: str, analysis: dict, *, correlation_id: str | None = None,
                            citations: list[str] | None = None, review: dict | None = None) -> None:
        await self.db.execute(
            """INSERT INTO order_analysis (order_id, correlation_id, causes, citations, review)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (order_id) DO UPDATE SET correlation_id = EXCLUDED.correlation_id,
                 causes = EXCLUDED.causes, citations = EXCLUDED.citations, review = EXCLUDED.review""",
            (order_id, correlation_id, Jsonb(analysis), Jsonb(citations or []), Jsonb(review or {})),
        )

    async def get_analysis(self, order_id: str) -> dict | None:
        return await self.db.fetchrow("SELECT * FROM order_analysis WHERE order_id = %s", (order_id,))

    async def save_closure(self, orden_id: str, nota_id: str | None, transcript: str,
                            parts: list[dict], differences: list[dict], *, correlation_id: str | None = None,
                            monto: float | None = None) -> None:
        await self.db.execute(
            """INSERT INTO closures (orden_id, nota_id, correlation_id, transcripcion, partes, diferencias,
                                     monto_habilita_usd)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (orden_id) DO UPDATE SET nota_id = EXCLUDED.nota_id,
                 transcripcion = EXCLUDED.transcripcion, partes = EXCLUDED.partes,
                 diferencias = EXCLUDED.diferencias, monto_habilita_usd = EXCLUDED.monto_habilita_usd""",
            (orden_id, nota_id, correlation_id, transcript, Jsonb(parts), Jsonb(differences), monto),
        )

    async def get_closure(self, orden_id: str) -> dict | None:
        return await self.db.fetchrow("SELECT * FROM closures WHERE orden_id = %s", (orden_id,))

    async def record_human_decision(self, order_id: str, decision: str, reasons: list[str],
                                    actor: str, role: str, *, correlation_id: str | None = None) -> None:
        await self.db.execute(
            """INSERT INTO decisions (order_id, decision, reasons, plant_state, actor, role, correlation_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (order_id, decision, Jsonb(reasons), Jsonb({}), actor, role, correlation_id),
        )

    async def human_decisions(self, order_id: str) -> list[dict]:
        return await self.db.fetch(
            "SELECT decision, reasons, actor, role, created_at FROM decisions "
            "WHERE order_id = %s ORDER BY id",
            (order_id,),
        )
