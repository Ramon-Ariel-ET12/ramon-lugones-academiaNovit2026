from __future__ import annotations

from app.domain.orders import order_id, order_payload, propose_tasks
from app.domain.parser import parse_transcript
from app.domain.rules import Decision, PlantState, build_proposal, evaluate


def state(**pumps):
    base = {"B-101": "marcha", "B-102": "marcha", "B-103": "parada"}
    base.update(pumps)
    return PlantState(pumps=base)


def test_filter_cartridges_approved_when_stock_and_cost_fit(materials, snapshot):
    proposal = build_proposal("F-201A", ["T-F-CAR"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert decision.approved, decision.reasons
    assert proposal.executor == "propio"
    assert proposal.parts == [{"codigo": "FC-CART-25", "cantidad": 48.0}]


def test_filter_b_without_stock_goes_pending(materials):
    proposal = build_proposal("F-201B", ["T-F-CAR"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert not decision.approved
    assert any("sin stock de FC-CART-10" in reason for reason in decision.reasons)
    assert decision.motive


def test_standard_pump_task_approved_when_reserve_available(materials):
    proposal = build_proposal("B-101", ["T-B-EMP"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert decision.approved, decision.reasons


def test_pump_stop_without_reserve_reduces_injection(materials):
    plant = state(**{"B-103": "mantenimiento"})
    proposal = build_proposal("B-101", ["T-B-EMP"], materials, plant)
    decision = evaluate(proposal, materials, plant)
    assert not decision.approved
    assert any("reduce la inyección" in reason for reason in decision.reasons)


def test_oil_top_up_is_approved(materials):
    proposal = build_proposal("B-101", ["T-B-ACE"], materials, state())
    assert evaluate(proposal, materials, state()).approved


def test_inspection_task_is_not_standard(materials):
    proposal = build_proposal("B-101", ["I-VIB"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert not decision.approved
    assert any("no estándar" in reason for reason in decision.reasons)
    assert any("contratista" in reason for reason in decision.reasons)
    assert proposal.executor != "propio"


def test_cost_limit(materials):
    proposal = build_proposal("B-101", ["T-B-VAL"], materials, state())
    proposal.parts = [{"codigo": "TX-VAL-KIT", "cantidad": 2}]
    decision = evaluate(proposal, materials, state())
    assert any("costo de repuestos" in reason for reason in decision.reasons)


def test_structural_damage_forces_human_review(materials):
    proposal = build_proposal("B-101", ["T-B-EMP"], materials, state(), structural_damage=True)
    decision = evaluate(proposal, materials, state())
    assert not decision.approved
    assert any("daño estructural" in reason for reason in decision.reasons)


def test_task_proposal_from_rows(snapshot, ts):
    rows = parse_transcript("La dos pierde bastante por la empaquetadura.", snapshot, note_id="N", ts=ts).rows
    assert propose_tasks("B-102", rows) == ["T-B-EMP"]
    differential = parse_transcript("El filtro A me dio uno coma tres de diferencial.", snapshot,
                                    note_id="N", ts=ts).rows
    assert propose_tasks("F-201A", differential) == ["T-F-CAR"]
    oil = parse_transcript("La uno tiene el visor de aceite bajo.", snapshot, note_id="N", ts=ts).rows
    assert propose_tasks("B-101", oil) == ["T-B-ACE"]
    noise = parse_transcript("La uno hace un golpeteo metálico.", snapshot, note_id="N", ts=ts).rows
    assert propose_tasks("B-101", noise) == ["I-VIB"]
    tripped = parse_transcript("La dos está disparada, no arranca.", snapshot, note_id="N", ts=ts).rows
    assert propose_tasks("B-102", tripped) == ["I-VAL"]


def test_order_id_is_deterministic(materials):
    assert order_id("F-201A", ["T-F-CAR"], "evt-1") == order_id("F-201A", ["T-F-CAR"], "evt-1")
    assert order_id("F-201A", ["T-F-CAR"], "evt-1") != order_id("F-201A", ["T-F-CAR"], "evt-2")


def test_order_payload_shape(materials, ts):
    proposal = build_proposal("F-201A", ["T-F-CAR"], materials, state())
    decision = Decision(approved=True)
    payload = order_payload("oid", ts, "Aprobada", proposal, decision, ["e1"])
    assert payload["estado"] == "Aprobada"
    assert payload["equipo"] == "F-201A"
    assert payload["detiene_equipo"] is False
    assert payload["reduce_inyeccion"] is False
    assert payload["motivo"] is None
    pending = order_payload("oid", ts, "PendienteAprobacion", proposal,
                            Decision(approved=False, reasons=["falta stock"]), ["e1"])
    assert pending["motivo"] == "falta stock"


# ---------------------------------------------------------------- bordes del anexo 2


def test_the_cost_limit_is_strictly_less_than_2500(materials):
    """USD 2.499 is approved; USD 2.500 is not (the Anexo: costo menor a USD 2.500)."""
    from app.domain.rules import MAX_PART_COST_USD, Proposal

    class PricedMaterials:
        """The real catalogue with one priced part, to hit the boundary exactly."""

        def __init__(self, cost: float):
            self._materials = materials
            self._cost = cost

        def __getattr__(self, name):
            return getattr(self._materials, name)

        def part_cost(self, code, quantity):
            return self._cost * quantity

    def proposal() -> Proposal:
        return Proposal(equipment="B-101", tasks=["T-B-EMP"],
                        parts=[{"codigo": "TX-EMP-KIT", "cantidad": 1}],
                        executor="propio", stops_equipment=True)

    assert MAX_PART_COST_USD == 2500.0
    below = evaluate(proposal(), PricedMaterials(2499.0), state())  # type: ignore[arg-type]
    assert below.approved, below.reasons

    at_limit = evaluate(proposal(), PricedMaterials(2500.0), state())  # type: ignore[arg-type]
    assert not at_limit.approved
    assert any("costo" in reason for reason in at_limit.reasons)


def test_the_valve_kit_is_under_the_limit_and_approved_when_the_reserve_is_idle(materials):
    """T-B-VAL on a running pump that stops it: only approvable with the reserve running."""
    proposal = build_proposal("B-102", ["T-B-VAL"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert proposal.parts == [{"codigo": "TX-VAL-KIT", "cantidad": 1.0}]
    assert materials.part_cost("TX-VAL-KIT", 1) == 1900.0
    assert decision.approved, decision.reasons


def test_the_crankshaft_bearing_kit_has_no_stock_in_the_yacimiento(materials):
    proposal = build_proposal("B-101", ["T-B-ROD"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert not decision.approved
    assert any("contratista" in reason for reason in decision.reasons)
