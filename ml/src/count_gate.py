"""Compare detection counts to sourced wiki maxima (th_unlocks.yaml).

Over-max → likely false positives. Under-max is not flagged: the screenshot
may crop buildings. No invented counts: missing count_by_th → no_wiki.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from th_gate import DETECTABLE_HALL_CLASSES, TYPE_MAP_PATH, UNLOCKS_PATH, _load_yaml

HALL_CLASSES = DETECTABLE_HALL_CLASSES | {"th13"}
SOURCE = "data-pipeline/src/renderer/sprites/th_unlocks.yaml"


@dataclass(frozen=True)
class CountRow:
    slug: str
    count_by_th: dict[int, int]
    merge_from_th: int | None


@dataclass(frozen=True)
class CountTable:
    by_name: dict[str, CountRow]


def _int_counts(raw: dict[Any, Any]) -> dict[int, int]:
    out: dict[int, int] = {}
    for key, value in raw.items():
        out[int(key)] = int(value)
    return out


def load_count_table(
    *,
    unlocks_path: Path = UNLOCKS_PATH,
    type_map_path: Path = TYPE_MAP_PATH,
) -> CountTable:
    unlocks = _load_yaml(unlocks_path)
    type_map = _load_yaml(type_map_path)
    buildings = unlocks.get("buildings", unlocks)
    if not isinstance(buildings, dict):
        raise ValueError(f"No buildings map in {unlocks_path}")
    overrides: dict[str, str] = dict(type_map.get("yolo_label_overrides") or {})

    by_name: dict[str, CountRow] = {}
    for slug, raw in buildings.items():
        if not isinstance(raw, dict) or "count_by_th" not in raw:
            continue
        counts = raw.get("count_by_th") or {}
        if not isinstance(counts, dict) or not counts:
            continue
        merge_raw = raw.get("merge_from_th")
        row = CountRow(
            slug=str(slug),
            count_by_th=_int_counts(counts),
            merge_from_th=int(merge_raw) if merge_raw is not None else None,
        )
        by_name[str(slug)] = row
        yolo_name = overrides.get(str(slug), str(slug))
        by_name[yolo_name] = row

    hall = by_name.get("town_hall")
    if hall is not None:
        for name in HALL_CLASSES:
            by_name[name] = hall
    return CountTable(by_name=by_name)


def wiki_max_for(class_name: str, th: int, table: CountTable) -> tuple[int | None, CountRow | None]:
    row = table.by_name.get(class_name)
    if row is None:
        return None, None
    return row.count_by_th.get(int(th)), row


def _class_counts(payload: dict[str, Any]) -> dict[str, int]:
    summary = payload.get("summary") or {}
    by_class = summary.get("by_class")
    if isinstance(by_class, dict) and by_class:
        return {str(k): int(v) for k, v in by_class.items()}
    counts: dict[str, int] = {}
    for building in payload.get("buildings") or []:
        name = str(building.get("class", "?"))
        counts[name] = counts.get(name, 0) + 1
    return counts


def _collapse_halls(counts: dict[str, int]) -> dict[str, int]:
    out = dict(counts)
    hall_hits = [(name, out.pop(name)) for name in list(out) if name in HALL_CLASSES]
    if not hall_hits:
        return out
    total = sum(n for _, n in hall_hits)
    names = [name for name, n in hall_hits if n]
    label = names[0] if len(names) == 1 else "town_hall"
    out[label] = out.get(label, 0) + total
    return out


def compare_counts(
    counts: dict[str, int],
    th: int | None,
    *,
    table: CountTable | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "th": th,
        "source": SOURCE,
        "applied": False,
        "over_max": [],
        "rows": [],
    }
    if th is None:
        meta["reason"] = "town hall unknown — no wiki max"
        return meta

    table = table if table is not None else load_count_table()
    meta["applied"] = True
    over_max: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for class_name, detected in sorted(
        _collapse_halls(counts).items(), key=lambda item: (-item[1], item[0])
    ):
        maximum, row = wiki_max_for(class_name, th, table)
        merge_cap = bool(row and row.merge_from_th is not None and th >= row.merge_from_th)
        entry: dict[str, Any] = {
            "class": class_name,
            "detected": int(detected),
            "wiki_max": maximum,
            "status": "no_wiki",
            "merge_cap": merge_cap,
        }
        if maximum is None:
            rows.append(entry)
            continue
        if detected > maximum:
            entry["status"] = "over"
            entry["excess"] = int(detected) - int(maximum)
            over_max.append(
                {
                    "class": class_name,
                    "detected": int(detected),
                    "wiki_max": int(maximum),
                    "excess": entry["excess"],
                    "merge_cap": merge_cap,
                }
            )
        else:
            entry["status"] = "ok"
        rows.append(entry)
    meta["over_max"] = over_max
    meta["rows"] = rows
    return meta


def attach_count_gate(
    payload: dict[str, Any],
    *,
    table: CountTable | None = None,
) -> dict[str, Any]:
    th = payload.get("town_hall")
    th_int = int(th) if th is not None else None
    payload["count_gate"] = compare_counts(_class_counts(payload), th_int, table=table)
    return payload
