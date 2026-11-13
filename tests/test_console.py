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
