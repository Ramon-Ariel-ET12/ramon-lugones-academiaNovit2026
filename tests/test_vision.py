"""Vision client and photo queue (Entrega 2): mocked HTTP, no network."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from app.vision.models import PhotoVerdict
from app.vision.nvidia import NvidiaVision, VisionUnavailable, content_type
from app.vision.queue import PhotoAnalyser, photo_id

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
URL = "https://vision.test/v1"


def vision(api_key: str = "k-123", *, timeout: float = 5) -> NvidiaVision:
    return NvidiaVision("meta/llama-3.2-11b-vision-instruct", URL, api_key, timeout=timeout)


def answer(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


VALID = {"kind": "empaquetadura", "structural_damage": False, "severity": "leve",
         "observations": ["pérdida en la empaquetadura"]}


class FakeQueue:
    def __init__(self):
        self.enqueued: list[tuple[str, str]] = []
        self.done: dict[str, dict] = {}
        self.failed: list[str] = []
        self.damage: dict[str, bool] = {}

    async def enqueue_photo(self, pid, photo):
        self.enqueued.append((pid, photo))
        return pid

    async def pending_photos(self, limit=20):
        return [{"id": pid, "photo": photo, "attempts": 0} for pid, photo in self.enqueued[:limit]]

    async def mark_analysed(self, pid, result):
        self.done[pid] = result
        self.damage[result["photo"]] = result["structural_damage"]

    async def mark_failed(self, pid):
        self.failed.append(pid)

    async def structural_damage(self, photo):
        return self.damage.get(photo, False)


async def load(_photo: str) -> bytes:
    return JPEG


# ------------------------------------------------------------------ client


def test_content_type_from_magic_bytes():
    assert content_type(JPEG) == "image/jpeg"
    assert content_type(PNG) == "image/png"
    assert content_type(b"RIFF0000WEBP") == "image/webp"
    assert content_type(b"not an image") is None


@respx.mock
async def test_analyse_sends_the_image_and_returns_a_verdict():
    route = respx.post(f"{URL}/chat/completions").mock(return_value=httpx.Response(200, json=answer(VALID)))
    verdict = await vision().analyse("/photos/1.jpg", JPEG)
    assert verdict.kind == "empaquetadura" and verdict.severity == "leve"
    assert verdict.deferred is False and verdict.model.startswith("meta/")
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body["model"] == "meta/llama-3.2-11b-vision-instruct"
    assert body["temperature"] == 0
    image_url = body["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(image_url.split(",", 1)[1]) == JPEG
    assert request.headers["authorization"] == "Bearer k-123"


@respx.mock
async def test_a_garbage_answer_is_not_a_verdict():
    respx.post(f"{URL}/chat/completions").mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": "no sé, parece una pérdida"}}]}))
    with pytest.raises(VisionUnavailable):
        await vision().analyse("/photos/1.jpg", JPEG)


@respx.mock
async def test_unrequested_fields_are_rejected():
    bad = dict(VALID, orden_id="OT-1")
    respx.post(f"{URL}/chat/completions").mock(return_value=httpx.Response(200, json=answer(bad)))
    with pytest.raises(VisionUnavailable):
        await vision().analyse("/photos/1.jpg", JPEG)


@respx.mock
async def test_a_throttled_request_is_retried_once():
    route = respx.post(f"{URL}/chat/completions").mock(side_effect=[
        httpx.Response(429), httpx.Response(200, json=answer(VALID))])
    verdict = await vision().analyse("/photos/1.jpg", JPEG)
    assert verdict.kind == "empaquetadura"
    assert route.call_count == 2


@respx.mock
async def test_a_rejected_key_is_not_retried():
    route = respx.post(f"{URL}/chat/completions").mock(return_value=httpx.Response(401))
    with pytest.raises(VisionUnavailable):
        await vision().analyse("/photos/1.jpg", JPEG)
    assert route.call_count == 1


@respx.mock
async def test_a_timeout_is_retried_and_then_reported():
    route = respx.post(f"{URL}/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(VisionUnavailable):
        await vision(timeout=0.01).analyse("/photos/1.jpg", JPEG)
    assert route.call_count == 2


async def test_disabled_without_a_key():
    client = vision(api_key="")
    assert client.enabled is False
    with pytest.raises(VisionUnavailable):
        await client.analyse("/photos/1.jpg", JPEG)


# ------------------------------------------------------------------ queue


async def test_submit_queues_what_cannot_be_analysed():
    class Offline(NvidiaVision):
        async def analyse(self, photo, image):
            raise VisionUnavailable("sin enlace")

    queue = FakeQueue()
    analyser = PhotoAnalyser(queue, Offline("m", URL, "k"), load)
    verdicts = await analyser.submit("NOTA-1", ["/photos/1.jpg", "/photos/2.jpg"])
    assert [v.deferred for v in verdicts] == [True, True]
    assert queue.enqueued == [(photo_id("NOTA-1", "/photos/1.jpg"), "/photos/1.jpg"),
                              (photo_id("NOTA-1", "/photos/2.jpg"), "/photos/2.jpg")]


async def test_the_photo_id_is_stable_for_a_retry():
    assert photo_id("NOTA-1", "/a.jpg") == photo_id("NOTA-1", "/a.jpg")
    assert photo_id("NOTA-1", "/a.jpg") != photo_id("NOTA-2", "/a.jpg")


@respx.mock
async def test_drain_analyses_the_queue_and_stores_the_verdict():
    respx.post(f"{URL}/chat/completions").mock(return_value=httpx.Response(200, json=answer(VALID)))
    queue = FakeQueue()
    await queue.enqueue_photo("p1", "/photos/1.jpg")
    analyser = PhotoAnalyser(queue, vision(), load)
    assert await analyser.drain() == 1
    assert queue.done["p1"]["photo"] == "/photos/1.jpg"
    assert await analyser.structural_damage(["/photos/1.jpg"]) is False


@respx.mock
async def test_drain_stops_when_the_link_is_down():
    respx.post(f"{URL}/chat/completions").mock(return_value=httpx.Response(503))
    queue = FakeQueue()
    await queue.enqueue_photo("p1", "/photos/1.jpg")
    await queue.enqueue_photo("p2", "/photos/2.jpg")
    analyser = PhotoAnalyser(queue, vision(), load)
    assert await analyser.drain() == 0
    assert queue.failed == ["p1"]


async def test_structural_damage_comes_only_from_a_stored_verdict():
    queue = FakeQueue()
    await queue.enqueue_photo("p1", "/photos/1.jpg")
    await queue.mark_analysed("p1", PhotoVerdict(photo="/photos/1.jpg", structural_damage=True,
                                                 severity="grave").model_dump())
    analyser = PhotoAnalyser(queue, vision(), load)
    assert await analyser.structural_damage(["/photos/1.jpg", "/photos/2.jpg"]) is True
    assert await analyser.structural_damage(["/photos/2.jpg"]) is False
