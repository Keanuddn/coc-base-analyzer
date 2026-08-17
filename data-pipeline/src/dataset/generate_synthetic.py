"""Generate bulk synthetic YOLO-labeled village renders (perfect labels).

Layouts are random-but-plausible occupancy on the 44×44 editor grid.
Count ranges and tile footprints are collision/variety parameters — not
combat stats or wiki army tables.

Sprite levels use a **sprite-max** heuristic (not an official CoC cap):
one visual tier per image. TH16 = max ClashKing sprite index, TH15 = max-1.
Town hall is exact (``level_15.webp`` / ``level_16.webp``). See
``renderer/sprites/max_level_by_th.yaml``.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml

from link_decoder.schema import BuildingPlacement
from renderer.domain_randomization import DomainRandomizationConfig
from renderer.isometric_renderer import (
    BUILDING_TYPE_MAP_PATH,
    CLASHKING_HOME_VILLAGE,
    GRID_SIZE,
    IsometricRenderer,
    list_sprite_levels,
    _load_building_type_map,
    _slug_for_building_type,
)

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PIPELINE_ROOT.parent
DEFAULT_OUTPUT = PIPELINE_ROOT / "datasets" / "processed" / "synthetic_v1"
DEFAULT_PREVIEW_DIR = REPO_ROOT / "ml" / "notebooks" / "phase2_output"
LEVEL_POLICY_PATH = (
    PIPELINE_ROOT / "src" / "renderer" / "sprites" / "max_level_by_th.yaml"
)
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

PREVIEW_SPECS: tuple[tuple[str, int, int], ...] = (
    ("preview_th_strict_th15_a.png", 15, 1015),
    ("preview_th_strict_th15_b.png", 15, 2015),
    ("preview_th_strict_th16_a.png", 16, 1016),
    ("preview_th_strict_th16_b.png", 16, 2016),
)


@dataclass
class SpriteLevelCatalog:
    """Available sprite levels per synthetic building_type (disk, else yaml snapshot)."""

    levels_by_type: dict[str, list[int]]
    policy: str = "sprite-max"
    not_official_coc_cap: bool = True
    th16_visual_tier: str = "max"
    th15_visual_tier: str = "max-1"
    source_path: Path | None = None

    def levels_for(self, building_type: str) -> list[int]:
        levels = self.levels_by_type.get(building_type)
        if not levels:
            raise KeyError(f"No sprite levels catalogued for {building_type!r}")
        return list(levels)

    def sprite_level(self, building_type: str, town_hall_level: int) -> int:
        """Exactly one ClashKing file for this building on a TH15/TH16 image.

        Visual-tier proxy (not official CoC unlocks):
        town hall is exact; TH16 = max sprite index; TH15 = max-1.
        Buildings with fewer than 2 files use the only/highest file for both THs.
        """
        if building_type == "town_hall":
            levels = self.levels_for("town_hall")
            if town_hall_level not in levels:
                raise RuntimeError(
                    f"Town hall sprite level_{town_hall_level} not in catalog {levels}"
                )
            return town_hall_level
        levels = self.levels_for(building_type)
        if town_hall_level >= 16 or len(levels) < 2:
            return levels[-1]
        return levels[-2]

    @classmethod
    def load(
        cls,
        *,
        sprites_root: Path | None = None,
        policy_path: Path = LEVEL_POLICY_PATH,
        type_map_path: Path = BUILDING_TYPE_MAP_PATH,
    ) -> SpriteLevelCatalog:
        policy = _load_level_policy(policy_path)
        type_map = _load_building_type_map(type_map_path)
        observed: dict[str, int] = {str(k): int(v) for k, v in (policy.get("sprite_max_observed") or {}).items()}
        root = sprites_root or CLASHKING_HOME_VILLAGE
        levels_by_type: dict[str, list[int]] = {}
        for building_type in SYNTHETIC_BUILDING_TYPES:
            slug = _slug_for_building_type(building_type, type_map)
            disk = list_sprite_levels(slug, root) if slug else []
            if disk:
                levels_by_type[building_type] = disk
                continue
            mx = observed.get(slug or "") or observed.get(building_type)
            if mx is None:
                raise RuntimeError(
                    f"No ClashKing sprites and no yaml snapshot for {building_type!r} (slug={slug})"
                )
            levels_by_type[building_type] = list(range(1, mx + 1))
        return cls(
            levels_by_type=levels_by_type,
            policy=str(policy.get("policy", "sprite-max")),
            not_official_coc_cap=bool(policy.get("not_official_coc_cap", True)),
            th16_visual_tier=str(policy.get("th16_visual_tier", "max")),
            th15_visual_tier=str(policy.get("th15_visual_tier", "max-1")),
            source_path=policy_path,
        )


def _load_level_policy(path: Path = LEVEL_POLICY_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Level policy must be a mapping: {path}")
    return data


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


def generate_random_layout(
    rng: random.Random,
    town_hall_level: int,
    *,
    catalog: SpriteLevelCatalog | None = None,
) -> list[BuildingPlacement]:
    """Place a TH plus a random mix of active defenses without grid overlap.

    Town hall sprite is exactly ``town_hall_level``. Every other building type
    uses one file: TH16 = max sprite index, TH15 = max-1 (or the only file).
    """
    catalog = catalog or SpriteLevelCatalog.load()

    occupied: set[tuple[int, int]] = set()
    placements: list[BuildingPlacement] = []

    th_size = TILE_FOOTPRINTS["town_hall"]
    pos = _try_place(occupied, th_size, rng, prefer_center=True)
    if pos is None:
        raise RuntimeError("Could not place town hall on empty grid")
    _mark(occupied, pos[0], pos[1], th_size)
    th_level = catalog.sprite_level("town_hall", town_hall_level)
    placements.append(BuildingPlacement("town_hall", level=th_level, x=pos[0], y=pos[1]))

    order = [name for name in SYNTHETIC_BUILDING_TYPES if name != "town_hall"]
    rng.shuffle(order)
    for building_type in order:
        lo, hi = COUNT_RANGES[building_type]
        count = rng.randint(lo, hi)
        size = TILE_FOOTPRINTS[building_type]
        level = catalog.sprite_level(building_type, town_hall_level)
        for _ in range(count):
            pos = _try_place(occupied, size, rng)
            if pos is None:
                break
            _mark(occupied, pos[0], pos[1], size)
            placements.append(BuildingPlacement(building_type, level=level, x=pos[0], y=pos[1]))

    return placements


def summarize_placement_levels(
    placements: Sequence[BuildingPlacement],
    catalog: SpriteLevelCatalog,
) -> dict[str, Any]:
    by_type: dict[str, list[int]] = defaultdict(list)
    th = next(p for p in placements if p.building_type == "town_hall")
    leftovers: list[str] = []
    for placement in placements:
        by_type[placement.building_type].append(placement.level)
        expected = catalog.sprite_level(placement.building_type, th.level)
        if placement.level != expected:
            leftovers.append(f"{placement.building_type}@{placement.level}")
    sprite_level = {name: vals[0] for name, vals in sorted(by_type.items())}
    return {
        "counts": {name: sorted(vals) for name, vals in sorted(by_type.items())},
        "sprite_level": sprite_level,
        "leftovers": leftovers,
    }


def generate_synthetic_dataset(
    count: int = DEFAULT_COUNT,
    output_dir: Path = DEFAULT_OUTPUT,
    seed: int = 42,
    *,
    skip_existing: bool = True,
    village_background: bool = True,
    catalog: SpriteLevelCatalog | None = None,
) -> dict[str, Any]:
    """Render ``count`` layouts to ``output_dir/th{15,16}/synthetic_XXXX.png`` + YOLO txt."""
    renderer = IsometricRenderer(use_placeholders=True, village_background=village_background)
    catalog = catalog or SpriteLevelCatalog.load()
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
        placements = generate_random_layout(
            layout_rng, town_hall_level=th_level, catalog=catalog
        )
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
        "level_policy": catalog.policy,
        "not_official_coc_cap": catalog.not_official_coc_cap,
    }
    logging.info(
        "Synthetic dataset: %d images (%d skipped existing), %d new boxes → %s",
        present,
        skipped_existing,
        boxes,
        output_dir,
    )
    return summary


def generate_th_strict_previews(
    output_dir: Path = DEFAULT_PREVIEW_DIR,
    seed: int = 42,
    *,
    catalog: SpriteLevelCatalog | None = None,
    village_background: bool = True,
) -> list[dict[str, Any]]:
    """Write 4 review images (2× TH15, 2× TH16) with one sprite tier per image."""
    catalog = catalog or SpriteLevelCatalog.load()
    renderer = IsometricRenderer(use_placeholders=True, village_background=village_background)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []

    for filename, th_level, seed_offset in PREVIEW_SPECS:
        layout_rng = random.Random(seed + seed_offset)
        placements = generate_random_layout(
            layout_rng, town_hall_level=th_level, catalog=catalog
        )
        out_png = output_dir / filename
        dr_cfg = DomainRandomizationConfig(seed=seed + seed_offset)
        result = renderer.render(
            placements,
            domain_randomization=dr_cfg,
            seed=seed + seed_offset,
        )
        result.image.save(out_png, format="PNG")
        level_info = summarize_placement_levels(placements, catalog)
        report = {
            "file": str(out_png),
            "town_hall_level": th_level,
            "sprite_level": level_info["sprite_level"],
            "sprite_levels": level_info["counts"],
            "leftovers": level_info["leftovers"],
            "level_policy": catalog.policy,
            "not_official_coc_cap": catalog.not_official_coc_cap,
            "heuristic": "TH16 = max sprite index, TH15 = max-1",
        }
        reports.append(report)
        logging.info(
            "%s TH=%s sprite_level=%s leftovers=%s",
            out_png.name,
            th_level,
            level_info["sprite_level"],
            level_info["leftovers"],
        )

    return reports


generate_th_capped_previews = generate_th_strict_previews


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate bulk synthetic YOLO labels from the isometric renderer."
    )
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Number of layouts (default: 200)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"Output dir (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="Overwrite existing PNG+txt pairs")
    parser.add_argument(
        "--flat-background",
        action="store_true",
        help="Legacy solid green fill instead of procedural village grass",
    )
    parser.add_argument(
        "--preview-th-strict",
        action="store_true",
        help="Write 4 review images (2×TH15, 2×TH16) with one sprite tier per image; does not bulk-generate",
    )
    parser.add_argument(
        "--preview-th-capped",
        action="store_true",
        help="Alias for --preview-th-strict",
    )
    parser.add_argument(
        "--preview-dir",
        type=Path,
        default=DEFAULT_PREVIEW_DIR,
        help=f"Preview output dir (default: {DEFAULT_PREVIEW_DIR})",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.preview_th_strict or args.preview_th_capped:
        reports = generate_th_strict_previews(
            output_dir=args.preview_dir,
            seed=args.seed,
            village_background=not args.flat_background,
        )
        print(json.dumps(reports, indent=2))
        print("\nSprite level per building (one file per type):")
        for report in reports:
            print(f"  {Path(report['file']).name}  TH={report['town_hall_level']}")
            for name, level in report["sprite_level"].items():
                print(f"    {name}: {level}")
        print("\nOpen previews:")
        for report in reports:
            print(f"  open {report['file']}")
        return 0

    if args.count < 1:
        parser.error("--count must be >= 1")

    summary = generate_synthetic_dataset(
        count=args.count,
        output_dir=args.output,
        seed=args.seed,
        skip_existing=not args.force,
        village_background=not args.flat_background,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
