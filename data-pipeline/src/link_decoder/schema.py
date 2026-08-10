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
    buildings: list[BuildingPlacement] = field(default_factory=list)
    traps: list[TrapPlacement] = field(default_factory=list)
    raw_payload: str | None = None
    decode_version: str = "stub-0.1"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "link": self.link,
            "town_hall_level": self.town_hall_level,
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
