"""LangChain core for the note pipeline.

The chain is deterministic by design: safety detection and extraction are ordinary
code.  An optional local language model is used only to read unusual free-text replies.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.runnables import RunnableLambda

from app.domain.models import PartDraft, PlantSnapshot
from app.domain.parser import parse_transcript


@dataclass
class AgentInput:
    transcript: str
    note_id: str
    ts: object
    photos: list[str]


class NoteAgent:
    """Transcript -> draft. The safety code travels inside the draft, already detected."""

    def __init__(self, snapshot: PlantSnapshot):
        self.snapshot = snapshot
        self.chain = RunnableLambda(self._extract)

    def _extract(self, data: AgentInput) -> PartDraft:
        return parse_transcript(data.transcript, self.snapshot, note_id=data.note_id,
                                ts=data.ts, photos=data.photos)  # type: ignore[arg-type]

    def analyze(self, transcript: str, note_id: str, ts, photos: list[str]) -> PartDraft:
        return self.chain.invoke(AgentInput(transcript, note_id, ts, list(photos or [])))
