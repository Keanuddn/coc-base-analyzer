"""Schema for decoded CoC base share links (Phase 1b)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BuildingPlacement:
    building_type: str
    level: int
    x: int
    y: int
    rotation: int = 0


@dataclass(slots=True)
class TrapPlacement:
    trap_type: str
    level: int
    x: int
    y: int


@dataclass(slots=True)
class DecodedBase:
    link: str
    town_hall_level: int | None = None
    village_type: str | None = None  # HV (home) or WB (war)
    layout_slot: int | None = None  # 1=layout1, 2=layout2, 3=war
    collection_index: int | None = None
    layout_fingerprint: str | None = None  # hex HMAC tag (bytes 8..24)
    link_format: str = "unknown"  # open_layout | copy_army | legacy | unknown
    buildings: list[BuildingPlacement] = field(default_factory=list)
    traps: list[TrapPlacement] = field(default_factory=list)
    raw_payload: str | None = None
    decode_version: str = "structural-1.0"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "link": self.link,
            "town_hall_level": self.town_hall_level,
            "village_type": self.village_type,
            "layout_slot": self.layout_slot,
            "collection_index": self.collection_index,
            "layout_fingerprint": self.layout_fingerprint,
            "link_format": self.link_format,
            "buildings": [
                {
                    "building_type": b.building_type,
                    "level": b.level,
                    "x": b.x,
                    "y": b.y,
                    "rotation": b.rotation,
                }
                for b in self.buildings
            ],
            "traps": [
                {"trap_type": t.trap_type, "level": t.level, "x": t.x, "y": t.y}
                for t in self.traps
            ],
            "raw_payload": self.raw_payload,
            "decode_version": self.decode_version,
            "warnings": self.warnings,
        }
