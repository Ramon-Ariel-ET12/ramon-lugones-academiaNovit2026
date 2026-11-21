"""Test doubles shared by the suite.

Each double implements only the slice of the real collaborator the code under test
touches, and its defaults describe a healthy plant: a test overrides the one thing it
is about instead of restating the whole fake.
"""

from __future__ import annotations

STATE = {"ts": "2026-11-03T08:00:00-03:00", "bombas": [], "enlace_arriba": True, "hay_energia": True}


class FakePlant:
    """Plant HTTP client double: plant clock, historian samples and order history."""

    def __init__(self, *, samples: list[float] | None = None, orders: list[dict] | None = None,
                 state: dict | None = None, by_variable: dict[str, list[float]] | None = None) -> None:
        self.samples = [112.0, 113.0] if samples is None else samples
        self.by_variable = by_variable or {}
        self.orders = orders or []
        self.state_payload = dict(STATE if state is None else state)
        self.historian_calls: list[tuple[str, str]] = []

    async def state(self) -> dict:
        return self.state_payload

    async def historian(self, tag: str, variable: str, desde=None, hasta=None) -> list[dict]:
        self.historian_calls.append((tag, variable))
        values = self.by_variable.get(variable, self.samples)
        return [{"ts": "2026-11-03T08:00:00-03:00", "valor": float(value)} for value in values]

    async def order_history(self, equipo=None) -> list[dict]:
        return self.orders


class FakeRepository:
    """Repository double covering the notes/parts/tablet/events slice of the workflow."""

    def __init__(self) -> None:
        self.tablet: list[str] = []
        self.parts: list[dict] = []
        self.events: list[tuple[dict, dict | None]] = []
        self.updated: dict[str, dict] = {}
        self.replies: list[dict] = []
        self.attempts: list[dict] = []
        self.usage: list[dict] = []
        self.analysis: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.published_orders: list[dict] = []
        self.upserted: list[tuple[str, str]] = []
        self.created: set[str] = set()
        self.queued: list[str] = []

    async def create_note(self, note_id, ts, operator, walk_id, audio_url, photos, live):
        if note_id in self.created:
            return False
        self.created.add(note_id)
        return True

    async def get_part(self, note_id):
        return None

    async def set_note_status(self, *args):
        return None

    async def set_transcript(self, *args):
        return None

    async def save_part(self, note_id, status, rows, safety, attempts):
        self.parts.append({"note_id": note_id, "status": status, "rows": rows, "safety": safety})

    async def add_tablet_message(self, message_id, note_id, ts, kind, payload):
        # Idempotent by id, like the real insert (ON CONFLICT DO NOTHING RETURNING id).
        if message_id in self.tablet:
            return False
        self.tablet.append(message_id)
        return True

    async def add_attempt(self, attempt_id, note_id, message_id, kind, rows):
        self.attempts.append({"id": attempt_id, "kind": kind, "message_id": message_id})

    async def set_attempt_reply(self, message_id, reply):
        return None

    async def note_ids_for_message(self, message_id):
        return ["N1"]

    async def add_reply(self, reply_id, message_id, note_id, text, ts):
        self.replies.append({"id": reply_id, "message_id": message_id, "note_id": note_id,
                             "text": text, "ts": ts})

    async def insert_event(self, event, context=None):
        self.events.append((event, context))
        return True

    async def update_event_context(self, event_id, context):
        self.updated[event_id] = context

    async def record_usage(self, model, task, input_tokens, output_tokens, latency_ms, cost_usd=0.0):
        self.usage.append({"model": model, "task": task, "latency_ms": latency_ms})

    async def open_order(self, equipment, tasks):
        return None

    async def orders_by_id(self, order_id):
        return self.orders.get(order_id) if hasattr(self, "orders") else None

    async def save_analysis(self, order_id, analysis, *, correlation_id=None, citations=None, review=None):
        self.analysis[order_id] = {"order_id": order_id, "causes": analysis.get("causes", analysis),
                                   "correlation_id": correlation_id, "citations": citations or [],
                                   "review": review or {}}

    async def get_analysis(self, order_id):
        return self.analysis.get(order_id)

    async def upsert_order(self, order_id, equipment, tasks, state, payload):
        self.orders[order_id] = {"id": order_id, "equipment": equipment, "tasks": tasks,
                                 "state": state, "payload": payload}
        self.upserted.append((order_id, state))

    async def record_decision(self, *args):
        return None


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    async def publish(self, topic, payload, sync=True):
        self.messages.append((topic, payload))
        return True


class FakeMqtt:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def publish(self, topic, payload, qos=1):
        self.sent.append((topic, payload))


class FakeQueue:
    """Minimal sync-queue double: everything enqueued is pending until acknowledged."""

    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = items or []
        self.acked: list[int] = []
        self.bumped: list[int] = []

    async def enqueue(self, topic, payload):
        self.items.append({"id": len(self.items) + 1, "topic": topic, "payload": payload})

    async def pending_sync(self, limit=50):
        return self.items[:limit]

    async def ack_sync(self, ids):
        self.acked.extend(ids)

    async def bump_sync(self, ids):
        self.bumped.extend(ids)


def make_workflow(snapshot, materials, *, plant=None, repo=None, publisher=None):
    """A NoteWorkflow wired to the doubles (imported lazily to keep this module light)."""
    from app.config import Settings
    from app.processing.workflow import NoteWorkflow

    repo = repo or FakeRepository()
    publisher = publisher or FakePublisher()
    workflow = NoteWorkflow(Settings(), repo=repo, plant=plant, publisher=publisher,  # type: ignore[arg-type]
                            snapshot=snapshot, materials=materials, transcriber=None)
    return workflow, repo, publisher
