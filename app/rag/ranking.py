"""Final ranking, shared by the two retrieval backends.

The system can answer from pgvector (production) or from the in-memory index (offline,
tests, MCP).  Both produce two candidate rankings and then apply the same rules: RRF
fusion, expired manuals never answer, metadata weights.  Keeping those rules in one
function is what stops the offline path from ranking differently than the plant one.
"""

from __future__ import annotations

import re

from app.rag.codes import translate_codes

# Candidates taken from each ranking before fusion, and the relative weight of the
# vector ranking against the lexical one (the lexical side carries the exact terms).
CANDIDATES = 30
FUSION_WEIGHTS = [1.0, 0.1]

OTHER_MODEL_RE = re.compile(
    r"tx-?250|tx-?500|fc-?24|fc-?96|pia-?1|pia-?2|otros modelos|otra familia",
    re.IGNORECASE,
)
MANUFACTURER_STOPWORDS = {"industrial", "gerencia", "operaciones", "contratos", "yacimiento", "srl", "sa"}


def manufacturer_words(text: str) -> set[str]:
    """Significant words of a manufacturer name ("Trimax Industrial S.A." -> {"trimax"})."""
    words = re.findall(r"[a-z]{4,}", (text or "").lower())
    return {word for word in words if word not in MANUFACTURER_STOPWORDS}


def rrf(lists: list[list[str]], k: int = 60, weights: list[float] | None = None) -> dict[str, float]:
    """Reciprocal rank fusion of several citation rankings."""
    fused: dict[str, float] = {}
    for index, ranking in enumerate(lists):
        weight = weights[index] if weights else 1.0
        for rank, citation in enumerate(ranking):
            fused[citation] = fused.get(citation, 0.0) + weight / (k + rank + 1)
    return fused


def metadata_weight(chunk: dict, query: str, equipment_tags: set[str]) -> float:
    """Confidence multiplier from the document metadata (revision, model, maker)."""
    weight = 1.0
    if chunk.get("current") is False:
        weight *= 0.6
    # Only the section title identifies "other models" sections; legitimate sections
    # often mention TX-250/TX-500 in passing and must not be penalised. The penalty only
    # applies when the question is not about that other model: an operator asking for
    # PIA-1 must still get the PIA-1 section.
    heading = f"{chunk.get('title', '')} {chunk.get('section_key', '')}"
    if OTHER_MODEL_RE.search(heading) and not OTHER_MODEL_RE.search(query):
        weight *= 0.55
    chunk_equipment = {str(tag).lower() for tag in (chunk.get("equipment") or [])}
    asked_equipment = {tag.lower() for tag in equipment_tags}
    if chunk_equipment & asked_equipment:
        weight *= 1.2
    elif asked_equipment and chunk.get("doc", "").startswith("historial"):
        weight *= 0.8
    # Manufacturer: the document issuer is part of the metadata, so a question that
    # names a manufacturer prefers that maker's manual and loses weight against another.
    asked = manufacturer_words(query)
    maker = manufacturer_words(chunk.get("manufacturer") or "")
    if asked and maker:
        weight *= 1.15 if (asked & maker) else 0.8
    return weight


def expand_query(query: str) -> str:
    """Add the plant fault codes a manufacturer code refers to (MBP-4 §6).

    The mapping is lexical, so it is applied to the BM25/tsquery side only: the vector
    query keeps the operator's words.
    """
    codes = translate_codes(query)
    return f"{query} {' '.join(sorted(codes))}" if codes else query


def rank(rankings: list[list[str]], chunks_by_citation: dict[str, dict], query: str,
         equipment_tags: set[str], k: int) -> list[dict]:
    """Fuse the candidate rankings and return the ``k`` best citations."""
    fused = rrf(rankings, weights=FUSION_WEIGHTS)
    scored: list[tuple[float, str]] = []
    for citation, score in fused.items():
        chunk = chunks_by_citation.get(citation)
        if chunk is None:
            continue
        if chunk.get("current") is False:
            # An expired manual never answers: its limits are the trap this corpus
            # tests. It stays indexed (searchable when someone asks for it by id), but
            # it does not compete in the operator's ranking.
            continue
        scored.append((score * metadata_weight(chunk, query, equipment_tags), citation))
    scored.sort(reverse=True)
    return [
        {
            "citation": citation,
            "score": round(score, 6),
            "doc": chunks_by_citation[citation].get("doc", ""),
            "title": chunks_by_citation[citation].get("title", ""),
            "current": True,
            "text": chunks_by_citation[citation].get("text", ""),
        }
        for score, citation in scored[:k]
    ]
