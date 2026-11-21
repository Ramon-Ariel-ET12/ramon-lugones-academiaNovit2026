"""Application assembly: MQTT ingestion, note workflow, heartbeat, sync and UI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.analysis.review import CorpusCitations
from app.api.decisions import configure as configure_orders
from app.api.decisions import router as orders_router
from app.config import Settings, get_settings
from app.domain.billing import PriceList
from app.domain.materials import load_materials
from app.domain.plant import load_snapshot_file, snapshot_from_definition
from app.domain.sensors import SensorDetector
from app.heartbeat import heartbeat_payload
from app.integrations.mqtt import MqttTransport
from app.integrations.plant_api import PlantClient
from app.integrations.sync import CloudSync
from app.llm.local import LocalLLM
from app.logging_setup import configure_logging
from app.persistence.db import Database
from app.persistence.repository import Repository
from app.processing.asr import Transcriber
from app.processing.workflow import NoteWorkflow
from app.publisher import Publisher
from app.ui.console import STARTING, render_console
from app.vision.nvidia import NvidiaVision
from app.vision.queue import PhotoAnalyser
from app.workflow.decisions import OrderDecisionService
from app.workflow.pipeline import OrderPipeline
from app.workflow.router import route_topic, sensor_parts

log = logging.getLogger(__name__)


@dataclass
class Context:
    settings: Settings
    db: Database
    repo: Repository
    plant: PlantClient
    mqtt: MqttTransport
    publisher: Publisher
    materials: object
    snapshot: object
    transcriber: Transcriber
    workflow: NoteWorkflow
    detector: SensorDetector
    pipeline: OrderPipeline | None = None
    photos: PhotoAnalyser | None = None
    link_up: bool = True
    ready: bool = False
    tasks: list[asyncio.Task] = field(default_factory=list)
    digests: dict[tuple[str, str], datetime] = field(default_factory=dict)


def _context(request: Request) -> Context | None:
    """The running application context (None before startup and after shutdown)."""
    return getattr(request.app.state, "ctx", None)


ContextDep = Annotated[Context | None, Depends(_context)]


async def _load_snapshot(plant: PlantClient, settings: Settings):
    try:
        return snapshot_from_definition(await plant.definition())
    except Exception as exc:  # noqa: BLE001
        log.warning("using bundled plant definition: %s", exc)
        return load_snapshot_file(settings.plant_snapshot_path)


async def _resume_orders(ctx_: Context) -> None:
    for order in await ctx_.repo.open_orders():
        payload = dict(order["payload"])
        if payload.get("estado") == "Borrador":
            continue
        await ctx_.publisher.publish("sistema/ordenes", payload, sync=False)
        log.info("resumed order %s in state %s", order["id"], payload.get("estado"))


async def _publish_heartbeat(ctx_: Context) -> None:
    payload = heartbeat_payload(ctx_.settings.system_name, ctx_.link_up,
                                await ctx_.repo.pending_count())
    await ctx_.publisher.publish("sistema/estado", payload, sync=False)


async def _monitor_loop(ctx_: Context) -> None:
    """Publish the heartbeat, and a degraded one as soon as the link drops.

    The link is polled more often than the heartbeat is published: it can fall between
    two heartbeats and the plant watches for the exact moment it does.
    """
    next_beat = time.monotonic() + ctx_.settings.heartbeat_seconds
    while True:
        try:
            link = await ctx_.plant.link_state()
            changed = link != ctx_.link_up
            ctx_.link_up = link
            if changed or not link or time.monotonic() >= next_beat:
                await _publish_heartbeat(ctx_)
                next_beat = time.monotonic() + ctx_.settings.heartbeat_seconds
        except Exception:
            log.warning("heartbeat failed", exc_info=True)
        await asyncio.sleep(ctx_.settings.link_poll_seconds)


async def _sync_loop(ctx_: Context) -> None:
    sync = CloudSync(ctx_.repo, ctx_.settings.cloud_sync_url, ctx_.settings.sync_batch_size)
    while True:
        await asyncio.sleep(ctx_.settings.sync_poll_seconds)
        synced = await sync.once()
        if synced:
            log.info("synced %s items to cloud replica", synced)


async def _sensor_digest(ctx_: Context, payload: dict) -> None:
    if ctx_.link_up:
        return
    key = (payload.get("tag", ""), payload.get("variable", ""))
    stamp = datetime.fromisoformat(payload["ts"])
    last = ctx_.digests.get(key)
    if last and stamp - last < timedelta(minutes=15):
        return
    ctx_.digests[key] = stamp
    await ctx_.repo.enqueue("sensor/digest", payload)


async def _dispatch_loop(ctx_: Context) -> None:
    async for topic, payload in ctx_.mqtt.messages():
        try:
            route = route_topic(topic)
            if route == "parte":
                await ctx_.workflow.enqueue(payload)
            elif route == "respuesta":
                await ctx_.workflow.on_reply(payload)
            elif route == "sensor":
                await _on_sensor_sample(ctx_, payload)
            elif route == "cierre":
                await ctx_.workflow.handle_closure(payload)
            elif route == "energia":
                log.info("plant energy state: %s", payload.get("hay_energia"))
            else:
                log.warning("message on an unknown topic ignored: %s", topic)
        except Exception:
            log.exception("failed to handle %s", topic)


async def _on_sensor_sample(ctx_: Context, payload: dict) -> None:
    """Feed one sample to the detector and escalate the sustained deviation it reports."""
    parts = sensor_parts(payload)
    if parts is None:
        return
    tag, variable = parts
    stamp = datetime.fromisoformat(payload["ts"])
    event, episode = ctx_.detector.feed(tag, variable, payload.get("valor"), stamp,
                                        payload.get("calidad", "buena"))
    if episode is not None:
        # Persisted on the transition only: the episode id survives a restart.
        await ctx_.repo.set_sensor_event(tag, variable,
                                         episode["event_id"] if episode["active"] else None,
                                         episode["since"])
    if event:
        await ctx_.workflow.handle_sensor_event(event, variable)
    await _sensor_digest(ctx_, payload)


async def _photo_loop(ctx_: Context) -> None:
    """Drain the photo queue: with the link down it simply retries on the next round."""
    analyser = ctx_.photos
    if analyser is None:
        return
    while True:
        try:
            done = await analyser.drain()
            if done:
                log.info("analysed %s queued photos", done)
        except Exception:
            log.warning("photo queue drain failed", exc_info=True)
        await asyncio.sleep(max(10.0, ctx_.settings.sync_poll_seconds * 6))


async def _rag_loop(ctx_: Context) -> None:
    """Build the manual index once the plant corpus is reachable, retrying a few times."""
    from app.rag.indexer import ensure_index


    for _ in range(3):
        try:
            count = await ensure_index(ctx_.repo, ctx_.plant, ctx_.settings)
            log.info("rag index ready with %s chunks", count)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("rag indexing failed: %s", exc)
            await asyncio.sleep(20)


async def _analysis_inputs(repo: Repository, settings: Settings) -> tuple[CorpusCitations, PriceList | None]:
    """The citation index and the contract price list the analysis and the reviewer use.

    Both come from the indexed corpus (the same text the retrieval uses); when the index
    is empty they fall back to the bundled file so the pipeline still works on a cold DB.
    """
    rows = await repo.rag_citations()
    citations = CorpusCitations(rows) if rows else CorpusCitations.from_settings(settings)
    contract = await repo.rag_texts("CT-SVP-2025") if rows else []
    prices = PriceList.from_chunks(contract) if contract else None
    if prices is None or len(prices) == 0:
        log.warning("CT-SVP-2025 price list not indexed yet: certification amounts unavailable")
        prices = None
    return citations, prices


def _photo_analyser(settings: Settings, repo: Repository, plant: PlantClient) -> PhotoAnalyser | None:
    vision = NvidiaVision(settings.vision_model, settings.vision_base_url, settings.vision_api_key,
                          timeout=settings.vision_timeout_s)
    if not (settings.vision_enabled and vision.enabled):
        log.info("photo analysis disabled (VISION_ENABLED / NVIDIA_API_KEY)")
        return None

    async def load(photo: str) -> bytes:
        path = Path(photo)
        if path.exists():
            return path.read_bytes()
        return await plant.download(photo)

    return PhotoAnalyser(repo, vision, load)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    db = Database(settings.database_url)
    await db.connect()
    repo = Repository(db)
    plant = PlantClient(settings.plant_url, link_control_url=settings.link_control_url)
    snapshot = await _load_snapshot(plant, settings)
    materials = load_materials(settings.materials_path)
    transcriber = Transcriber(settings.asr_model, threads=settings.asr_threads,
                              beam_size=settings.asr_beam_size)
    try:
        await asyncio.to_thread(transcriber.warmup)
    except Exception:
        log.exception("ASR warmup failed; notes will fail until the model is available")

    mqtt = MqttTransport(settings.mqtt_host, settings.mqtt_port)
    mqtt.start()
    if not await mqtt.wait_connected(30):
        log.error("mqtt not connected yet; continuing with reconnect")
    publisher = Publisher(mqtt, repo)
    llm = LocalLLM(settings.llm_model, enabled=settings.llm_enabled)
    from app.rag.search import ManualSearch

    search = ManualSearch(repo, settings, snapshot)
    citations, prices = await _analysis_inputs(repo, settings)
    pipeline = OrderPipeline(settings, repo, plant, publisher, snapshot, materials, citations, search)
    photos = _photo_analyser(settings, repo, plant)
    workflow = NoteWorkflow(settings, repo, plant, publisher, snapshot, materials, transcriber, llm,
                            search=search, pipeline=pipeline, prices=prices, photos=photos)
    detector = SensorDetector(snapshot)
    # A restart in the middle of a sustained deviation must keep the same event id.
    try:
        detector.restore(await repo.sensor_episodes())
    except Exception:
        log.warning("sensor episodes could not be restored", exc_info=True)
    ctx = Context(settings, db, repo, plant, mqtt, publisher, materials, snapshot, transcriber,
                  workflow, detector, pipeline=pipeline, photos=photos)
    app.state.ctx = ctx
    publisher.pending_hook = lambda: _publish_heartbeat(ctx)
    await workflow.start()
    await _resume_orders(ctx)
    ctx.tasks = [
        asyncio.create_task(_dispatch_loop(ctx), name="mqtt-dispatch"),
        asyncio.create_task(_monitor_loop(ctx), name="heartbeat"),
        asyncio.create_task(_sync_loop(ctx), name="sync"),
        asyncio.create_task(_photo_loop(ctx), name="photos"),
    ]
    configure_orders(OrderDecisionService(repo, publisher, prices=prices))
    ctx.ready = True
    # The correction waits for this first heartbeat before releasing the plant clock, so
    # it carries the link state as it is at startup, not the optimistic default.
    try:
        ctx.link_up = await plant.link_state()
        await _publish_heartbeat(ctx)
    except Exception:
        log.exception("initial heartbeat failed")
    ctx.tasks.append(asyncio.create_task(_rag_loop(ctx), name="rag"))
    log.info("system ready as %s", settings.system_name)
    try:
        yield
    finally:
        for task in ctx.tasks:
            task.cancel()
        for task in ctx.tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await workflow.stop()
        mqtt.stop()
        await db.close()
        del app.state.ctx


app = FastAPI(title="PIA-3 assistant", lifespan=lifespan)
app.include_router(orders_router)


@app.get("/health")
async def health(runtime: ContextDep):
    if runtime is None:
        return JSONResponse({"ready": False}, status_code=503)
    return {"ready": runtime.ready, "database": await runtime.db.health(), "link_up": runtime.link_up,
            "system": runtime.settings.system_name}


@app.get("/api/state")
async def state(runtime: ContextDep):
    if runtime is None:
        return JSONResponse({"ready": False}, status_code=503)
    return await runtime.repo.console_state()


@app.get("/", response_class=HTMLResponse)
async def index(runtime: ContextDep):
    if runtime is None:
        return HTMLResponse(STARTING)
    data = await runtime.repo.console_state()
    return HTMLResponse(render_console(data, system_name=runtime.settings.system_name,
                                       link_up=runtime.link_up))


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.ui_port, log_config=None)


if __name__ == "__main__":
    main()
