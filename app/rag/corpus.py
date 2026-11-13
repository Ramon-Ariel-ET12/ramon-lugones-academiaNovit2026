"""The course corpus: one shape, one loader.

The fragments arrive as ``fragmentos.jsonl`` (course shape: ``titulo``/``texto``/
``clave``/``vigente``/``fabricante``) and live in the database as chunks of the same
concept (``title``/``text``/``section_key``/``current``/``manufacturer``).  Everything
above this module works with the canonical shape, so the retrieval code never needs to
know which of the two it is looking at.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings

FRAGMENTS_FILE = "fragmentos.jsonl"


def canonical(fragment: dict) -> dict:
    """Normalise one corpus fragment to the chunk shape used by the index and the DB."""
    if "text" in fragment:
        return fragment
    return {
        "id": fragment["id"],
        "citation": fragment["id"],
        "doc": fragment.get("doc", ""),
        "number": str(fragment.get("numero") or ""),
        "title": str(fragment.get("titulo") or ""),
        "section_key": str(fragment.get("clave") or ""),
        "page": fragment.get("pagina"),
        "current": fragment.get("vigente") is not False,
        "manufacturer": str(fragment.get("fabricante") or ""),
        "equipment": [str(tag).upper() for tag in (fragment.get("equipment") or [])],
        "text": fragment["texto"],
    }


def load_fragments(path: Path | str) -> list[dict]:
    """Read a JSONL corpus file into canonical chunks."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [canonical(json.loads(line)) for line in lines if line.strip()]


def bundled_path(settings: Settings) -> Path:
    return Path(settings.evaluation_dir) / FRAGMENTS_FILE


def bundled_fragments(settings: Settings) -> list[dict]:
    """The corpus shipped in ``evaluacion/`` (used when the plant API is unreachable)."""
    return load_fragments(bundled_path(settings))
