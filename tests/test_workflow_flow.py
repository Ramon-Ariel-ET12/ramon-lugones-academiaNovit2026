from __future__ import annotations

from app.config import Settings
from app.contract import NotaRecorrida
from tests import fakes
from tests.conftest import TZ


def make_workflow(text: str, snapshot, materials):
    workflow, repo, publisher = fakes.make_workflow(snapshot, materials)

    async def transcribe(note):
        return text

    async def wait_reply(message_id, timeout):
        return {"texto": "La tres." if "-eq" in message_id else "Sí, confirmo."}

    async def no_history(rows, reference):
        return []

    workflow._transcribe = transcribe  # type: ignore[assignment]
    workflow.tablet.wait = wait_reply  # type: ignore[assignment]
    workflow.history.check = no_history  # type: ignore[assignment]
    return workflow, repo, publisher


async def test_ambiguous_observation_asks_and_gets_a_draft(snapshot, materials):
    workflow, repo, _ = make_workflow("La bomba está parada en reserva.", snapshot, materials)
    note = NotaRecorrida(id="N1", ts=__import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                         operador="x", audio_url=None, fotos=[], recorrida_id="R")
    await workflow._process(note)
    assert "TAB-N1-eq0" in repo.tablet
    assert "TAB-N1-info" in repo.tablet
    assert repo.parts and repo.parts[0]["status"] == "confirmed"


async def test_asr_merged_differential_first_draft_is_correct(snapshot, materials):
    workflow, repo, publisher = make_workflow("El filtro B-109 de diferencial. El pulmón está en 5 metros.",
                                              snapshot, materials)
    note = NotaRecorrida(id="N2", ts=__import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                         operador="x", audio_url=None, fotos=[], recorrida_id="R")
    await workflow._process(note)
    draft = next(payload for topic, payload in publisher.messages
                 if topic == "sistema/tablet" and payload["id"] == "TAB-N2-0")
    rows = {(row["tag"], row["variable"]): row["valor"] for row in draft["pantalla"]["filas"]}
    assert rows[("F-201B", "presion_diferencial")] == 0.9
    assert "TAB-N2-hist0" not in repo.tablet


async def test_value_question_answer_replaces_the_repaired_value(snapshot, materials):
    """The operator says the differential really was eighteen: the stored row must change."""
    from app.domain.models import Ambiguity, ExtractedRow, PartDraft

    wf, _repo, publisher = make_workflow("", snapshot, materials)
    draft = PartDraft(note_id="N3", ts=__import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                      rows=[ExtractedRow(tag="F-201B", variable="presion_diferencial", value=1.8,
                                         unit="kg/cm2", flags=["value_repaired"])])
    ambiguity = Ambiguity(kind="value", tag="F-201B", raw_value=18.0, repaired_value=1.8)

    async def reply_eighteen(message_id, timeout):
        return {"texto": "Eran dieciocho de diferencial."}

    wf.tablet.wait = reply_eighteen  # type: ignore[assignment]
    draft.ambiguities = [ambiguity]
    resolved = await wf._resolve_ambiguities(
        __import__("app.contract", fromlist=["NotaRecorrida"]).NotaRecorrida(
            id="N3", ts=draft.ts, operador="x", audio_url=None, fotos=[], recorrida_id="R"),
        draft, deadline=__import__("time").monotonic() + 60)
    row = resolved.rows[0]
    assert row.value == 18.0
    assert "value_repaired" not in row.flags
    assert any(payload.get("pantalla", {}) and payload["pantalla"].get("opciones")
               for topic, payload in publisher.messages if topic == "sistema/tablet")


async def test_historical_answer_is_applied_and_a_denial_removes_the_row(snapshot, materials):
    from app.domain.models import ExtractedRow

    wf, _repo, _publisher = make_workflow("", snapshot, materials)
    corrected = ExtractedRow(tag="B-101", variable="presion_descarga_local", value=200.0, unit="kg/cm2")
    wf._apply_historical_answer(corrected, "No, estaba en ciento quince kilos.")
    assert (corrected.value, corrected.unit) == (115.0, "kg/cm2")

    denied = ExtractedRow(tag="B-101", variable="presion_descarga_local", value=200.0, unit="kg/cm2")
    wf._apply_historical_answer(denied, "No.")
    assert denied.value is None and "denied_by_operator" in denied.flags


async def test_unreadable_audio_is_not_reported_as_no_novedad(snapshot, materials):
    wf, repo, _publisher = make_workflow("", snapshot, materials)

    async def silent(note):
        return ""

    wf._transcribe = silent  # type: ignore[assignment]
    note = NotaRecorrida(id="N4", ts=__import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                         operador="x", audio_url="/media/audios/roto.wav", fotos=[], recorrida_id="R")
    wf.plant = type("P", (), {"download": staticmethod(lambda url: None)})()  # type: ignore[assignment]
    await wf._process(note)
    assert repo.events == [], "an unreadable note must not publish SinNovedad"
    assert repo.parts and repo.parts[0]["status"] == "unreadable"
    assert "TAB-N4-retry" in repo.tablet


