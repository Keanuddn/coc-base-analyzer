"""Infer-only Town Hall gate: drop or remap classes that cannot exist at the known TH.

Unlock ``min_th`` comes from ``th_unlocks.yaml`` (sourced). YOLO names may differ
from placement slugs (``superwizztower`` vs ``super_wizard_tower``); mapping uses
``building_type_map.yaml`` ``yolo_label_overrides``. No invented min_th.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from model_utils import REPO_ROOT, model_class_names

UNLOCKS_PATH = (
    REPO_ROOT / "data-pipeline" / "src" / "renderer" / "sprites" / "th_unlocks.yaml"
)
TYPE_MAP_PATH = (
    REPO_ROOT / "data-pipeline" / "src" / "renderer" / "sprites" / "building_type_map.yaml"
)

# th13 is the frozen keremberke hall slot, not a reliable TH level.
DETECTABLE_HALL_CLASSES = frozenset({"th14", "th15", "th16", "th17", "th18"})

# Prefer remap over drop when the model confuses a merge pair (WT vs Super WT).
REMAP_WHEN_LOCKED: dict[str, str] = {
    "superwizztower": "wizztower",
}


@dataclass(frozen=True)
class ThGateTable:
    """Sourced min_th keyed by YOLO class name (and placement slug when different)."""

    min_th_by_name: dict[str, int]
    class_id_by_name: dict[str, int]
    remap_when_locked: dict[str, str] = field(default_factory=lambda: dict(REMAP_WHEN_LOCKED))


@dataclass
class GateResult:
    buildings: list[dict[str, Any]]
    town_hall: int | None
    town_hall_source: str
    applied: bool
    dropped: int = 0
    remapped: int = 0
    reason: str | None = None
    counts_before: Counter[str] = field(default_factory=Counter)
    counts_after: Counter[str] = field(default_factory=Counter)

    def as_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "applied": self.applied,
            "dropped": self.dropped,
            "remapped": self.remapped,
            "class_counts_before": dict(self.counts_before),
            "class_counts_after": dict(self.counts_after),
        }
        if self.reason:
            meta["reason"] = self.reason
        return meta


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {path}")
    return payload


def load_th_gate_table(
    *,
    unlocks_path: Path = UNLOCKS_PATH,
    type_map_path: Path = TYPE_MAP_PATH,
    class_names: list[str] | None = None,
) -> ThGateTable:
    unlocks = _load_yaml(unlocks_path)
    type_map = _load_yaml(type_map_path)
    buildings = unlocks.get("buildings", unlocks)
    if not isinstance(buildings, dict):
        raise ValueError(f"No buildings map in {unlocks_path}")

    overrides: dict[str, str] = dict(type_map.get("yolo_label_overrides") or {})
    min_th_by_name: dict[str, int] = {}
    for key, row in buildings.items():
        if not isinstance(row, dict) or "min_th" not in row:
            continue
        min_th = int(row["min_th"])
        yolo_name = overrides.get(str(key), str(key))
        min_th_by_name[str(key)] = min_th
        min_th_by_name[yolo_name] = min_th

    names = class_names if class_names is not None else model_class_names()
    class_id_by_name = {name: idx for idx, name in enumerate(names)}
    return ThGateTable(min_th_by_name=min_th_by_name, class_id_by_name=class_id_by_name)


def _hall_level(class_name: str) -> int | None:
    if class_name in DETECTABLE_HALL_CLASSES and class_name.startswith("th"):
        suffix = class_name[2:]
        if suffix.isdigit():
            return int(suffix)
    return None


def resolve_town_hall(
    buildings: list[dict[str, Any]],
    *,
    cli_th: int | None = None,
) -> tuple[int | None, str]:
    """CLI override wins. Else a th14–th18 box. th13-only or no hall → unknown."""
    if cli_th is not None:
        return int(cli_th), "cli"

    halls = [b for b in buildings if str(b.get("class")) in DETECTABLE_HALL_CLASSES]
    if not halls:
        return None, "unknown"

    def _key(b: dict[str, Any]) -> tuple[float, int]:
        level = _hall_level(str(b.get("class"))) or 0
        return (float(b.get("confidence") or 0.0), level)

    best = max(halls, key=_key)
    level = _hall_level(str(best.get("class")))
    if level is None:
        return None, "unknown"
    return level, "detection"


def gate_decision(
    class_name: str,
    town_hall: int,
    table: ThGateTable,
) -> tuple[str, str | None]:
    """Return ``('keep', None)``, ``('remap', new_name)``, or ``('drop', None)``."""
    min_th = table.min_th_by_name.get(class_name)
    if min_th is None or min_th <= town_hall:
        return "keep", None
    remap_to = table.remap_when_locked.get(class_name)
    if remap_to is not None:
        return "remap", remap_to
    return "drop", None


def apply_th_gate(
    buildings: list[dict[str, Any]],
    *,
    town_hall: int | None,
    town_hall_source: str,
    table: ThGateTable,
) -> GateResult:
    counts_before = Counter(str(b.get("class")) for b in buildings)
    if town_hall is None:
        return GateResult(
            buildings=list(buildings),
            town_hall=None,
            town_hall_source=town_hall_source,
            applied=False,
            reason="unknown_town_hall",
            counts_before=counts_before,
            counts_after=Counter(counts_before),
        )

    out: list[dict[str, Any]] = []
    dropped = 0
    remapped = 0
    for building in buildings:
        name = str(building.get("class", ""))
        action, new_name = gate_decision(name, town_hall, table)
        if action == "drop":
            dropped += 1
            continue
        if action == "remap" and new_name:
            updated = dict(building)
            updated["class"] = new_name
            if new_name in table.class_id_by_name:
                updated["class_id"] = table.class_id_by_name[new_name]
            out.append(updated)
            remapped += 1
            continue
        out.append(building)

    counts_after = Counter(str(b.get("class")) for b in out)
    return GateResult(
        buildings=out,
        town_hall=town_hall,
        town_hall_source=town_hall_source,
        applied=True,
        dropped=dropped,
        remapped=remapped,
        counts_before=counts_before,
        counts_after=counts_after,
    )


def attach_gate_metadata(payload: dict[str, Any], gate: GateResult) -> dict[str, Any]:
    payload["buildings"] = gate.buildings
    payload["detection_count"] = len(gate.buildings)
    payload["town_hall"] = gate.town_hall
    payload["town_hall_source"] = gate.town_hall_source
    payload["th_gate"] = gate.as_meta()
    return payload
