"""Generate bulk synthetic YOLO-labeled village renders (perfect labels).

Layouts are random-but-plausible occupancy on the 44×44 editor grid.
Count ranges and tile footprints are collision/variety parameters — not
combat stats or wiki army tables.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

from link_decoder.schema import BuildingPlacement
from renderer.domain_randomization import DomainRandomizationConfig
from renderer.isometric_renderer import GRID_SIZE, IsometricRenderer

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PIPELINE_ROOT / "datasets" / "processed" / "synthetic_v1"
DEFAULT_COUNT = 200
TOWN_HALL_LEVELS = (15, 16)

# Active classes from building_type_map aliases + town_hall (no hero pads).
SYNTHETIC_BUILDING_TYPES: tuple[str, ...] = (
    "canon",
    "mortar",
    "inferno",
    "eagle",
    "xbow",
    "scattershot",
    "wizztower",
    "ad",
    "bombtower",
    "airsweeper",
    "clancastle",
    "town_hall",
)

# Layout-editor occupancy in tiles (collision only).
TILE_FOOTPRINTS: dict[str, int] = {
    "town_hall": 4,
    "clancastle": 3,
    "eagle": 4,
    "inferno": 2,
    "canon": 3,
    "mortar": 3,
    "wizztower": 3,
    "ad": 3,
    "airsweeper": 2,
    "xbow": 3,
    "bombtower": 3,
    "scattershot": 3,
}

# How many of each type to try placing. Not TH unlock tables.
COUNT_RANGES: dict[str, tuple[int, int]] = {
    "town_hall": (1, 1),
    "clancastle": (1, 1),
    "eagle": (0, 1),
    "scattershot": (1, 2),
    "inferno": (1, 3),
    "xbow": (2, 4),
    "canon": (2, 5),
    "mortar": (2, 4),
    "wizztower": (2, 5),
    "ad": (2, 4),
    "bombtower": (1, 2),
    "airsweeper": (1, 2),
}


def _fits(occupied: set[tuple[int, int]], x: int, y: int, size: int) -> bool:
    if x < 0 or y < 0 or x + size > GRID_SIZE or y + size > GRID_SIZE:
        return False
    for dx in range(size):
        for dy in range(size):
            if (x + dx, y + dy) in occupied:
                return False
    return True


def _mark(occupied: set[tuple[int, int]], x: int, y: int, size: int) -> None:
    for dx in range(size):
        for dy in range(size):
            occupied.add((x + dx, y + dy))


def _try_place(
    occupied: set[tuple[int, int]],
    size: int,
    rng: random.Random,
    *,
    prefer_center: bool = False,
    max_attempts: int = 80,
) -> tuple[int, int] | None:
    if prefer_center:
        cx = GRID_SIZE // 2 - size // 2
        for radius in range(0, 14):
            candidates: list[tuple[int, int]] = []
            lo = max(0, cx - radius)
            hi = min(GRID_SIZE - size, cx + radius)
            for x in range(lo, hi + 1):
                for y in range(lo, hi + 1):
                    if _fits(occupied, x, y, size):
                        candidates.append((x, y))
            if candidates:
                return rng.choice(candidates)
        return None

    for _ in range(max_attempts):
        x = rng.randint(0, GRID_SIZE - size)
        y = rng.randint(0, GRID_SIZE - size)
        if _fits(occupied, x, y, size):
            return x, y
    for x in range(0, GRID_SIZE - size + 1):
        for y in range(0, GRID_SIZE - size + 1):
            if _fits(occupied, x, y, size):
                return x, y
    return None


def generate_random_layout(rng: random.Random, town_hall_level: int) -> list[BuildingPlacement]:
    """Place a TH plus a random mix of active defenses without grid overlap."""
    occupied: set[tuple[int, int]] = set()
    placements: list[BuildingPlacement] = []

    th_size = TILE_FOOTPRINTS["town_hall"]
    pos = _try_place(occupied, th_size, rng, prefer_center=True)
    if pos is None:
        raise RuntimeError("Could not place town hall on empty grid")
    _mark(occupied, pos[0], pos[1], th_size)
    placements.append(BuildingPlacement("town_hall", level=town_hall_level, x=pos[0], y=pos[1]))

    order = [name for name in SYNTHETIC_BUILDING_TYPES if name != "town_hall"]
    rng.shuffle(order)
    for building_type in order:
        lo, hi = COUNT_RANGES[building_type]
        count = rng.randint(lo, hi)
        size = TILE_FOOTPRINTS[building_type]
        for _ in range(count):
            pos = _try_place(occupied, size, rng)
            if pos is None:
                break
            _mark(occupied, pos[0], pos[1], size)
            # Sprite level is a visual hint; renderer caps to files on disk.
            level = rng.randint(5, 20)
            placements.append(BuildingPlacement(building_type, level=level, x=pos[0], y=pos[1]))
    return placements


def generate_synthetic_dataset(
    count: int = DEFAULT_COUNT,
    output_dir: Path = DEFAULT_OUTPUT,
    seed: int = 42,
    *,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """Render ``count`` layouts to ``output_dir/th{15,16}/synthetic_XXXX.png`` + YOLO txt."""
    renderer = IsometricRenderer(use_placeholders=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    present = 0
    skipped_existing = 0
    boxes = 0
    warnings: list[str] = []

    for idx in range(count):
        th_level = TOWN_HALL_LEVELS[idx % len(TOWN_HALL_LEVELS)]
        th_dir = output_dir / f"th{th_level}"
        th_dir.mkdir(parents=True, exist_ok=True)
        out_png = th_dir / f"synthetic_{idx:04d}.png"
        out_txt = th_dir / f"synthetic_{idx:04d}.txt"
        if skip_existing and out_png.is_file() and out_txt.is_file():
            skipped_existing += 1
            present += 1
            continue

        layout_rng = random.Random(seed + idx * 1009 + th_level)
        placements = generate_random_layout(layout_rng, town_hall_level=th_level)
        dr_cfg = DomainRandomizationConfig(seed=seed + idx)
        result = renderer.render_to_files(
            placements,
            out_png,
            domain_randomization=dr_cfg,
            seed=seed + idx,
        )
        present += 1
        boxes += len(result.labels)
        warnings.extend(result.warnings)

    summary = {
        "images": present,
        "skipped_existing": skipped_existing,
        "boxes": boxes,
        "output_dir": str(output_dir),
        "warning_count": len(warnings),
    }
    logging.info(
        "Synthetic dataset: %d images (%d skipped existing), %d new boxes → %s",
        present,
        skipped_existing,
        boxes,
        output_dir,
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate bulk synthetic YOLO labels from the isometric renderer."
    )
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Number of layouts (default: 200)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"Output dir (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="Overwrite existing PNG+txt pairs")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.count < 1:
        parser.error("--count must be >= 1")

    summary = generate_synthetic_dataset(
        count=args.count,
        output_dir=args.output,
        seed=args.seed,
        skip_existing=not args.force,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
