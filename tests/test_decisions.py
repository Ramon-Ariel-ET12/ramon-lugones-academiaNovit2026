"""Routing of plant messages and the human decision matrix (Entrega 2)."""

from __future__ import annotations

from typing import Any

import pytest

from app.workflow.decisions import DecisionError, OrderDecisionService
from app.workflow.router import Routed, classify, route_note, route_topic, sensor_parts

ORDER: dict[str, Any] = {
    "id": "OT-1",
    "equipment": "B-101",
    "tasks": ["T-B-EMP"],
    "state": "PendienteAprobacion",
    "payload": {"id": "OT-1", "ts": "2026-11-04T06:30:00-03:00", "estado": "PendienteAprobacion",
                "equipo": "B-101", "evento_ids": ["E1"], "tareas": ["T-B-EMP"],
                "detiene_equipo": True, "reduce_inyeccion": False, "ejecutor": "propio",
                "repuestos": [{"codigo": "TX-EMP-KIT", "cantidad": 1}], "motivo": "sin stock",
                "habilita": None, "monto_habilita_usd": None},
}


class FakeOrders:
    """The slice of the repository the decision service needs."""

    def __init__(self, orders: dict[str, dict]):
        self.orders = orders
        self.decisions: list[dict] = []
        self.analysis: dict[str, dict] = {}

    async def orders_by_id(self, order_id):
        return self.orders.get(order_id)

    async def upsert_order(self, order_id, equipment, tasks, state, payload):
        self.orders[order_id] = {"id": order_id, "equipment": equipment, "tasks": tasks,
                                 "state": state, "payload": payload}

    async def get_analysis(self, order_id):
        return self.analysis.get(order_id)

    async def record_human_decision(self, order_id, decision, reasons, actor, role, correlation_id=None):
        self.decisions.append({"order_id": order_id, "decision": decision, "actor": actor, "role": role,
                              "correlation_id": correlation_id})


class FakePublisher:
    def __init__(self, accept: bool = True):
        self.accept = accept
        self.published: list[tuple[str, dict]] = []

    async def publish(self, topic, payload, sync=True):
        if not self.accept:
            return False
        self.published.append((topic, payload))
        return True


class FakePrices:
    def amount_for(self, tasks, *, equipment_count=1, started_at=None, emergency=False):
        return 780.0


def service(state: str = "PendienteAprobacion", *, accept: bool = True, prices=None):
    order = dict(ORDER, state=state)
    order["payload"] = dict(ORDER["payload"], estado=state)
    repo, publisher = FakeOrders({"OT-1": order}), FakePublisher(accept)
    return OrderDecisionService(repo, publisher, prices=prices or FakePrices()), repo, publisher  # type: ignore[arg-type]


# ------------------------------------------------------------------ routing


def test_route_by_topic():
    assert route_topic("planta/recorridas") == "parte"
    assert route_topic("planta/sensores/B-101") == "sensor"
    assert route_topic("planta/respuestas") == "respuesta"
    assert route_topic("planta/cierres") == "cierre"
    assert route_topic("planta/energia") == "energia"
    assert route_topic("sistema/inventado") == "desconocido"


def test_a_part_is_unsafe_only_when_the_local_detector_says_so():
    assert route_note(safety=None) == "parte"
    assert route_note(safety="S1") == "seguridad"


def test_sensor_parts_reject_a_malformed_sample():
    assert sensor_parts({"tag": "B-101", "variable": "vibracion"}) == ("B-101", "vibracion")
    assert sensor_parts({"tag": "B-101"}) is None
    assert sensor_parts({}) is None


def test_classify_keeps_the_payload():
    routed = classify("planta/cierres", {"orden_id": "OT-1"})
    assert isinstance(routed, Routed)
    assert routed.route == "cierre" and routed.payload == {"orden_id": "OT-1"}


# ------------------------------------------------------------------ decisions


async def test_planner_approves_a_pending_order():
    svc, repo, publisher = service()
    result = await svc.decide("OT-1", role="planificador", action="approve", actor="Ana")
    assert result.state == "Aprobada"
    assert repo.orders["OT-1"]["state"] == "Aprobada"
    topic, payload = publisher.published[-1]
    assert topic == "sistema/ordenes" and payload["estado"] == "Aprobada"
    assert repo.decisions[-1] == {"order_id": "OT-1", "decision": "Aprobada", "actor": "Ana",
                                  "role": "planificador", "correlation_id": None}


async def test_reject_demands_a_motive():
    svc, repo, _ = service()
    with pytest.raises(DecisionError):
        await svc.decide("OT-1", role="planificador", action="reject", actor="Ana")
    result = await svc.decide("OT-1", role="planificador", action="reject", actor="Ana",
                             motive="no hay reserva")
    assert result.state == "Rechazada"
    assert repo.orders["OT-1"]["payload"]["motivo"] == "no hay reserva"


async def test_the_wrong_role_cannot_move_the_order():
    svc, _, _ = service()
    with pytest.raises(DecisionError):
        await svc.decide("OT-1", role="supervisor", action="close", actor="Luis")
    with pytest.raises(DecisionError):
        await svc.decide("OT-1", role="inspector", action="certify", actor="Luis")
    with pytest.raises(DecisionError):
        await svc.decide("OT-1", role="planificador", action="firmar", actor="Ana")


async def test_approve_does_not_apply_to_an_already_approved_order():
    svc, _, _ = service("Aprobada")
    with pytest.raises(DecisionError):
        await svc.decide("OT-1", role="planificador", action="approve", actor="Ana")


async def test_only_the_supervisor_closes_and_only_after_execution():
    svc, repo, _ = service("Ejecutada")
    result = await svc.decide("OT-1", role="supervisor", action="close", actor="Luis")
    assert result.state == "Cerrada"
    assert repo.orders["OT-1"]["state"] == "Cerrada"


async def test_inspector_observes_with_a_motive_and_certifies_with_the_contract_amount():
    svc, repo, _ = service("Ejecutada")
    observed = await svc.decide("OT-1", role="inspector", action="observe", actor="Ines",
                                motive="declara horas de más")
    assert observed.state == "Observada"
    assert repo.orders["OT-1"]["payload"]["motivo"] == "declara horas de más"

    certified = await svc.decide("OT-1", role="inspector", action="certify", actor="Ines",
                                 habilita="HAB-2025-0001")
    assert certified.state == "Certificada"
    payload = repo.orders["OT-1"]["payload"]
    assert payload["habilita"] == "HAB-2025-0001"
    assert payload["monto_habilita_usd"] == 780.0
    assert payload["motivo"] is None


async def test_certify_without_a_known_contract_price_is_refused():
    class NoPrice:
        def amount_for(self, *args, **kwargs):
            return None

    svc, repo, _ = service("Ejecutada", prices=NoPrice())
    with pytest.raises(DecisionError):
        await svc.decide("OT-1", role="inspector", action="certify", actor="Ines", habilita="HAB-1")
    assert repo.orders["OT-1"]["state"] == "Ejecutada"


async def test_the_decision_is_recorded_with_the_correlation_id_of_the_analysis():
    svc, repo, _ = service()
    repo.analysis["OT-1"] = {"correlation_id": "E1"}
    await svc.decide("OT-1", role="planificador", action="approve", actor="Ana")
    assert repo.decisions[-1]["correlation_id"] == "E1"


async def test_a_payload_the_contract_rejects_does_not_change_the_order():
    svc, repo, _ = service(accept=False)
    with pytest.raises(DecisionError):
        await svc.decide("OT-1", role="planificador", action="approve", actor="Ana")
    assert repo.orders["OT-1"]["state"] == "PendienteAprobacion"
