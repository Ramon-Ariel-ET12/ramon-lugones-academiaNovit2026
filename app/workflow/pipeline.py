"""The order pipeline, step by step.

Delivery 2 asks for the workflow to be explicit: escalated event → analysis → draft →
rules → approved or pending, with the reviewer in between and the human decision outside.
Each step is a method, so the fixed part of the workflow is readable in one screen and
the agent part (the optional language model) is only where it is marked.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from app.analysis.analyzer import analyse
from app.analysis.review import CitationIndex
from app.config import Settings
from app.domain.materials import Materials
from app.domain.models import ExtractedRow, PlantSnapshot
from app.domain.orders import make_proposal, order_id, order_payload
from app.domain.rules import Decision, PlantState
from app.integrations.plant_api import PlantClient
from app.persistence.repository import Repository
from app.publisher import Publisher
from app.rag.context import build_event_context
from app.rag.search import ManualSearch

log = logging.getLogger(__name__)


class OrderPipeline:
    """Evidence → analysis → reviewed draft → rules → published order."""

    def __init__(self, settings: Settings, repo: Repository, plant: PlantClient, publisher: Publisher,
                 snapshot: PlantSnapshot, materials: Materials, citations: CitationIndex,
                 search: ManualSearch | None = None):
        self.settings = settings
        self.repo = repo
        self.plant = plant
        self.publisher = publisher
        self.snapshot = snapshot
        self.materials = materials
        self.citations = citations
        self.search = search
        # Two escalated events can be analysed at the same time (orders run detached);
        # the duplicate check and the creation must not interleave.
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- steps

    async def evidence(self, event: dict, rows: list[ExtractedRow], photos: list[str]) -> dict:
        """The evidence for an escalated event, under the order's real-time budget."""
        try:
            return await asyncio.wait_for(
                build_event_context(event, rows, photos, self.plant, self.search, self.snapshot,
                                    self.materials),
                timeout=self.settings.order_deadline_s,
            )
        except TimeoutError:
            log.warning("evidence for %s exceeded %.0fs: drafting with the part alone",
                        event.get("id"), self.settings.order_deadline_s)
            return {"rows": [row.model_dump() for row in rows], "photos": photos}
        except Exception:
            log.warning("evidence for %s could not be built", event.get("id"), exc_info=True)
            return {"rows": [row.model_dump() for row in rows], "photos": photos}

    async def analyse(self, event: dict, rows: list[ExtractedRow], sensor_variable: str | None,
                      context: dict):
        equipment = event.get("equipo") or ""
        return await asyncio.to_thread(
            analyse, equipment, rows, sensor_variable, context, self.snapshot, self.materials,
            self.citations, event["id"],
        )

    # ---------------------------------------------------------------- the order

    async def run(self, event: dict, *, rows: list[ExtractedRow], photos: list[str],
                  sensor_variable: str | None, plant_state: PlantState, link_ok: bool,
                  structural_damage: bool = False) -> dict | None:
        """Draft, decide and publish the order for one escalated event.

        Returns the payload published last, or None when there is nothing to order (the
        reviewer blocked the analysis, a drifting sensor, or no task applies).
        """
        started = time.monotonic()
        equipment = event.get("equipo")
        if not equipment:
            return None
        context = await self.evidence(event, rows, photos)
        analysis = await self.analyse(event, rows, sensor_variable, context)
        if analysis.blocked:
            log.warning("order for %s not drafted: %s", equipment,
                        "; ".join(finding.detail for finding in analysis.blocking_findings))
            return None
        if not analysis.tasks:
            log.info("event %s on %s needs no work order (analysis: %s)", event.get("id"), equipment,
                     analysis.causes[0].code if analysis.causes else "sin causa")
            return None
        async with self._lock:
            existing = await self.repo.open_order(equipment, analysis.tasks)
            if existing:
                log.info("order already open for %s %s: %s", equipment, analysis.tasks, existing["id"])
                return None

            proposal, decision = make_proposal(
                equipment, analysis.tasks, self.materials, plant_state,
                structural_damage=structural_damage, forced_pending=not link_ok,
            )
            oid = order_id(equipment, analysis.tasks, event["id"])
            now = datetime.now(UTC)
            draft_state = Decision(approved=False)
            borrador = order_payload(oid, now, "Borrador", proposal, draft_state, [event["id"]])
            final = order_payload(oid, now, decision.state, proposal, decision, [event["id"]])
            await self.repo.save_analysis(
                oid, {"causes": [cause.model_dump() for cause in analysis.causes]},
                correlation_id=event["id"], citations=analysis.citations,
                review={"findings": [finding.model_dump() for finding in analysis.findings],
                        "history": analysis.history, "parts": analysis.parts,
                        "symptoms": [symptom.model_dump() for symptom in analysis.symptoms]},
            )
            await self.publisher.publish("sistema/ordenes", borrador, sync=True)
            await self.repo.upsert_order(oid, equipment, analysis.tasks, "Borrador", borrador)
            await self.publisher.publish("sistema/ordenes", final, sync=True)
            await self.repo.upsert_order(oid, equipment, analysis.tasks, decision.state, final)
            await self.repo.record_decision(oid, decision.state, decision.reasons, plant_state.model_dump())
        log.info("order %s for %s %s -> %s (%.0f ms; causes: %s)", oid, equipment, analysis.tasks,
                 decision.state, (time.monotonic() - started) * 1000,
                 ", ".join(cause.code or cause.title for cause in analysis.causes[:3]))
        return final
