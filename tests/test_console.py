"""The operator console: the HTML page and the two JSON endpoints.

Nothing here is on the correction's path, so these are the only tests that cover it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.ui.console import STARTING, render_console

DATA = {
    "notes": [{"id": "NOTA-1", "ts": "2026-11-03T08:00:00-03:00", "status": "confirmed",
               "transcript": "la uno en ciento doce kilos"}],
    "events": [{"id": "E1", "ts": "2026-11-03T08:00:00-03:00", "type": "Escalado",
                "equipment": "B-101", "origin": "parte", "summary": "presión baja",
                "context": {"sections": [{"citation": "TX350-D §3.2"}]}}],
    "orders": [{"id": "O1", "equipment": "B-101", "state": "Aprobada", "tasks": ["T-B-EMP"],
                "payload": {"motivo": None}}],
    "pending_sync": 3,
    "usage": {"calls": 2, "input": 120, "output": 40, "latency": 900},
    "rag_chunks": 120,
}


def test_console_renders_the_part_the_events_and_the_citations():
    page = render_console(DATA, system_name="Planta Norte", link_up=False)
    assert "Planta Norte" in page
    assert "caído" in page            # the link state, not the optimistic default
    assert "NOTA-1" in page
    assert "TX350-D §3.2" in page     # every conclusion cites its manual section
    assert "B-101" in page and "T-B-EMP" in page


def test_console_escapes_operator_text():
    data = {**DATA, "notes": [{**DATA["notes"][0], "transcript": "<script>alert(1)</script>"}]}
    page = render_console(data, system_name="Planta", link_up=True)
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_endpoints_answer_before_the_context_exists():
    """Before startup (and after shutdown) the app has no context: it must say so.

    The client is used without its context manager on purpose: that would run the
    lifespan, which connects to Postgres and warms the ASR model.
    """
    client = TestClient(app)
    assert client.get("/health").status_code == 503
    assert client.get("/api/state").status_code == 503
    page = client.get("/")
    assert page.status_code == 200
    assert STARTING in page.text


def test_the_console_shows_the_orders_a_human_has_to_decide():
    data = {
        **DATA,
        "review_orders": [{
            "id": "OT-1", "equipment": "B-101", "state": "PendienteAprobacion", "tasks": ["T-B-ROD"],
            "payload": {"motivo": "requiere contratista (Servipat)", "estado": "PendienteAprobacion"},
            "causes": [{"code": "F03", "title": "Rodamiento de cigüeñal dañado", "confidence": "alta",
                        "citation": "MBP-4 §6.5"}],
            "correlation_id": "E1", "diferencias": [{"kind": "horas", "detail": "declara 26,5 h"}],
            "monto_habilita_usd": 1150.0,
        }],
    }
    page = render_console(data, system_name="Planta", link_up=True)
    assert "Órdenes para decidir" in page
    assert "Rodamiento de cigüeñal dañado" in page and "MBP-4 §6.5" in page
    assert "requiere contratista" in page
    assert "declara 26,5 h" in page and "USD 1150" in page
    assert "scripts/orden.py aprobar OT-1" in page


async def test_analysis_inputs_degrade_when_the_index_is_broken(snapshot):
    """A broken corpus must not keep the plant from starting."""
    from app.config import Settings
    from app.main import _analysis_inputs

    class BrokenRepo:
        async def rag_citations(self):
            raise RuntimeError("index unavailable")

    citations, prices = await _analysis_inputs(BrokenRepo(), Settings())
    assert citations.knows("MBP-4 §7.1")
    assert prices is None


async def test_a_pending_order_is_republished_after_a_restart_and_a_draft_is_not():
    """F3: what comes back after a power cut keeps its id and state; nothing goes back to Borrador."""
    from app.main import _resume_orders

    class Repo:
        def __init__(self):
            self.open = [
                {"id": "OT-PENDING", "payload": {"estado": "PendienteAprobacion", "equipo": "F-201B"}},
                {"id": "OT-DRAFT", "payload": {"estado": "Borrador", "equipo": "B-101"}},
                {"id": "OT-DONE", "payload": {"estado": "Certificada", "equipo": "B-101"}},
            ]
            self.removed: list[str] = []

        async def clear_draft_orders(self):
            drafts = [order for order in self.open if order["payload"]["estado"] == "Borrador"]
            self.removed = [order["id"] for order in drafts]
            self.open = [order for order in self.open if order not in drafts]
            return len(drafts)

        async def open_orders(self):
            return self.open

    class Publisher:
        def __init__(self):
            self.sent = []

        async def publish(self, topic, payload, sync=True):
            self.sent.append((topic, payload["estado"]))
            return True

    class Ctx:
        repo = Repo()
        publisher = Publisher()

    await _resume_orders(Ctx())
    assert [state for _topic, state in Ctx.publisher.sent] == ["PendienteAprobacion", "Certificada"]
    assert Ctx.repo.removed == ["OT-DRAFT"]
    assert all(order["id"] != "OT-DRAFT" for order in Ctx.repo.open)


def test_console_shows_the_closure_part_next_to_the_differences():
    data = {**DATA, "review_orders": [{
        "id": "O1", "equipment": "B-101", "state": "Ejecutada", "tasks": ["I-VIB"],
        "payload": {"motivo": None}, "causes": [],
        "parte": {"tasks_done": ["I-VIB"], "hours": 3.0,
                  "test_result": "probé a ciento diez kilos, sin pérdida"},
        "diferencias": [{"kind": "horas", "detail": "3 h sobre 2 incluidas"}],
        "monto_habilita_usd": 320.0,
    }]}
    page = render_console(data, system_name="Planta", link_up=True)
    assert "Parte de cierre" in page
    assert "ciento diez kilos" in page
    assert "horas" in page and "USD 320" in page


def test_the_console_offers_only_the_action_that_matches_state_and_role():
    from app.ui.console import _next_command

    def row(state, executor="propio"):
        return {"id": "OT-1", "state": state, "payload": {"ejecutor": executor}}

    assert "aprobar" in _next_command(row("PendienteAprobacion"))
    assert _next_command(row("Ejecutada", "propio")).startswith("cerrar")
    assert "certificar" in _next_command(row("Ejecutada", "Servipat"))
    assert "certificar" in _next_command(row("Observada", "Servipat"))
    assert _next_command(row("Aprobada")) == ""
