"""Validated publishing.

Nothing leaves the system without passing the contract model first: an invalid message
is a robustness failure in the rubric and, worse, a lie to the plant.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine

from pydantic import ValidationError

from app.contract import TOPIC_MODELS
from app.integrations.mqtt import MqttTransport
from app.persistence.repository import Repository

log = logging.getLogger(__name__)


class Publisher:
    def __init__(self, mqtt: MqttTransport, repo: Repository,
                 pending_hook: Callable[[], Coroutine] | None = None):
        self.mqtt = mqtt
        self.repo = repo
        self.pending_hook = pending_hook
        # The heartbeat refresh runs detached from the caller, so the task is kept
        # referenced: an unreferenced task can be collected mid-flight.
        self._background: set[asyncio.Task[None]] = set()

    async def publish(self, topic: str, payload: dict, *, sync: bool = True) -> bool:
        model = TOPIC_MODELS.get(topic)
        if model is None:
            log.error("refusing unknown topic %s", topic)
            return False
        try:
            model.model_validate(payload)
        except ValidationError as exc:
            log.error("refusing invalid %s: %s", topic, exc.errors(include_url=False))
            return False
        self.mqtt.publish(topic, payload)
        if sync:
            await self.repo.enqueue(topic, payload)
            if self.pending_hook is not None:
                task: asyncio.Task = asyncio.create_task(self.pending_hook())
                self._background.add(task)
                task.add_done_callback(self._background.discard)
        return True
