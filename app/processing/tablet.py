"""The tablet channel: the dialog with the operator's screen.

Everything that leaves for ``sistema/tablet`` goes through here, together with the
matching that a reply has with the message that asked for it. The workflow decides
*what* to ask; this class decides how a question is stored, published and waited for.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.contract import NotaRecorrida, RespuestaOperador
from app.domain.models import ExtractedRow
from app.persistence.repository import Repository
from app.publisher import Publisher

log = logging.getLogger(__name__)


class TabletChannel:
    def __init__(self, repo: Repository, publisher: Publisher):
        self.repo = repo
        self.publisher = publisher
        # A reply can arrive before the dialog asks for it (the operator answers while the
        # next question is being prepared), so late answers are kept per message id.
        self._replies: dict[str, dict] = {}
        self._waiters: dict[str, asyncio.Event] = {}

    async def send(self, note: NotaRecorrida, message_id: str, text: str, *,
                   rows: list[ExtractedRow] | None = None, options: list[str] | None = None,
                   waits: bool = True, kind: str = "draft") -> bool:
        """Send one tablet message. Returns False when it had already been sent."""
        pantalla: dict | None = None
        if options is not None:
            pantalla = {"titulo": "Pregunta", "filas": [], "opciones": options}
        elif rows is not None:
            pantalla = {"titulo": "Parte de recorrida - borrador", "filas": [row.to_contract() for row in rows]}
        payload = {
            "id": message_id,
            "ts": datetime.now(UTC).isoformat(),
            "nota_ids": [note.id],
            "texto": text,
            "pantalla": pantalla,
            "espera_respuesta": waits,
            "audio_url": None,
        }
        created = await self.repo.add_tablet_message(message_id, note.id, note.ts, kind, payload)
        if created:
            await self.publisher.publish("sistema/tablet", payload, sync=False)
        return bool(created)

    async def deliver(self, payload: dict) -> None:
        """Store the operator's answer and wake the dialog waiting for it."""
        message_id = payload.get("mensaje_id")
        if not message_id:
            return
        try:
            reply = RespuestaOperador.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("invalid operator reply on %s: %s", message_id, exc)
            return
        try:
            notes = await self.repo.note_ids_for_message(message_id)
            await self.repo.add_reply(reply.id, message_id, notes[0] if notes else None,
                                      reply.texto, reply.ts)
            # The attempt that asked for it keeps the answer, even when it arrived after
            # the timeout of the dialog that sent the question.
            await self.repo.set_attempt_reply(message_id, reply.texto)
        except Exception:
            log.warning("reply %s could not be stored", reply.id, exc_info=True)
        self._replies[message_id] = payload
        waiter = self._waiters.get(message_id)
        if waiter:
            waiter.set()

    async def wait(self, message_id: str, timeout: float) -> dict | None:
        if message_id in self._replies:
            return self._replies.pop(message_id)
        event = self._waiters.setdefault(message_id, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            return None
        finally:
            self._waiters.pop(message_id, None)
        return self._replies.pop(message_id, None)
