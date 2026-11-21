"""NVIDIA vision client for the field photos (Entrega 2).

The model runs in NVIDIA's cloud, which the plant reaches only through the link proxy,
so this client is optional and its absence is a normal state: the analysis is queued
(see ``app/vision/queue.py``) and nothing in the alert path waits for it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable

import httpx

from app.vision.models import PhotoVerdict

log = logging.getLogger(__name__)

# What the model is asked to answer. It is a closed schema on purpose: the pipeline
# reads damage and severity, never free-form advice that could reach an order.
PROMPT = (
    "Sos un inspector de mantenimiento de una planta de inyección de agua. Mirás UNA foto "
    "de campo y respondés SOLO un objeto JSON, sin texto alrededor, con esta forma exacta:\n"
    '{"kind": "empaquetadura|correas|acople|manometro|filtro|estructura|desconocida", '
    '"structural_damage": true|false, "severity": "ninguna|leve|grave", '
    '"observations": ["frase corta", ...]}\n'
    "structural_damage es true solo si ves daño estructural (fisuras, deformación, rotura "
    "de soporte o de carcasa), no una pérdida o desgaste normal. Si la foto no permite "
    "decidir, usá kind=desconocida, severity=ninguna y observations vacía."
)

MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"BM", "image/bmp"),
)
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 2


class VisionUnavailable(RuntimeError):
    """The photo could not be analysed now: no model, no link, or an unusable answer."""


def content_type(image: bytes) -> str | None:
    for magic, mime in MAGIC:
        if image.startswith(magic):
            return mime
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    return None


class NvidiaVision:
    def __init__(self, model: str, base_url: str, api_key: str, *, timeout: float = 45.0,
                 client_factory: Callable[[], httpx.AsyncClient] | None = None):
        self.model = model
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=self.timeout, trust_env=True)
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key.strip() and self.model.strip() and self.base_url)

    async def analyse(self, photo: str, image: bytes) -> PhotoVerdict:
        if not self.enabled:
            raise VisionUnavailable("el análisis de fotos no está configurado")
        mime = content_type(image)
        if mime is None:
            raise VisionUnavailable(f"formato de imagen desconocido en {photo}")
        payload = {
            "model": self.model,
            "max_tokens": 300,
            "temperature": 0,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"}},
                ],
            }],
        }
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                answer = await self._post(payload)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in RETRY_STATUS:
                    # A bad key or a bad request will not fix itself: fail fast, no retry.
                    raise VisionUnavailable(f"el modelo de visión rechazó la petición ({status})") from exc
                last = exc
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last = exc
            else:
                return self._verdict(photo, answer)
            if attempt + 1 < MAX_ATTEMPTS:
                await asyncio.sleep(0.5 * (2 ** attempt))
        raise VisionUnavailable(f"el modelo de visión no respondió: {last}") from last

    async def _post(self, payload: dict) -> str:
        async with self.client_factory() as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload,
                                         headers={"Authorization": f"Bearer {self.api_key}"})
            response.raise_for_status()
            body = response.json()
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise VisionUnavailable("respuesta del modelo sin contenido") from exc

    def _verdict(self, photo: str, answer: str) -> PhotoVerdict:
        """Parse the JSON out of a chat answer. A malformed answer is never a verdict."""
        start = answer.find("{")
        if start < 0:
            raise VisionUnavailable("el modelo de visión no devolvió JSON")
        try:
            data, _ = json.JSONDecoder().raw_decode(answer[start:])
        except ValueError as exc:
            raise VisionUnavailable("el modelo de visión devolvió JSON inválido") from exc
        if not isinstance(data, dict):
            raise VisionUnavailable("el modelo de visión devolvió algo que no es un objeto")
        unknown = set(data) - {"kind", "structural_damage", "severity", "observations"}
        if unknown:
            raise VisionUnavailable(f"el modelo de visión devolvió campos no pedidos: {sorted(unknown)}")
        try:
            return PhotoVerdict(photo=photo, model=self.model, **data)
        except Exception as exc:  # pydantic rejects the shape
            raise VisionUnavailable(f"veredicto de visión inválido: {exc}") from exc
