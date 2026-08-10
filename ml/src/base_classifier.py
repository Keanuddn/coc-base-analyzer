"""Rule-based town hall / base type heuristics from building distribution (stub)."""

from __future__ import annotations

from collections import Counter
from typing import Any


def classify_base_type(detections: list[dict[str, Any]]) -> dict[str, Any]:
    """Estimate TH level and base archetype from detected building counts.

    This is a placeholder — production logic should combine CV detections with
    knowledge-base rules and explicit TH-level classes once labeled.
    """
    counts = Counter(d.get("class", "unknown") for d in detections)
    total = sum(counts.values())

    th_guess = "unknown"
    if counts.get("th13", 0) >= 1:
        th_guess = "th13"
    elif counts.get("scattershot", 0) >= 2:
        th_guess = "th13-th15"
    elif counts.get("xbow", 0) >= 3:
        th_guess = "th11-th13"

    return {
        "estimated_th": th_guess,
        "building_counts": dict(counts),
        "total_detections": total,
        "confidence": "low",
        "disclaimer": "Stub heuristic — not validated; use manual review or future classifier.",
    }
