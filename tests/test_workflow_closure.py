"""The closure path and the durability hooks (Entrega 2).

These are the two places where the official run found real failures: a closure that is
transcribed and compared, and the orders that come back after a power cut.
"""

from __future__ import annotations

import pytest

from app.domain.billing import PriceList
from app.processing.asr import Transcription
from app.processing.workflow import NoteWorkflow
from tests import fakes

CERT = "Cierro la orden OT 25 0001. Hice análisis de vibraciones con colector. Medí las tres bombas. Fueron 3 horas."
ORDER_PAYLOAD = {
    "id": "OT-1", "ts": "2026-11-05T10:00:00-03:00", "estado": "Ejecutada", "equipo": "B-101",
    "evento_ids": ["E1"], "tareas": ["I-VIB"], "detiene_equipo": False, "reduce_inyeccion": False,
    "ejecutor": "propio", "repuestos": [], "motivo": None, "habilita": None, "monto_habilita_usd": None,
}


class FakeTranscriber:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def transcribe(self, path, on_partial=None):
        self.calls += 1
        return Transcription(text=self.text, duration_s=1.0, latency_ms=10, model="fake")


class ClosureRepo(fakes.FakeRepository):
    def __init__(self, order: dict | None = None):
        super().__init__()
        self.order = order
        self.closure: dict | None = None
        self.republished: list[dict] = []

    async def orders_by_id(self, order_id):
        return None if self.order is None else {"id": order_id, "equipment": "B-101",
                                                "tasks": ["I-VIB"], "state": "Ejecutada",
                                                "payload": dict(self.order)}

    async def save_closure(self, orden_id, nota_id, transcript, parts, differences, *, correlation_id=None,
                           monto=None):
        self.closure = {"orden_id": orden_id, "nota_id": nota_id, "transcript": transcript,
                        "parts": parts, "differences": differences, "correlation_id": correlation_id,
                        "monto": monto}

    async def get_closure(self, orden_id):
        return self.closure

    async def get_analysis(self, orden_id):
        return {"correlation_id": "E1"}


async def workflow_with(repo, materials, *, text: str = CERT, prices=None) -> NoteWorkflow:
    class Plant:
        async def download(self, url):
            return b"RIFF0000WAVE"

    return NoteWorkflow(__import__("app.config", fromlist=["Settings"]).Settings(), repo, Plant(),  # type: ignore[arg-type]
                         fakes.FakePublisher(), object(), materials, FakeTranscriber(text),  # type: ignore[arg-type]
                         prices=prices)


def prices() -> PriceList:
    from pathlib import Path

    contract = Path(__file__).resolve().parent.parent / "academia2026-tp" / "datos" / "documentos" / "contrato" / "CT-SVP-2025.md"
    return PriceList.from_markdown(contract.read_text(encoding="utf-8"))


async def test_the_closure_is_transcribed_compared_and_the_order_executed(materials):
    repo = ClosureRepo(dict(ORDER_PAYLOAD))
    workflow = await workflow_with(repo, materials, prices=prices())
    await workflow.handle_closure({"id": "CIERRE-OT-1", "ts": "2026-11-05T18:00:00-03:00",
                                   "orden_id": "OT-1", "tecnico": "Lucas", "empresa": "propio",
                                   "audio_url": "/media/audios/CIERRE-OT-1.wav", "fotos": []})
    assert repo.orders["OT-1"]["state"] == "Ejecutada"
    assert repo.closure is not None
    assert repo.closure["transcript"].startswith("Cierro la orden")
    assert repo.closure["monto"] == pytest.approx(320.0)
    assert repo.closure["correlation_id"] == "E1"


