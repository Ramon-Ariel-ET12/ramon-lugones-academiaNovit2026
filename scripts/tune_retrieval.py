"""Tune the hybrid fusion on the provided suite (development tool)."""

from __future__ import annotations

import re

from app.rag.bm25 import BM25, cosine
from app.rag.indexer import Embedder
from app.rag.ranking import rrf
from evaluacion.retrieval_eval import evaluate, load

OTHER_MODEL = re.compile(r"tx-?250|tx-?500|fc-?24|fc-?96|pia-?1|pia-?2")


def rev_c(rows, ks=5):
    count = 0
    for row in rows:
        relevant = set(row["relevantes"])
        if not any(c.startswith("TX350-D") for c in relevant):
            continue
        top = row["top"][:ks]
        pos_rel = next((i for i, c in enumerate(top) if c in relevant), None)
        pos_c = next((i for i, c in enumerate(top) if c.startswith("TX350-C")), None)
        if pos_c is not None and (pos_rel is None or pos_c < pos_rel):
            count += 1
    return count


def main():
    suite, fragments = load()
    bm25 = BM25(fragments)
    by_id = {fragment["citation"]: fragment for fragment in fragments}
    embedder = Embedder("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    texts = [f"{fragment['title']}\n{fragment['text']}" for fragment in fragments]
    vectors = embedder.passages(texts)
    base = evaluate(lambda q, k: [c for c, _ in bm25.search(q, k)], suite)
    print("BM25", base["total"], "revC", rev_c(base["preguntas"]))

    def make(vector_weight, current_penalty, other_penalty, title_only):
        def search(query, k):
            lex = [c for c, _ in bm25.search(query, 30)]
            qv = embedder.query(query)
            scored = sorted(((cosine(qv, v), fragment) for v, fragment in zip(vectors, fragments, strict=False)),
                            key=lambda item: item[0], reverse=True)
            vec = [fragment["citation"] for _, fragment in scored[:30]]
            fused = rrf([lex, vec], weights=[1.0, vector_weight])
            ranked = []
            for citation, score in fused.items():
                fragment = by_id[citation]
                title = f"{fragment['title']} {fragment['section_key']}".lower()
                body = fragment["text"].lower()
                weight = 1.0
                if not fragment["current"]:
                    weight *= current_penalty
                if OTHER_MODEL.search(title if title_only else title + " " + body):
                    weight *= other_penalty
                ranked.append((score * weight, citation))
            ranked.sort(reverse=True)
            return [c for _, c in ranked[:k]]
        return search

    for vw in (0.05, 0.1, 0.2, 0.25):
        for cp in (0.6,):
            for op in (0.55,):
                result = evaluate(make(vw, cp, op, True), suite)
                total = result["total"]
                print(f"vw={vw} cp={cp} op={op} title_only -> hit@5={total['hit@5']} recall@5={total['recall@5']} "
                      f"mrr={total['mrr']} revC={rev_c(result['preguntas'])} dist@5={total['distractor@5']}")


if __name__ == "__main__":
    main()
