"""The contractor's price list, read from the contract itself (Entrega 2).

The certification amount comes from the ORDER and the price list of CT-SVP-2025, never
from what the closure declares. The list is parsed from the indexed document (§2.1,
Anexo II) instead of being copied into the code, so a new revision of the contract
changes the amount without touching the rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

VIGENTE_DESDE = date(2025, 1, 1)

# Task code -> contract item (Anexo II). Anything else has no closed price.
ITEM_OF_TASK = {"T-B-ROD": "SVP-01", "T-B-ALI": "SVP-02", "I-VIB": "SVP-03"}
HOUR_ITEMS = {"SVP-04", "SVP-05"}
MOBILISATION_ITEM = "SVP-06"
EMERGENCY_ITEM = "SVP-07"

# The same table appears as a markdown row ("| SVP-01 | … |") in the contract file and as
# a flat row ("SVP-01 | …") in the indexed chunk, so the outer pipes are optional.
ROW = re.compile(
    r"^\s*\|?\s*(?P<code>SVP-\d{2})\s*\|\s*(?P<desc>[^|]*)\|\s*(?P<unit>[^|]*)\|\s*"
    r"USD\s*(?P<price>[\d.,]+)\s*\|\s*(?P<hours>[^|]*?)\s*\|?\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ItemPrice:
    code: str
    description: str
    unit: str
    price_usd: float
    hours_included: float

    @property
    def per_equipment(self) -> bool:
        return "equipo" in self.unit.lower()


def _usd(text: str) -> float:
    """'1.150' is one thousand one hundred and fifty: dots group thousands."""
    text = text.strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    return float(text)


def _hours(text: str) -> float:
    text = (text or "").strip()
    return _usd(text) if re.fullmatch(r"[\d.,]+", text) else 0.0


class PriceList:
    def __init__(self, items: dict[str, ItemPrice]):
        self.items = items

    def __contains__(self, code: str) -> bool:
        return code in self.items

    def __len__(self) -> int:
        return len(self.items)

    @classmethod
    def from_markdown(cls, text: str) -> PriceList:
        items: dict[str, ItemPrice] = {}
        for match in ROW.finditer(text or ""):
            code = match["code"]
            items[code] = ItemPrice(code=code, description=match["desc"].strip(),
                                    unit=match["unit"].strip(), price_usd=_usd(match["price"]),
                                    hours_included=_hours(match["hours"]))
        return cls(items)

    @classmethod
    def from_chunks(cls, chunks: list[dict]) -> PriceList:
        """The §2.1 table as it was indexed (the chunk text keeps the rows flat)."""
        price_rows = [chunk.get("text", "") for chunk in chunks
                      if str(chunk.get("doc", "")).upper() == "CT-SVP-2025"]
        return cls.from_markdown("\n".join(price_rows))

    def hours_included(self, tasks: list[str], equipment_count: int = 1) -> float:
        total = 0.0
        for task in tasks:
            item = self.items.get(ITEM_OF_TASK.get(task, ""))
            if item is not None:
                total += item.hours_included * (equipment_count if item.per_equipment else 1)
        return total

    def amount_for(self, tasks: list[str], *, equipment_count: int = 1,
                   started_at: str | None = None, emergency: bool = False) -> float | None:
        """The contract amount for the ordered work, or None when there is no closed price.

        A work started before 2025-01-01 is certified with CT-SVP-2022 (§1.2): we do not
        have that list, so the amount is unknown and the closure must say why.
        """
        if started_at and not _starts_from_2025(started_at):
            return None
        total = 0.0
        found = False
        for task in tasks:
            item = self.items.get(ITEM_OF_TASK.get(task, ""))
            if item is None:
                continue
            total += item.price_usd * (equipment_count if item.per_equipment else 1)
            found = True
        if not found:
            return None
        if emergency and EMERGENCY_ITEM in self.items:
            total += self.items[EMERGENCY_ITEM].price_usd
        return round(total, 2)


def _starts_from_2025(started_at: str) -> bool:
    try:
        return date.fromisoformat(str(started_at)[:10]) >= VIGENTE_DESDE
    except ValueError:
        return True