async def test_step_budget_caps_the_review_loop(snapshot, materials):
    from app.domain.models import ExtractedRow, PartDraft

    wf, repo, _ = make_workflow("", snapshot, materials)
    wf.settings = Settings(max_attempts=6, max_note_steps=2)
    draft = PartDraft(note_id="N5", ts=__import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                      rows=[ExtractedRow(tag="B-101", variable="presion_descarga_local", value=112.0,
                                         unit="kg/cm2")])

    async def unreadable(message_id, timeout):
        return {"texto": "Eh?"}

    wf.tablet.wait = unreadable  # type: ignore[assignment]
    note = NotaRecorrida(id="N5", ts=draft.ts, operador="x", audio_url=None, fotos=[], recorrida_id="R")
    _, confirmed = await wf._review_loop(note, draft, deadline=__import__("time").monotonic() + 60)
    assert confirmed is False
    assert [mid for mid in repo.tablet if mid.startswith("TAB-N5-") and not mid.endswith(("-info", "-ok"))] == [
        "TAB-N5-0", "TAB-N5-1"]


async def test_token_budget_disables_the_local_llm(snapshot, materials):
    from app.domain.models import ExtractedRow, PartDraft

    calls = {"n": 0}

    class FakeLLM:
        enabled = True

        async def interpret_reply(self, text, rows):
            calls["n"] += 1
            return [{"action": "set", "tag": "B-101", "value": 113.0, "unit": "kg/cm2"}], {
                "model": "fake", "task": "reply", "input_tokens": 100, "output_tokens": 100,
                "latency_ms": 1, "cost_usd": 0.0}

    wf, _repo, _ = make_workflow("", snapshot, materials)
    wf.llm = FakeLLM()
    wf.settings = Settings(max_attempts=6, max_note_steps=4, token_budget=50)
    draft = PartDraft(note_id="N6", ts=__import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                      rows=[ExtractedRow(tag="B-101", variable="presion_descarga_local", value=112.0,
                                         unit="kg/cm2")])

    async def odd(message_id, timeout):
        return {"texto": "Mmm no sé."}

    wf.tablet.wait = odd  # type: ignore[assignment]
    note = NotaRecorrida(id="N6", ts=draft.ts, operador="x", audio_url=None, fotos=[], recorrida_id="R")
    await wf._review_loop(note, draft, deadline=__import__("time").monotonic() + 60)
    assert calls["n"] == 1, "the LLM must be disabled once the note token budget is spent"


async def test_correction_that_restates_the_draft_is_resent_and_confirmed(snapshot, materials):
    """A correction the draft already satisfies must not end the dialog: resend it."""
    from app.domain.models import PartDraft
    from app.domain.parser import parse_transcript

    wf, repo, _ = make_workflow("", snapshot, materials)
    ts = __import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ)
    draft = parse_transcript(
        "La del medio está en 1610 psi de descarga. El rodamiento me dio 51 grados con la pistola.",
        snapshot, note_id="N7", ts=ts)
    replies = iter([
        {"texto": "No. La dos estaba en mil seiscientos diez psi, no en cincuenta y uno. "
                   "Te faltó la dos, que estaba en cincuenta y uno grados."},
        {"texto": "Sí, confirmo."},
    ])

    async def wait(message_id, timeout):
        return next(replies)

    wf.tablet.wait = wait  # type: ignore[assignment]
    note = NotaRecorrida(id="N7", ts=ts, operador="x", audio_url=None, fotos=[], recorrida_id="R")
    result, confirmed = await wf._review_loop(note, draft, deadline=__import__("time").monotonic() + 60)
    assert confirmed is True
    assert "TAB-N7-0" in repo.tablet and "TAB-N7-1" in repo.tablet
    discharge = next(row for row in result.rows if row.variable == "presion_descarga_local")
    assert (discharge.value, discharge.unit) == (1610.0, "psi")
    assert isinstance(result, PartDraft)


async def test_a_hanging_transcription_is_cut_by_the_note_budget(snapshot, materials):
    """E1d: the global timeout must stop the step, not just be checked between steps."""
    import asyncio

    wf, repo, _ = make_workflow("", snapshot, materials)
    wf.settings = Settings(note_timeout_s=0.2)

    async def slow(note):
        await asyncio.sleep(5)
        return "nunca"

    wf._transcribe = slow  # type: ignore[assignment]
    note = NotaRecorrida(id="N8", ts=__import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                         operador="x", audio_url="/media/audios/tarda.wav", fotos=[], recorrida_id="R")
    await wf._process(note)
    assert repo.parts and repo.parts[0]["status"] == "unreadable"
    assert repo.events == []
    assert "TAB-N8-retry" in repo.tablet


