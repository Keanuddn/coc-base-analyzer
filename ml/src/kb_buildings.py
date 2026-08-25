"""Load sourced building combat roles from knowledge-base/buildings.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from model_utils import REPO_ROOT

DEFAULT_BUILDINGS_YAML = REPO_ROOT / "knowledge-base" / "buildings.yaml"


def load_building_kb(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_BUILDINGS_YAML
    with target.open(encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)
    buildings = payload.get("buildings")
    if not isinstance(buildings, dict):
        raise ValueError(f"No buildings map in {target}")
    return buildings


def targets_for(class_name: str, *, kb: dict[str, Any] | None = None) -> list[str] | str:
    row = (kb or load_building_kb()).get(class_name) or {}
    raw = row.get("targets", "unknown")
    if raw == "unknown" or raw == "mode_dependent":
        return raw
    if raw is None:
        return "unknown"
    return list(raw)


def _range_payload(row: dict[str, Any]) -> dict[str, float] | float | None:
    if "range_tiles" in row:
        return row["range_tiles"]
    if "range_tiles_min" in row or "range_tiles_max" in row:
        out: dict[str, float] = {}
        if "range_tiles_min" in row:
            out["min"] = row["range_tiles_min"]
        if "range_tiles_max" in row:
            out["max"] = row["range_tiles_max"]
        return out
    return None


def enrich_building(building: dict[str, Any], *, kb: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach sourced KB fields. Missing class → targets unknown (do not guess)."""
    table = kb if kb is not None else load_building_kb()
    name = str(building.get("class", ""))
    row = table.get(name) or {}
    out = dict(building)
    out["wiki_name"] = row.get("wiki_name", name)
    out["category"] = row.get("category", "unknown")
    out["targets"] = targets_for(name, kb=table)
    if "damage_type" in row:
        out["damage_type"] = row["damage_type"]
    rng = _range_payload(row)
    if rng is not None:
        out["range_tiles"] = rng
    return out


def _target_bucket(targets: list[str] | str) -> str:
    if targets == "unknown" or targets == "mode_dependent":
        return "unknown"
    if not targets:
        return "none"
    has_air = "air" in targets
    has_ground = "ground" in targets
    if has_air and has_ground:
        return "both"
    if has_air:
        return "air"
    if has_ground:
        return "ground"
    return "unknown"


def summarize_detections(buildings: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by category and targeting. mode_dependent counts as unknown."""
    by_category: dict[str, int] = {}
    by_class: dict[str, int] = {}
    targeting = {"air": 0, "ground": 0, "both": 0, "unknown": 0, "none": 0}
    for b in buildings:
        cat = str(b.get("category", "unknown"))
        by_category[cat] = by_category.get(cat, 0) + 1
        cls = str(b.get("class", "?"))
        by_class[cls] = by_class.get(cls, 0) + 1
        if cat == "defense":
            targeting[_target_bucket(b.get("targets", "unknown"))] += 1
    return {
        "by_category": by_category,
        "by_class": by_class,
        "defenses_targeting": targeting,
        "kb": "knowledge-base/buildings.yaml",
    }


def attach_knowledge_base(payload: dict[str, Any], *, kb: dict[str, Any] | None = None) -> dict[str, Any]:
    table = kb if kb is not None else load_building_kb()
    payload["buildings"] = [enrich_building(b, kb=table) for b in payload.get("buildings") or []]
    payload["summary"] = summarize_detections(payload["buildings"])
    return payload
