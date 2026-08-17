"""Generate bulk synthetic YOLO-labeled village renders (perfect labels).

Layouts are random-but-plausible occupancy on the 44×44 editor grid.
Count ranges and tile footprints are collision/variety parameters — not
combat stats or wiki army tables.

Sprite levels use a **visual-tier proxy** (not an official CoC cap),
with user-corrected merge exceptions:

* Cannons max at TH15 (``cannon/level_21.webp`` purple). TH16–18 place
  ``ricochet_cannon`` (2→1 merge). YOLO class remains ``canon``.
* Wizard towers max at TH17 (``wizard_tower/level_17.webp``). TH18 places
  ``super_wizard_tower``. YOLO class remains ``wizztower``.
* Other defenses use ClashKing max / max-1 / max-2 / max-3 for
  TH18 / 17 / 16 / 15. One sprite level per building type per image.
  See ``renderer/sprites/max_level_by_th.yaml`` and
  ``building_type_map.yaml`` ``era_merges``.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

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
ERA_MAX_TOWN_HALL = 18
REQUESTED_TOWN_HALL_LEVELS = (15, 16, 17, 18)
TOWN_HALL_LEVELS = REQUESTED_TOWN_HALL_LEVELS

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

# Placement types used after era merges (not in the logical SYNTHETIC list).
MERGED_PLACEMENT_TYPES: frozenset[str] = frozenset(
    {"ricochet_cannon", "super_wizard_tower"}
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
    "ricochet_cannon": 3,
    "super_wizard_tower": 3,
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
    ("preview_th18era_th15.png", 15, 1015),
    ("preview_th18era_th16.png", 16, 1016),
    ("preview_th18era_th17.png", 17, 1017),
    ("preview_th18era_th18.png", 18, 1018),
)


def defense_offset_for_th(town_hall_level: int, era_max: int = ERA_MAX_TOWN_HALL) -> int:
    """TH18 → 0 (highest file), TH17 → 1, TH16 → 2, TH15 → 3."""
    return era_max - town_hall_level


def visual_tier_level(levels: Sequence[int], town_hall_level: int, era_max: int = ERA_MAX_TOWN_HALL) -> int:
    """Pick one ClashKing file for a building type at this TH (visual-tier proxy).

    Uses max / max-1 / max-2 / max-3 for TH18 / 17 / 16 / 15. Clamps at 1.
    If the target file is missing, uses the lowest available file at or below
    the target instead of wrapping to a higher-era sprite.
    """
    if not levels:
        raise RuntimeError("Empty sprite level list")
    ordered = sorted(levels)
    max_lv = ordered[-1]
    min_lv = ordered[0]
    desired = max_lv - defense_offset_for_th(town_hall_level, era_max)
    if desired < 1:
        desired = 1
    if desired in ordered:
        return desired
    below = [lv for lv in ordered if lv <= desired]
    return below[-1] if below else min_lv


@dataclass
class SpriteLevelCatalog:
    """Available sprite levels per synthetic building_type (disk, else yaml snapshot)."""

    levels_by_type: dict[str, list[int]]
    era_max_town_hall: int = ERA_MAX_TOWN_HALL
    requested_town_hall_levels: tuple[int, ...] = REQUESTED_TOWN_HALL_LEVELS
    policy: str = "visual-tier-proxy"
    not_official_coc_cap: bool = True
    source_path: Path | None = None
    type_map: Mapping[str, Any] = field(default_factory=dict)
    sprites_root: Path | None = None

    def levels_for(self, building_type: str) -> list[int]:
        levels = self.levels_by_type.get(building_type)
        if not levels:
            raise KeyError(f"No sprite levels catalogued for {building_type!r}")
        return list(levels)

    def sprite_level(self, building_type: str, town_hall_level: int) -> int:
        """Exactly one ClashKing file for this building on a TH15–18 image.

        Visual-tier proxy (not official CoC unlocks): town hall is exact;
        TH18 = max sprite index, TH17 = max-1, TH16 = max-2, TH15 = max-3.
        Clamp at 1; if fewer files than needed, use the lowest available.
        """
        if building_type == "town_hall":
            levels = self.levels_for("town_hall")
            if town_hall_level not in levels:
                raise RuntimeError(
                    f"Town hall sprite level_{town_hall_level} not in catalog {levels}"
                )
            return town_hall_level
        merge = self._merge_rule(building_type)
        era_max = self.era_max_town_hall
        if merge is not None and town_hall_level < int(merge["merged_from_th"]):
            era_max = int(merge["max_regular_th"])
        return visual_tier_level(
            self.levels_for(building_type),
            town_hall_level,
            era_max=era_max,
        )

    def _merge_rule(self, building_type: str) -> Mapping[str, Any] | None:
        merges = self.type_map.get("era_merges") or {}
        rule = merges.get(building_type)
        if not isinstance(rule, Mapping):
            return None
        return rule

    def resolve_for_th(self, building_type: str, town_hall_level: int) -> tuple[str, int] | None:
        """Logical type → (placement type, sprite level) for this TH.

        Merge rules (user): cannons become ricochet from TH16; wizard towers
        become super_wizard_tower at TH18. Returns None to skip the type.
        """
        if building_type == "town_hall":
            return building_type, self.sprite_level(building_type, town_hall_level)
        merge = self._merge_rule(building_type)
        if merge is None:
            return building_type, self.sprite_level(building_type, town_hall_level)
        merged_from = int(merge["merged_from_th"])
        merged_slug = str(merge.get("merged_slug") or "").strip()
        if town_hall_level >= merged_from:
            if not merged_slug:
                return None
            level = visual_tier_level(
                self.levels_for(merged_slug),
                town_hall_level,
                era_max=self.era_max_town_hall,
            )
            return merged_slug, level
        return building_type, self.sprite_level(building_type, town_hall_level)

    def count_range_for(self, building_type: str, town_hall_level: int) -> tuple[int, int]:
        merge = self._merge_rule(building_type)
        if merge is not None and town_hall_level >= int(merge["merged_from_th"]):
            raw = merge.get("count_range")
            if isinstance(raw, (list, tuple)) and len(raw) == 2:
                return int(raw[0]), int(raw[1])
        return COUNT_RANGES[building_type]

    def defense_level_for_th(self, building_type: str, town_hall_level: int) -> int:
        return self.sprite_level(building_type, town_hall_level)

    def available_town_hall_levels(self) -> list[int]:
        present = set(self.levels_for("town_hall"))
        return [th for th in self.requested_town_hall_levels if th in present]

    def skipped_town_hall_levels(self) -> list[int]:
        present = set(self.levels_for("town_hall"))
        return [th for th in self.requested_town_hall_levels if th not in present]

    def sprite_relpath(self, building_type: str, level: int) -> str:
        slug = _slug_for_building_type(building_type, self.type_map) or building_type
        return f"{slug}/level_{level}.webp"

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

        def _levels_for_slug(building_type: str, slug: str | None) -> list[int]:
            disk = list_sprite_levels(slug, root) if slug else []
            if disk:
                return disk
            mx = observed.get(slug or "") or observed.get(building_type)
            if mx is None:
                raise RuntimeError(
                    f"No ClashKing sprites and no yaml snapshot for {building_type!r} (slug={slug})"
                )
            return list(range(1, mx + 1))

        for building_type in SYNTHETIC_BUILDING_TYPES:
            slug = _slug_for_building_type(building_type, type_map)
            levels_by_type[building_type] = _levels_for_slug(building_type, slug)
        merges = type_map.get("era_merges") or {}
        for rule in merges.values():
            if not isinstance(rule, dict):
                continue
            merged_slug = str(rule.get("merged_slug") or "").strip()
            if merged_slug and merged_slug not in levels_by_type:
                slug = _slug_for_building_type(merged_slug, type_map) or merged_slug
                levels_by_type[merged_slug] = _levels_for_slug(merged_slug, slug)
        requested = tuple(
            int(x) for x in (policy.get("town_hall_levels_generated") or REQUESTED_TOWN_HALL_LEVELS)
        )
        return cls(
            levels_by_type=levels_by_type,
            era_max_town_hall=int(policy.get("era_max_town_hall", ERA_MAX_TOWN_HALL)),
            requested_town_hall_levels=requested or REQUESTED_TOWN_HALL_LEVELS,
            policy=str(policy.get("policy", "visual-tier-proxy")),
            not_official_coc_cap=bool(policy.get("not_official_coc_cap", True)),
            source_path=policy_path,
            type_map=type_map,
            sprites_root=root,
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

    Town hall sprite is exactly ``town_hall_level``. Other types use one
    visual-tier file, with cannon/wizard era merges from ``era_merges``.
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
        resolved = catalog.resolve_for_th(building_type, town_hall_level)
        if resolved is None:
            continue
        place_type, level = resolved
        lo, hi = catalog.count_range_for(building_type, town_hall_level)
        count = rng.randint(lo, hi)
        size = TILE_FOOTPRINTS.get(place_type) or TILE_FOOTPRINTS[building_type]
        for _ in range(count):
            pos = _try_place(occupied, size, rng)
            if pos is None:
                break
            _mark(occupied, pos[0], pos[1], size)
            placements.append(BuildingPlacement(place_type, level=level, x=pos[0], y=pos[1]))

    return placements


def summarize_placement_levels(
    placements: Sequence[BuildingPlacement],
    catalog: SpriteLevelCatalog,
) -> dict[str, Any]:
    by_type: dict[str, dict[str, Any]] = {}
    mixed: list[str] = []
    for placement in placements:
        entry = by_type.get(placement.building_type)
        if entry is None:
            by_type[placement.building_type] = {
                "level": placement.level,
                "sprite": catalog.sprite_relpath(placement.building_type, placement.level),
                "count": 1,
            }
            continue
        entry["count"] += 1
        if placement.level != entry["level"]:
            mixed.append(f"{placement.building_type}@{placement.level}")
    return {
        "by_type": dict(sorted(by_type.items())),
        "mixed_levels": mixed,
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
    """Render ``count`` layouts to ``output_dir/th{15,16,17,18}/synthetic_XXXX.png`` + YOLO txt."""
    renderer = IsometricRenderer(use_placeholders=True, village_background=village_background)
    catalog = catalog or SpriteLevelCatalog.load()
    th_levels = catalog.available_town_hall_levels()
    skipped_th = catalog.skipped_town_hall_levels()
    if not th_levels:
        raise RuntimeError(
            f"No town_hall sprites for requested THs {list(catalog.requested_town_hall_levels)}"
        )
    if skipped_th:
        logging.warning(
            "Skipping TH%s — missing town_hall/level_{N}.webp",
            "/".join(str(th) for th in skipped_th),
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    present = 0
    skipped_existing = 0
    boxes = 0
    warnings: list[str] = []

    for idx in range(count):
        th_level = th_levels[idx % len(th_levels)]
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
        "town_hall_levels": th_levels,
        "skipped_town_hall_levels": skipped_th,
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


def generate_th18era_previews(
    output_dir: Path = DEFAULT_PREVIEW_DIR,
    seed: int = 42,
    *,
    catalog: SpriteLevelCatalog | None = None,
    village_background: bool = True,
) -> list[dict[str, Any]]:
    """Write one review image per TH in {15,16,17,18}; skip missing hall sprites."""
    catalog = catalog or SpriteLevelCatalog.load()
    renderer = IsometricRenderer(use_placeholders=True, village_background=village_background)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    skipped_th = catalog.skipped_town_hall_levels()
    if skipped_th:
        logging.warning(
            "Skipping TH%s — missing town_hall/level_{N}.webp",
            "/".join(str(th) for th in skipped_th),
        )

    for filename, th_level, seed_offset in PREVIEW_SPECS:
        if th_level not in catalog.levels_for("town_hall"):
            reports.append(
                {
                    "file": None,
                    "town_hall_level": th_level,
                    "skipped": True,
                    "reason": f"missing town_hall/level_{th_level}.webp",
                    "level_policy": catalog.policy,
                    "not_official_coc_cap": catalog.not_official_coc_cap,
                }
            )
            continue
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
            "skipped": False,
            "sprite_levels": level_info["by_type"],
            "mixed_levels": level_info["mixed_levels"],
            "level_policy": catalog.policy,
            "not_official_coc_cap": catalog.not_official_coc_cap,
        }
        reports.append(report)
        logging.info(
            "%s TH=%s sprites=%s",
            out_png.name,
            th_level,
            {
                name: f"{info['sprite']} x{info['count']}"
                for name, info in level_info["by_type"].items()
            },
        )

    return reports


generate_th_capped_previews = generate_th18era_previews
generate_th_strict_previews = generate_th18era_previews


def _print_preview_reports(reports: Sequence[Mapping[str, Any]]) -> None:
    print(json.dumps(reports, indent=2))
    print("\nSprite levels (visual-tier proxy + user merge exceptions):")
    for report in reports:
        th = report["town_hall_level"]
        if report.get("skipped"):
            print(f"  TH{th}: SKIPPED — {report.get('reason')}")
            continue
        print(f"  TH{th}  {report['file']}")
        for name, info in (report.get("sprite_levels") or {}).items():
            print(
                f"    {name:12} level={info['level']:<3} {info['sprite']}  n={info['count']}"
            )
    print("\nCannon / ricochet and wizard / merge sprites:")
    highlight = (
        "canon",
        "ricochet_cannon",
        "wizztower",
        "super_wizard_tower",
    )
    for report in reports:
        th = report["town_hall_level"]
        if report.get("skipped"):
            print(f"  TH{th}: SKIPPED")
            continue
        levels = report.get("sprite_levels") or {}
        bits = []
        for name in highlight:
            info = levels.get(name)
            if info:
                bits.append(f"{name}={info['sprite']}")
        print(f"  TH{th}: " + (", ".join(bits) if bits else "(none)"))
    written = [r["file"] for r in reports if r.get("file")]
    print("\nOpen previews:")
    for path in written:
        print(f"  open {path}")


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
        "--preview-th18era",
        "--preview-th-capped",
        "--preview-th-strict",
        dest="preview_th18era",
        action="store_true",
        help="Write 4 review images (TH15–18) and print sprite paths; does not bulk-generate",
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

    if args.preview_th18era:
        reports = generate_th18era_previews(
            output_dir=args.preview_dir,
            seed=args.seed,
            village_background=not args.flat_background,
        )
        _print_preview_reports(reports)
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