async def test_safety_alert_is_published_from_a_partial_transcript(snapshot, materials):
    """The alert must not wait for the whole audio: a partial trigger publishes it once."""
    from app.domain.parser import parse_transcript

    wf, repo, publisher = make_workflow("", snapshot, materials)
    ts = __import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ)
    note = NotaRecorrida(id="N9", ts=ts, operador="x", audio_url="/media/audios/s1.wav",
                         fotos=[], recorrida_id="R")
    await wf._early_alert(note, "¡Atención! Se rompió algo en la descarga de la uno, "
                                "sale agua a presión para todos lados")
    alerts = [payload for topic, payload in publisher.messages
              if topic == "sistema/eventos" and payload["tipo"] == "AlertaSeguridad"]
    assert alerts and alerts[0]["nota_ids"] == ["N9"]
    assert repo.tablet.count("ALERTA-N9") == 1

    draft = parse_transcript("¡Atención! Se rompió algo en la descarga de la uno, sale agua a presión "
                             "para todos lados, me alejé.", snapshot, note_id="N9", ts=ts)
    await wf._handle_safety(note, draft, deadline=__import__("time").monotonic() + 30)
    assert repo.tablet.count("ALERTA-N9") == 1, "the final path must not repeat the alert"
    assert repo.parts and repo.parts[0]["status"] == "confirmed"


async def test_vivo_note_without_reportable_content_emits_no_event(snapshot, materials):
    """B8: a VIVO- note has no expected part and may carry nothing to report."""
    wf, repo, _ = make_workflow("", snapshot, materials)
    ts = __import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ)
    note = NotaRecorrida(id="VIVO-1", ts=ts, operador="x", audio_url=None, fotos=[], recorrida_id="R")
    await wf._process(note)
    assert repo.events == [], "an empty VIVO note must not fabricate an event"
    assert repo.parts and repo.parts[0]["status"] == "confirmed"
    assert "TAB-VIVO-1-ok" in repo.tablet
    assert not any(mid.startswith("TAB-VIVO-1-processing") for mid in repo.tablet)


async def test_vivo_note_reports_only_what_was_said(snapshot, materials):
    wf, repo, _ = make_workflow("La uno está en 112 kilos de descarga.", snapshot, materials)
    ts = __import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ)
    note = NotaRecorrida(id="VIVO-2", ts=ts, operador="x", audio_url=None, fotos=[], recorrida_id="R")
    await wf._process(note)
    rows = repo.parts[0]["rows"]
    assert [(row["tag"], row["variable"], row["value"]) for row in rows] == [
        ("B-101", "presion_descarga_local", 112.0)]


async def test_escalated_event_context_stores_the_manual_citations(snapshot, materials):
    """The annex asks every conclusion to cite the manual section it comes from."""
    wf, repo, _ = make_workflow("", snapshot, materials)
    stored: dict = {}

    async def capture(event_id, context):
        stored.update(context)

    repo.update_event_context = capture  # type: ignore[assignment]

    class Search:
        async def search(self, query, k=6):
            return [{"citation": "TX350-D §3.2", "doc": "TX350-D", "title": "Límites",
                     "current": True, "text": "presión de descarga"}]

    class Plant:
        async def state(self):
            return {"ts": "2026-11-03T08:00:00-03:00"}

        async def historian(self, tag, variable, desde=None, hasta=None):
            return [{"ts": "2026-11-03T07:00:00-03:00", "valor": 112.0}]

        async def order_history(self, equipo=None):
            return []

    wf.search = Search()
    wf.plant = Plant()  # type: ignore[assignment]
    await wf._enrich_event({"id": "E1", "equipo": "B-101", "tipo": "Escalado"}, [], [], {})

    assert stored["sections"][0]["citation"] == "TX350-D §3.2"
    assert stored["sensor_trend"]["presion_descarga"]["last"] == 112.0


async def test_the_operator_hears_about_the_note_before_it_is_transcribed(snapshot, materials):
    """The processing notice is sent on arrival, and only once."""
    wf, repo, _publisher = make_workflow("La uno está en 112 kilos de descarga.", snapshot, materials)
    from app.contract import NotaRecorrida

    payload = {"id": "NOTA-X", "ts": "2026-11-03T08:00:00-03:00", "operador": "Héctor",
               "audio_url": None, "fotos": [], "recorrida_id": "R1"}
    note = NotaRecorrida.model_validate(payload)
    await wf.enqueue(payload)
    assert "TAB-NOTA-X-processing" in repo.tablet
    await wf.tablet.send(note, "TAB-NOTA-X-processing", "Nota recibida. Procesando el parte...",
                         waits=False, kind="notice")
    assert repo.tablet.count("TAB-NOTA-X-processing") == 1
