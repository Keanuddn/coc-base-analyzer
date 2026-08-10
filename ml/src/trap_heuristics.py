"""Trap location probability map stub (Phase 2 placeholder).

DISCLAIMER: Trap positions cannot be reliably inferred from static war-base
screenshots alone. This module returns an empty probability map until a
dedicated trap-detection or layout-reasoning model exists.
"""

from __future__ import annotations

from typing import Any


def estimate_trap_probabilities(
    detections: list[dict[str, Any]],
    grid_size: int = 44,
) -> dict[str, Any]:
    """Return a stub trap probability map."""
    return {
        "grid_size": grid_size,
        "trap_probability_map": [],
        "max_probability": 0.0,
        "method": "stub",
        "disclaimer": (
            "Trap inference is NOT implemented. Do not use this output for "
            "attack planning. Static screenshots do not reveal hidden traps."
        ),
        "detection_count_used": len(detections),
    }
