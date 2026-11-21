"""The order pipeline end to end (Entrega 2).

Escalated event → evidence → analysis → reviewer → rules → published order. The tests use
the real snapshot, the real materials, the real corpus citations and the real rules, with
only the plant, the repository and the publisher doubled.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis.review import CorpusCitations
from app.config import Settings
from app.domain.models import ExtractedRow
from app.domain.rules import PlantState
from app.workflow.pipeline import OrderPipeline
from tests import fakes

CORPUS = Path(__file__).resolve().parent.parent / "academia2026-tp" / "datos" / "documentos" / "fragmentos.jsonl"


@pytest.fixture(scope="module")
def citations() -> CorpusCitations:
    return CorpusCitations.bundled(CORPUS)


def pipeline(snapshot, materials, citations, plant=None) -> tuple[OrderPipeline, fakes.FakeRepository, fakes.FakePublisher]:
    repo, publisher = fakes.FakeRepository(), fakes.FakePublisher()
    plant = plant or fakes.FakePlant()
    built = OrderPipeline(Settings(), repo, plant, publisher, snapshot, materials, citations)  # type: ignore[arg-type]
    return built, repo, publisher


def escalated(equipment: str, event_id: str = "E1") -> dict:
    return {"id": event_id, "ts": "2026-11-04T06:30:00-03:00", "tipo": "Escalado", "equipo": equipment,
            "origen": "parte", "parte_id": "NOTA-1", "nota_ids": ["NOTA-1"], "resumen": "anomalía"}


def row(tag: str, variable: str, value: float | None = None, unit: str | None = None,
        observation: str | None = None) -> ExtractedRow:
    return ExtractedRow(tag=tag, variable=variable, value=value, unit=unit, observation=observation)


def published_states(publisher: fakes.FakePublisher) -> list[str]:
    return [payload["estado"] for topic, payload in publisher.messages if topic == "sistema/ordenes"]


# ------------------------------------------------------------------ orders


async def test_a_standard_own_repair_is_approved(snapshot, materials, citations):
    built, repo, publisher = pipeline(snapshot, materials, citations)
    result = await built.run(escalated("B-101"),
                             rows=[row("B-101", "goteo_empaquetadura", observation="goteo en el prensa")],
                             photos=[], sensor_variable=None,
                             plant_state=PlantState(pumps={"B-101": "marcha", "B-103": "parada"}),
                             link_ok=True)
    assert result is not None
    assert result["estado"] == "Aprobada"
    assert result["tareas"] == ["T-B-EMP"]
    assert published_states(publisher) == ["Borrador", "Aprobada"]
    analysis = repo.analysis[result["id"]]
    assert analysis["causes"][0]["code"] == "F01"
    assert "MBP-4 §6.3" in analysis["citations"]
    assert analysis["review"]["parts"][0]["codigo"] == "TX-EMP-KIT"


async def test_a_contractor_repair_goes_to_the_planner(snapshot, materials, citations):
    plant = fakes.FakePlant(by_variable={"vibracion": [8.0] * 20, "temperatura_aceite": [82.0] * 20,
                                         "presion_succion": [1.6] * 20, "presion_descarga": [112.0] * 20})
    built, _repo, _publisher = pipeline(snapshot, materials, citations, plant)
    result = await built.run(
        escalated("B-101"), rows=[row("B-101", "temperatura_rodamiento_ir", 88.0, "degC")], photos=[],
        sensor_variable="vibracion", plant_state=PlantState(pumps={"B-101": "marcha", "B-103": "parada"}),
        link_ok=True)
    assert result is not None
    assert result["estado"] == "PendienteAprobacion"
    assert result["tareas"] == ["T-B-ROD"]
    assert result["motivo"]
    assert "contratista" in result["motivo"] or "no estándar" in result["motivo"]


async def test_a_filter_with_cartridges_pending_for_stock(snapshot, materials, citations):
    built, _repo, _ = pipeline(snapshot, materials, citations)
    result = await built.run(
        escalated("F-201B"), rows=[row("F-201B", "presion_diferencial", 3.4, "kg/cm2")], photos=[],
        sensor_variable="presion_diferencial", plant_state=PlantState(pumps={"B-101": "marcha"}),
        link_ok=True)
    assert result is not None
    assert result["tareas"] == ["T-F-CAR"]
    assert result["estado"] in ("Aprobada", "PendienteAprobacion")


async def test_a_pump_that_stops_without_a_reserve_reduces_injection(snapshot, materials, citations):
    built, _, _ = pipeline(snapshot, materials, citations)
    result = await built.run(
        escalated("B-102"), rows=[row("B-102", "presion_diferencial", 3.9, "kg/cm2")], photos=[],
        sensor_variable="vibracion", plant_state=PlantState(pumps={"B-102": "marcha", "B-103": "mantenimiento"}),
        link_ok=True)
    assert result is not None
    assert result["estado"] == "PendienteAprobacion"
    assert "reduce la inyección" in result["motivo"]


async def test_a_drifting_sensor_creates_no_order(snapshot, materials, citations):
    """F10 does not demand a work order (the Anexo is explicit)."""
    plant = fakes.FakePlant(by_variable={"vibracion": [8.0] * 20, "temperatura_aceite": [55.0] * 20,
                                         "presion_succion": [1.8] * 20, "presion_descarga": [112.0] * 20})
    built, _repo, publisher = pipeline(snapshot, materials, citations, plant)
    result = await built.run(
        escalated("B-101"), rows=[row("B-101", "estado", observation="sin novedad")], photos=[],
        sensor_variable="vibracion", plant_state=PlantState(pumps={"B-101": "marcha"}), link_ok=True)
    assert result is None
    assert publisher.messages == []


async def test_the_reviewer_blocks_an_order_it_cannot_back(snapshot, materials, citations):
    built, _repo, publisher = pipeline(snapshot, materials, citations)
    original = built.__class__.analyse

    async def broken(self, event, rows, sensor_variable, context):
        analysis = await original(self, event, rows, sensor_variable, context)
        analysis.causes[0].citation = "MBP-9 §1.1"
        analysis.findings = [f for f in analysis.findings if f.kind != "citation_missing"]
        from app.analysis.review import review

        analysis.findings = review(analysis.equipment, analysis.causes, analysis.parts, materials, citations)
        return analysis

    built.analyse = broken.__get__(built)  # type: ignore[method-assign]
    result = await built.run(escalated("B-101"),
                             rows=[row("B-101", "goteo_empaquetadura", observation="goteo")], photos=[],
                             sensor_variable=None,
                             plant_state=PlantState(pumps={"B-101": "marcha", "B-103": "parada"}),
                             link_ok=True)
    assert result is None
    assert publisher.messages == []


async def test_a_second_event_for_the_same_open_order_does_not_duplicate(snapshot, materials, citations):
    built, repo, publisher = pipeline(snapshot, materials, citations)

    async def open_exists(equipment, tasks):
        return {"id": "OT-EXISTING", "equipment": equipment, "tasks": tasks, "state": "Aprobada"}

    repo.open_order = open_exists  # type: ignore[method-assign]
    result = await built.run(escalated("B-101"),
                             rows=[row("B-101", "goteo_empaquetadura", observation="goteo")], photos=[],
                             sensor_variable=None,
                             plant_state=PlantState(pumps={"B-101": "marcha", "B-103": "parada"}),
                             link_ok=True)
    assert result is None
    assert publisher.messages == []


async def test_the_analysis_and_the_order_share_the_correlation_id(snapshot, materials, citations):
    built, repo, _ = pipeline(snapshot, materials, citations)
    result = await built.run(escalated("B-101", event_id="EVENT-XYZ"),
                             rows=[row("B-101", "goteo_empaquetadura", observation="goteo")], photos=[],
                             sensor_variable=None,
                             plant_state=PlantState(pumps={"B-101": "marcha", "B-103": "parada"}),
                             link_ok=True)
    assert result is not None
    assert repo.analysis[result["id"]]["correlation_id"] == "EVENT-XYZ"
    assert result["evento_ids"] == ["EVENT-XYZ"]


async def test_an_equipment_without_a_task_gets_no_order(snapshot, materials, citations):
    built, _, publisher = pipeline(snapshot, materials, citations)
    result = await built.run(escalated("TK-301"), rows=[], photos=[], sensor_variable="nivel",
                             plant_state=PlantState(), link_ok=True)
    assert result is None
    assert publisher.messages == []


async def test_the_order_does_not_run_the_vector_search(snapshot, materials, citations):
    """The causes cite MBP-4 themselves; a vector query here would load the embedder."""
    calls: list[str] = []

    class Search:
        async def search(self, query, k=8):
            calls.append(query)
            return [{"citation": "MBP-4 §7.1"}]

    repo, publisher = fakes.FakeRepository(), fakes.FakePublisher()
    built = OrderPipeline(Settings(), repo, fakes.FakePlant(), publisher, snapshot, materials,  # type: ignore[arg-type]
                          citations, Search())  # type: ignore[arg-type]
    await built.run(escalated("B-101"),
                    rows=[row("B-101", "goteo_empaquetadura", observation="goteo")], photos=[],
                    sensor_variable=None,
                    plant_state=PlantState(pumps={"B-101": "marcha", "B-103": "parada"}), link_ok=True)
    assert calls == []
