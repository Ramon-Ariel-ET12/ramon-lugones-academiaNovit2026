"""Index the plant corpus into pgvector with citable metadata."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any

from app.config import Settings
from app.integrations.plant_api import PlantClient
from app.persistence.repository import Repository
from app.rag.corpus import bundled_fragments, canonical

log = logging.getLogger(__name__)

EMBED_DIM = 384
DEFAULT_TAG_RE = re.compile(r"\b([BF]-\d{3}[AB]?|TK-\d{3}|FT-\d{3})\b", re.IGNORECASE)


def _metadata_by_doc(documents: dict, equipment_makers: dict[str, str] | None = None) -> dict:
    """Document metadata plus the equipment → manufacturer map used for order histories.

    A manual's issuer is the maker of the machines it documents (Trimax, Filtrapat).
    An order history has no issuer of its own, so its manufacturer comes from
    ``GET /api/planta`` (``equipos[].fabricante``); the issuer of whichever manual
    happens to list the equipment is not the equipment's maker.
    """
    docs: dict[str, dict] = {}
    makers: dict[str, str] = {}
    for item in documents.get("documentos", []):
        info: dict = {"manufacturer": item.get("emisor") or "", "equipment": item.get("equipos") or []}
        docs[item["id"]] = info
        for tag in info["equipment"]:
            if tag and info["manufacturer"]:
                makers[str(tag).upper()] = info["manufacturer"]
    known = sorted({tag for info in docs.values() for tag in info["equipment"]} | set(makers))
    tag_re = (re.compile(r"\b(" + "|".join(re.escape(tag) for tag in known) + r")\b", re.IGNORECASE)
              if known else DEFAULT_TAG_RE)
    return {"docs": docs, "makers": makers,
            "equipment_makers": {str(k).upper(): v for k, v in (equipment_makers or {}).items()},
            "tag_re": tag_re}


def _chunk(fragment: dict, meta: dict) -> dict:
    """One corpus fragment -> one indexed chunk, with the metadata the reranker uses."""
    chunk = canonical(fragment)
    doc = chunk["doc"]
    info = meta["docs"].get(doc, {})
    equipment = [str(tag).upper() for tag in (info.get("equipment") or [])]
    if not equipment:
        # Order histories carry the TAG in their title ("OT-24-0001 B-101 T-B-VAL") but
        # the plant's document metadata has no equipment list for the collection.
        heading = f"{chunk['title']} {chunk['number']}"
        equipment = sorted({match.group(1).upper() for match in meta["tag_re"].finditer(heading)})
    manufacturer = str(info.get("manufacturer") or "")
    if doc == "historial":
        # The order history is not a document: attribute it to the equipment's maker.
        manufacturer = next((meta["equipment_makers"][tag] for tag in equipment
                             if tag in meta["equipment_makers"]), "")
    elif not manufacturer:
        manufacturer = next((meta["makers"][tag] for tag in equipment if tag in meta["makers"]), "")
    if not chunk["section_key"] and doc == "historial":
        chunk["section_key"] = "OT"
    return {
        **chunk,
        "manufacturer": manufacturer,
        "equipment": equipment,
        "content_hash": hashlib.sha1(chunk["text"].encode("utf-8")).hexdigest()[:16],
    }


class Embedder:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model: Any = None

    def load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def passages(self, texts: list[str]) -> list[list[float]]:
        model = self.load()
        return [list(map(float, vector)) for vector in model.embed([f"passage: {text}" for text in texts])]

    def query(self, text: str) -> list[float]:
        model = self.load()
        return list(map(float, next(iter(model.embed([f"query: {text}"])))))


async def ensure_index(repo: Repository, plant: PlantClient, settings: Settings) -> int:
    count = await repo.rag_count()
    try:
        fragments = await plant.fragments()
        documents = await plant.documents()
        definition = await plant.definition()
        makers = {item["tag"]: item.get("fabricante") for item in definition.get("equipos", [])
                  if item.get("fabricante")}
    except Exception as exc:  # noqa: BLE001
        log.warning("plant corpus unavailable, using bundled snapshot: %s", exc)
        fragments = bundled_fragments(settings)
        documents = {"documentos": []}
        makers = {}
    meta = _metadata_by_doc(documents, makers)
    chunks = [_chunk(fragment, meta) for fragment in fragments]
    if count >= len(chunks):
        # Text and embeddings are already there. Refresh the metadata a newer indexer
        # can derive (equipment/manufacturer for order histories) without re-embedding.
        await repo.rag_refresh_metadata(chunks)
        return count
    embedder = Embedder(settings.embedding_model)
    texts = [f"{chunk['title']}\n{chunk['text']}" for chunk in chunks]
    embeddings = await asyncio.to_thread(embedder.passages, texts)
    await repo.rag_upsert(chunks, embeddings)
    return len(chunks)