async def test_a_second_delivery_of_the_same_closure_does_nothing(materials):
    repo = ClosureRepo(dict(ORDER_PAYLOAD))
    workflow = await workflow_with(repo, materials, prices=prices())
    payload = {"id": "CIERRE-OT-1", "ts": "2026-11-05T18:00:00-03:00", "orden_id": "OT-1",
               "tecnico": "Lucas", "empresa": "propio", "audio_url": "/x.wav", "fotos": []}
    await workflow.handle_closure(payload)
    first = dict(repo.closure or {})
    calls = workflow.transcriber.calls
    await workflow.handle_closure(payload)
    assert workflow.transcriber.calls == calls, "the transcript must not be repeated"
    assert repo.closure == first


async def test_a_closure_for_an_unknown_order_is_ignored(materials):
    repo = ClosureRepo(None)
    workflow = await workflow_with(repo, materials, prices=prices())
    await workflow.handle_closure({"id": "CIERRE-X", "ts": "2026-11-05T18:00:00-03:00",
                                   "orden_id": "OT-NO", "tecnico": "Lucas", "empresa": "propio",
                                   "audio_url": None, "fotos": []})
    assert repo.closure is None
    assert repo.orders == {}


async def test_without_a_price_list_the_order_still_closes(materials):
    repo = ClosureRepo(dict(ORDER_PAYLOAD))
    workflow = await workflow_with(repo, materials, prices=None)
    await workflow.handle_closure({"id": "CIERRE-OT-1", "ts": "2026-11-05T18:00:00-03:00",
                                   "orden_id": "OT-1", "tecnico": "Lucas", "empresa": "propio",
                                   "audio_url": "/x.wav", "fotos": []})
    assert repo.orders["OT-1"]["state"] == "Ejecutada"
    assert repo.closure is None


# ------------------------------------------------------------------ structural damage


async def test_structural_damage_marks_the_equipment_before_the_photos_are_archived(materials):
    from app.domain.models import ExtractedRow, PartDraft
    from app.vision.models import PhotoVerdict

    class Photos:
        async def structural_damage(self, photos):
            return False

        async def submit(self, note_id, photos):
            return [PhotoVerdict(photo="/media/fotos/1.jpg", structural_damage=True, severity="grave")]

    repo = ClosureRepo(None)
    workflow = await workflow_with(repo, materials)
    workflow.photos = Photos()  # type: ignore[assignment]
    note = __import__("app.contract", fromlist=["NotaRecorrida"]).NotaRecorrida.model_validate(
        {"id": "NOTA-1", "ts": "2026-11-05T09:00:00-03:00", "operador": "Héctor", "audio_url": None,
         "fotos": ["/media/fotos/1.jpg"], "recorrida_id": "R1"})
    draft = PartDraft(note_id="NOTA-1", ts=note.ts, photos=list(note.fotos),
                      rows=[ExtractedRow(tag="B-101", variable="condicion_insegura",
                                         observation="agua a presión", photo="/media/fotos/1.jpg")])
    await workflow._check_structural_damage(note, draft)
    assert "B-101" in workflow.structural_damage


async def test_an_offline_photo_is_not_read_as_no_damage(materials):
    from app.domain.models import ExtractedRow, PartDraft
    from app.vision.models import PhotoVerdict

    class Offline:
        async def structural_damage(self, photos):
            return False

        async def submit(self, note_id, photos):
            return [PhotoVerdict(photo=photo, deferred=True) for photo in photos]

    repo = ClosureRepo(None)
    workflow = await workflow_with(repo, materials)
    workflow.photos = Offline()  # type: ignore[assignment]
    note = __import__("app.contract", fromlist=["NotaRecorrida"]).NotaRecorrida.model_validate(
        {"id": "NOTA-2", "ts": "2026-11-05T09:00:00-03:00", "operador": "Héctor", "audio_url": None,
         "fotos": ["/media/fotos/2.jpg"], "recorrida_id": "R1"})
    draft = PartDraft(note_id="NOTA-2", ts=note.ts, photos=list(note.fotos),
                      rows=[ExtractedRow(tag="B-102", variable="goteo_empaquetadura",
                                         observation="goteo", photo="/media/fotos/2.jpg")])
    await workflow._check_structural_damage(note, draft)
    assert workflow.structural_damage == set()
