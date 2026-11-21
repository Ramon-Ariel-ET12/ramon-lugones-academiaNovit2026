"""The persistence façade the application talks to.

Each aggregate lives in its own module (notes, events, orders, queue, RAG) and the
façade composes them, so a caller keeps one object while the SQL stays grouped by the
thing it is about. Only the console query is cross-aggregate and lives here.
"""

from __future__ import annotations

from typing import Any

from app.persistence.events import EventsRepository
from app.persistence.notes import NotesRepository
from app.persistence.orders import OrdersRepository
from app.persistence.queue import QueueRepository
from app.persistence.rag import RagRepository
from app.persistence.vision import PhotoQueueRepository


class Repository(NotesRepository, EventsRepository, OrdersRepository, QueueRepository, RagRepository,
                 PhotoQueueRepository):
    async def console_state(self) -> dict[str, Any]:
        """Everything the operator console shows, in one round of queries."""
        notes = await self.db.fetch(
            "SELECT id, ts, status, transcript FROM notes ORDER BY ts DESC LIMIT 10"
        )
        events = await self.db.fetch(
            "SELECT id, ts, type, equipment, origin, summary, context FROM events ORDER BY created_at DESC LIMIT 15"
        )
        orders = await self.db.fetch(
            "SELECT id, equipment, state, tasks, payload FROM orders ORDER BY updated_at DESC LIMIT 15"
        )
        # Orders a human still has to decide, with the analysis that justifies them.
        review = await self.db.fetch(
            """SELECT o.id, o.equipment, o.state, o.tasks, o.payload, a.causes, a.correlation_id
               FROM orders o LEFT JOIN order_analysis a ON a.order_id = o.id
               WHERE o.state IN ('PendienteAprobacion', 'Aprobada', 'Ejecutada', 'Observada')
               ORDER BY o.updated_at DESC LIMIT 10"""
        )
        return {
            "notes": notes,
            "events": events,
            "orders": orders,
            "review_orders": review,
            "pending_sync": await self.pending_count(),
            "usage": await self.usage_summary(),
            "rag_chunks": await self.rag_count(),
        }
