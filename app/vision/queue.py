"""Photo analysis queue (Entrega 2).

A photo is analysed as soon as the link allows it; when it does not, the photo is
queued and analysed later. Nothing here blocks a note, an order or the safety alert: the
queue is drained by its own periodic task.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.vision.models import PhotoVerdict
from app.vision.nvidia import NvidiaVision, VisionUnavailable

log = logging.getLogger(__name__)

MediaLoader = Callable[[str], Awaitable[bytes]]

# Photo ids are derived from the note and the path so a retry cannot duplicate a row.
PHOTO_NAMESPACE = uuid.UUID("0f7c2b64-6f5a-4c1e-9c2a-8f3d5b7e1a90")


def photo_id(note_id: str, photo: str) -> str:
    return str(uuid.uuid5(PHOTO_NAMESPACE, f"{note_id}:{photo}"))


class PhotoQueue(Protocol):
    async def enqueue_photo(self, photo_id: str, photo: str) -> str: ...

    async def pending_photos(self, limit: int = 20) -> list[dict]: ...

    async def mark_analysed(self, photo_id: str, result: dict) -> None: ...

    async def mark_failed(self, photo_id: str) -> None: ...

    async def record_usage(self, model: str, task: str, input_tokens: int, output_tokens: int,
                           latency_ms: int, cost_usd: float = 0.0) -> None: ...


class PhotoAnalyser:
    def __init__(self, queue: PhotoQueue, vision: NvidiaVision, media_loader: MediaLoader):
        self.queue = queue
        self.vision = vision
        self.media_loader = media_loader

    async def submit(self, note_id: str, photos: list[str]) -> list[PhotoVerdict]:
        """Analyse what can be analysed now; queue the rest. Never raises."""
        verdicts: list[PhotoVerdict] = []
        for photo in photos:
            try:
                verdicts.append(await self._analyse(photo_id(note_id, photo), photo))
            except VisionUnavailable as exc:
                log.warning("photo %s queued for analysis: %s", photo, exc)
                await self.queue.enqueue_photo(photo_id(note_id, photo), photo)
                verdicts.append(PhotoVerdict(photo=photo, deferred=True, model=self.vision.model))
        return verdicts

    async def drain(self, limit: int = 20) -> int:
        """Analyse queued photos. Stops at the first unavailable model: the link is down."""
        done = 0
        for row in await self.queue.pending_photos(limit):
            try:
                verdict = await self._analyse(row["id"], row["photo"])
            except VisionUnavailable as exc:
                log.info("photo analysis stopped, %s still pending: %s", limit - done, exc)
                await self.queue.mark_failed(row["id"])
                break
            await self.queue.mark_analysed(row["id"], verdict.model_dump())
            done += 1
        return done

    async def _analyse(self, pht_id: str, photo: str) -> PhotoVerdict:
        image = await self.media_loader(photo)
        verdict = await self.vision.analyse(photo, image)
        await self.queue.mark_analysed(pht_id, verdict.model_dump())
        await self._record_usage(verdict)
        return verdict

    async def _record_usage(self, verdict: PhotoVerdict) -> None:
        """One usage row per analysed photo; a storage failure cannot undo the verdict."""
        if not verdict.model:
            return
        try:
            await self.queue.record_usage(verdict.model, "vision", verdict.input_tokens,
                                          verdict.output_tokens, verdict.latency_ms, 0.0)
        except Exception:
            log.warning("vision usage could not be stored", exc_info=True)
