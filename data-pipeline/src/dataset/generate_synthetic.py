"""Generate bulk synthetic YOLO-labeled village renders (perfect labels).

Layouts are random-but-plausible occupancy on the 44×44 editor grid.
Count ranges and tile footprints are collision/variety parameters — not
combat stats. **Which buildings exist at a TH** comes from
``renderer/sprites/th_unlocks.yaml`` (internet-sourced; see
``knowledge-base/SOURCES.md``). Types without a sourced row are omitted.

Sprite levels use a **visual-tier proxy** (not an official CoC cap),
with sourced merge windows:

* Cannons max at TH15 (``cannon/level_21.webp`` purple). TH16–18 place
  ``ricochet_cannon`` (wiki merge TH16). YOLO class remains ``canon``.
* Wizard towers max at TH17 (``wizard_tower/level_17.webp``). TH18 places
  ``super_wizard_tower`` (wiki merge TH18). YOLO class remains ``wizztower``.
* Eagle artillery TH11–16; removed at TH17 (merged into Inferno Artillery).
* Firespitter TH17+; Multi-Gear Tower TH17+; Revenge Tower TH18.
* Spell towers: wiki Number Available is 2 at TH15–18. **Generator skips
  TH15** (user 2026-08-17). Place 2 on TH16–18. Not the old “TH15+ except 16”.
* Monolith TH15+; Hidden Tesla TH7+; weaponized Builder Hut TH14+.
* Walls (``wall/``): visual-tier from maxed TH18. 1×1 tiles, unlabeled.
* Other defenses use ClashKing max / max-1 / max-2 / max-3 for
  TH18 / 17 / 16 / 15. One sprite level per building type per image.
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
from renderer.photo_background import scenery_path_by_name
from renderer.isometric_renderer import (
    BUILDING_TYPE_MAP_PATH,
    CLASHKING_HOME_VILLAGE,
    GRID_SIZE,
    TILE_FOOTPRINTS,
    TILE_WIDTH,
    IsometricRenderer,
    list_sprite_levels,
    occupancy_tiles,
    occupied_cells,
    placement_in_playable_grid,
    sprite_stays_on_playable,
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
TH_UNLOCKS_PATH = (
    PIPELINE_ROOT / "src" / "renderer" / "sprites" / "th_unlocks.yaml"
)
DEFAULT_COUNT = 200
ERA_MAX_TOWN_HALL = 18
REQUESTED_TOWN_HALL_LEVELS = (15, 16, 17, 18)
TOWN_HALL_LEVELS = REQUESTED_TOWN_HALL_LEVELS

# Active classes from building_type_map aliases + town_hall (no hero pads).
# Extra defenses added after the TH15–18 wiki/ClashKing gap audit (SOURCES.md).
SYNTHETIC_BUILDING_TYPES: tuple[str, ...] = (
    "canon",
    "archertower",
    "mortar",
    "inferno",
    "eagle",
    "xbow",
    "scattershot",
    "wizztower",
    "ad",
    "bombtower",
    "firespitter",
    "spelltower",
    "airsweeper",
    "clancastle",
    "town_hall",
    "monolith",
    "tesla",
    "builderhut",
    "multi-gear_tower",
    "revenge_tower",
)

# Placement types used after era merges (not in the logical SYNTHETIC list).
MERGED_PLACEMENT_TYPES: frozenset[str] = frozenset(
    {"ricochet_cannon", "super_wizard_tower", "multi-archer_tower"}
)

# ClashKing spell_tower/ filenames — four designs, not named spells.
SPELL_TOWER_VARIANT_FILES: tuple[str, ...] = (
    "spell_tower/level_1.webp",
    "spell_tower/level_2.webp",
    "spell_tower/level_3.webp",
    "spell_tower/level_4.webp",
)

# How many of each type to try placing. Caps come from wiki counts in
# th_unlocks.yaml when present; these are occupancy fallbacks only.
COUNT_RANGES: dict[str, tuple[int, int]] = {
    "town_hall": (1, 1),
    "clancastle": (1, 1),
    "eagle": (1, 1),
    "scattershot": (1, 2),
    "inferno": (1, 3),
    "xbow": (2, 4),
    "canon": (2, 5),
    "mortar": (2, 4),
    "wizztower": (2, 5),
    "ad": (2, 4),
    "bombtower": (1, 2),
    "archertower": (2, 5),
    "firespitter": (1, 2),
    "spelltower": (2, 2),
    "airsweeper": (1, 2),
    "monolith": (1, 1),
    "tesla": (1, 3),
    "builderhut": (1, 3),
    "multi-gear_tower": (1, 1),
    "revenge_tower": (1, 1),
}

# Place these before the shuffled remainder so TH-window uniques still fit.
PRIORITY_TYPES: tuple[str, ...] = (
    "eagle",
    "clancastle",
    "monolith",
    "firespitter",
    "spelltower",
    "multi-gear_tower",
    "revenge_tower",
    "wizztower",
    "canon",
    "archertower",
    "bombtower",
    "tesla",
    "builderhut",
)

PREVIEW_SPECS: tuple[tuple[str, int, int], ...] = (
    ("preview_th18era_th15.png", 15, 1015),
    ("preview_th18era_th16.png", 16, 1016),
    ("preview_th18era_th17.png", 17, 1017),
    ("preview_th18era_th18.png", 18, 1018),
)

# Distinct home sceneries + clan_war for the photo-composite review set.
SCENERY_PREVIEW_SPECS: tuple[tuple[str, int, int, str], ...] = (
    ("preview_bg_th15.png", 15, 3015, "classic_grass.png"),
    ("preview_bg_th16.png", 16, 3016, "ruins_temple.png"),
    ("preview_bg_th17.png", 17, 3017, "primal.png"),
    ("preview_bg_war.png", 18, 3019, "clan_war.png"),
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
    unlocks: Mapping[str, Any] = field(default_factory=dict)

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
        avail = self._availability(building_type)
        if avail is not None and avail.get("max_th") is not None:
            era_max = min(era_max, int(avail["max_th"]))
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

    def _availability(self, building_type: str) -> Mapping[str, Any] | None:
        """Prefer sourced ``th_unlocks.yaml``; fall back to type_map heuristics."""
        buildings = self.unlocks.get("buildings") or {}
        rule = buildings.get(building_type)
        if isinstance(rule, Mapping):
            return rule
        avail = self.type_map.get("era_availability") or {}
        fallback = avail.get(building_type)
        if not isinstance(fallback, Mapping):
            return None
        return fallback

    def available_at_th(self, building_type: str, town_hall_level: int) -> bool:
        """False when sourced unlocks (or era_availability) exclude this TH."""
        merge = self._merge_rule(building_type)
        if merge is not None and town_hall_level >= int(merge["merged_from_th"]):
            merged_slug = str(merge.get("merged_slug") or "").strip()
            merged_rule = (self.unlocks.get("buildings") or {}).get(merged_slug)
            if isinstance(merged_rule, Mapping):
                return self._rule_allows(merged_rule, town_hall_level)
            return True
        sourced = self.unlocks.get("buildings") or {}
        if sourced and building_type not in sourced and building_type != "town_hall":
            return False
        rule = self._availability(building_type)
        if rule is None:
            return True
        return self._rule_allows(rule, town_hall_level)

    @staticmethod
    def _rule_allows(rule: Mapping[str, Any], town_hall_level: int) -> bool:
        min_th = rule.get("min_th")
        max_th = rule.get("max_th")
        removed_at = rule.get("removed_at")
        skip_th: set[int] = set()
        for key in ("skip_th", "exclude_th", "generator_skip_th"):
            skip_th.update(int(x) for x in (rule.get(key) or []))
        if town_hall_level in skip_th:
            return False
        if removed_at is not None and town_hall_level >= int(removed_at):
            return False
        if min_th is not None and town_hall_level < int(min_th):
            return False
        if max_th is not None and town_hall_level > int(max_th):
            return False
        return True

    def resolve_for_th(self, building_type: str, town_hall_level: int) -> tuple[str, int] | None:
        """Logical type → (placement type, sprite level) for this TH.

        Merge rules (user): cannons become ricochet from TH16; archer towers
        become multi-archer_tower from TH16; wizard towers become
        super_wizard_tower at TH18. Returns None to skip the type
        (including era_availability windows: eagle ≤ TH16, firespitter ≥ TH17).
        """
        if building_type == "town_hall":
            return building_type, self.sprite_level(building_type, town_hall_level)
        if not self.available_at_th(building_type, town_hall_level):
            return None
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

    def uses_random_variants(self, building_type: str) -> bool:
        variants = self.type_map.get("random_sprite_variants") or {}
        return building_type in variants

    def places_all_variants(self, building_type: str) -> bool:
        variants = self.type_map.get("random_sprite_variants") or {}
        spec = variants.get(building_type)
        if not isinstance(spec, Mapping):
            return False
        return bool(spec.get("place_all") or spec.get("place_all_variants"))

    def variant_levels_for_layout(self, building_type: str, cycle: int) -> list[int] | None:
        """Rotated ClashKing variant levels when place_all is set.

        Cycle offset makes leftover variants even across a batch if occupancy
        cannot fit every design on one layout.
        """
        if not self.places_all_variants(building_type):
            return None
        levels = self.levels_for(building_type)
        if not levels:
            return None
        offset = cycle % len(levels)
        return levels[offset:] + levels[:offset]

    def count_range_for(self, building_type: str, town_hall_level: int) -> tuple[int, int]:
        merge = self._merge_rule(building_type)
        if merge is not None and town_hall_level >= int(merge["merged_from_th"]):
            raw = merge.get("count_range")
            if isinstance(raw, (list, tuple)) and len(raw) == 2:
                return int(raw[0]), int(raw[1])
        avail = self._availability(building_type)
        if avail is not None:
            raw = avail.get("count_range")
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

    def sprite_pixel_size(self, building_type: str, level: int) -> tuple[int, int] | None:
        """ClashKing image size, or None when sprites are not on disk."""
        root = self.sprites_root
        if root is None:
            return None
        slug = _slug_for_building_type(building_type, self.type_map) or building_type
        path = root / slug / f"level_{level}.webp"
        if not path.is_file():
            return None
        from PIL import Image

        with Image.open(path) as image:
            return image.size

    def occupancy_size(self, building_type: str, level: int | None = None) -> int:
        """Tiles reserved for collision: CoC footprint, sprite AABB, plus pad."""
        sprite_w: int | None = None
        sprite_h: int | None = None
        if level is not None:
            dims = self.sprite_pixel_size(building_type, level)
            if dims is not None:
                sprite_w, sprite_h = dims
        return occupancy_tiles(building_type, sprite_w, sprite_h)

    def visual_sprite_size(self, building_type: str, level: int) -> tuple[int, int]:
        dims = self.sprite_pixel_size(building_type, level)
        if dims is not None:
            return dims
        from renderer.isometric_renderer import SPRITE_NORTH_PAD_PX, TILE_HEIGHT

        tiles = TILE_FOOTPRINTS.get(building_type, 3)
        return tiles * TILE_WIDTH, tiles * TILE_HEIGHT + SPRITE_NORTH_PAD_PX

    @classmethod
    def load(
        cls,
        *,
        sprites_root: Path | None = None,
        policy_path: Path = LEVEL_POLICY_PATH,
        type_map_path: Path = BUILDING_TYPE_MAP_PATH,
        unlocks_path: Path = TH_UNLOCKS_PATH,
    ) -> SpriteLevelCatalog:
        policy = _load_level_policy(policy_path)
        type_map = _load_building_type_map(type_map_path)
        unlocks = _load_th_unlocks(unlocks_path)
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
        if "wall" not in levels_by_type:
            wall_slug = _slug_for_building_type("wall", type_map) or "wall"
            levels_by_type["wall"] = _levels_for_slug("wall", wall_slug)
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
            unlocks=unlocks,
        )


def _load_level_policy(path: Path = LEVEL_POLICY_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Level policy must be a mapping: {path}")
    return data


def _load_th_unlocks(path: Path = TH_UNLOCKS_PATH) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"TH unlocks must be a mapping: {path}")
    return data


def _fits(
    occupied: set[tuple[int, int]],
    x: int,
    y: int,
    size: int,
    *,
    sprite_w: int,
    sprite_h: int,
) -> bool:
    if not placement_in_playable_grid(x, y, size):
        return False
    if occupied_cells(x, y, size) & occupied:
        return False
    # One empty tile between occupancy squares so iso sprites do not sit on
    # each other's feet. Walls may still fill that gap later.
    dilated = occupied_cells(x - 1, y - 1, size + 2)
    if dilated & occupied:
        return False
    return sprite_stays_on_playable(x, y, size, sprite_w=sprite_w, sprite_h=sprite_h)


def _mark(occupied: set[tuple[int, int]], x: int, y: int, size: int) -> None:
    occupied.update(occupied_cells(x, y, size))


def _try_place(
    occupied: set[tuple[int, int]],
    size: int,
    rng: random.Random,
    *,
    sprite_w: int,
    sprite_h: int,
    prefer_center: bool = False,
    max_attempts: int = 400,
) -> tuple[int, int] | None:
    limit = GRID_SIZE - size
    if limit < 0:
        return None

    def _ok(x: int, y: int) -> bool:
        return _fits(
            occupied,
            x,
            y,
            size,
            sprite_w=sprite_w,
            sprite_h=sprite_h,
        )

    if prefer_center:
        cx = GRID_SIZE // 2 - size // 2
        for radius in range(0, 18):
            candidates: list[tuple[int, int]] = []
            lo = max(0, cx - radius)
            hi = min(limit, cx + radius)
            for x in range(lo, hi + 1):
                for y in range(lo, hi + 1):
                    if _ok(x, y):
                        candidates.append((x, y))
            if candidates:
                return rng.choice(candidates)
        return None

    for _ in range(max_attempts):
        x = rng.randint(0, limit)
        y = rng.randint(0, limit)
        if _ok(x, y):
            return x, y
    for x in range(0, limit + 1):
        for y in range(0, limit + 1):
            if _ok(x, y):
                return x, y
    return None


MIN_WALL_SEGMENTS = 40
MAX_WALL_SEGMENTS = 110


def _wall_cell_ok(x: int, y: int, occupied: set[tuple[int, int]]) -> bool:
    """1×1 wall on the playable interior, not on a building footprint."""
    if (x, y) in occupied:
        return False
    if x < 1 or y < 1 or x >= GRID_SIZE - 1 or y >= GRID_SIZE - 1:
        return False
    return placement_in_playable_grid(x, y, 1)


def _try_add_wall(
    x: int,
    y: int,
    occupied: set[tuple[int, int]],
    placements: list[BuildingPlacement],
    wall_level: int,
    *,
    cap: int = MAX_WALL_SEGMENTS,
) -> bool:
    if len(placements) >= cap:
        return False
    if not _wall_cell_ok(x, y, occupied):
        return False
    occupied.add((x, y))
    placements.append(BuildingPlacement("wall", level=wall_level, x=x, y=y))
    return True


def _place_rect_ring(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    occupied: set[tuple[int, int]],
    placements: list[BuildingPlacement],
    wall_level: int,
    *,
    gate: tuple[str, int] | None = None,
) -> None:
    """Draw a 1-tile rectangle; ``gate`` is ('x'|'y', coord) opening of 2 tiles."""
    if x1 <= x0 or y1 <= y0:
        return

    def _gated(x: int, y: int) -> bool:
        if gate is None:
            return False
        axis, coord = gate
        if axis == "x" and x == coord and y0 + 1 < y < y1 - 1:
            return abs(y - ((y0 + y1) // 2)) <= 1
        if axis == "y" and y == coord and x0 + 1 < x < x1 - 1:
            return abs(x - ((x0 + x1) // 2)) <= 1
        return False

    for x in range(x0, x1 + 1):
        if not _gated(x, y0):
            _try_add_wall(x, y0, occupied, placements, wall_level)
        if not _gated(x, y1):
            _try_add_wall(x, y1, occupied, placements, wall_level)
    for y in range(y0 + 1, y1):
        if not _gated(x0, y):
            _try_add_wall(x0, y, occupied, placements, wall_level)
        if not _gated(x1, y):
            _try_add_wall(x1, y, occupied, placements, wall_level)


def _place_walls(
    occupied: set[tuple[int, int]],
    buildings: Sequence[BuildingPlacement],
    rng: random.Random,
    *,
    catalog: SpriteLevelCatalog,
    town_hall_level: int,
) -> list[BuildingPlacement]:
    """Compartment-ish walls around/between buildings (1×1, no building overlap)."""
    try:
        wall_level = catalog.sprite_level("wall", town_hall_level)
    except KeyError:
        return []

    walls: list[BuildingPlacement] = []
    if not occupied:
        return walls

    xs = [c[0] for c in occupied]
    ys = [c[1] for c in occupied]
    margin = 2
    x0 = max(1, min(xs) - margin)
    y0 = max(1, min(ys) - margin)
    x1 = min(GRID_SIZE - 2, max(xs) + margin)
    y1 = min(GRID_SIZE - 2, max(ys) + margin)

    gate_axis = rng.choice(("x", "y"))
    gate_coord = x0 if gate_axis == "x" else y0
    _place_rect_ring(
        x0, y0, x1, y1, occupied, walls, wall_level, gate=(gate_axis, gate_coord)
    )

    if x1 - x0 >= 10:
        splits_x = [(x0 + x1) // 2]
        if x1 - x0 >= 18:
            splits_x.append(x0 + (x1 - x0) // 3)
        for mx in splits_x:
            gap = rng.randint(y0 + 3, max(y0 + 4, y1 - 3))
            for y in range(y0 + 1, y1):
                if abs(y - gap) <= 1:
                    continue
                _try_add_wall(mx, y, occupied, walls, wall_level)
    if y1 - y0 >= 10:
        splits_y = [(y0 + y1) // 2]
        if y1 - y0 >= 18:
            splits_y.append(y0 + (y1 - y0) // 3)
        for my in splits_y:
            gap = rng.randint(x0 + 3, max(x0 + 4, x1 - 3))
            for x in range(x0 + 1, x1):
                if abs(x - gap) <= 1:
                    continue
                _try_add_wall(x, my, occupied, walls, wall_level)

    # One inner ring around the town hall only (not every defense).
    for building in buildings:
        if building.building_type != "town_hall":
            continue
        size = catalog.occupancy_size(building.building_type, building.level)
        bx0, by0 = building.x - 1, building.y - 1
        bx1, by1 = building.x + size, building.y + size
        side = rng.choice(("x", "y"))
        coord = bx0 if side == "x" else by0
        _place_rect_ring(
            bx0, by0, bx1, by1, occupied, walls, wall_level, gate=(side, coord)
        )

    if len(walls) < MIN_WALL_SEGMENTS:
        candidates = [
            (x, y)
            for x in range(x0, x1 + 1)
            for y in range(y0, y1 + 1)
            if _wall_cell_ok(x, y, occupied)
        ]
        rng.shuffle(candidates)
        for x, y in candidates:
            if len(walls) >= MIN_WALL_SEGMENTS:
                break
            _try_add_wall(x, y, occupied, walls, wall_level)

    return walls


def generate_random_layout(
    rng: random.Random,
    town_hall_level: int,
    *,
    catalog: SpriteLevelCatalog | None = None,
    variant_cycle: int = 0,
) -> list[BuildingPlacement]:
    """Place a TH plus a random mix of active defenses without grid overlap.

    Town hall sprite is exactly ``town_hall_level``. Other types use one
    visual-tier file, with cannon/archer/wizard era merges from ``era_merges``.
    Availability is ``th_unlocks.yaml``: eagle ≤ TH16, firespitter ≥ TH17,
    spell towers on TH16–18 (not TH15), monolith/tesla/builder hut as sourced.
    Walls are 1×1 compartment rings (rendered, not YOLO-labeled). Occupied
    tiles are never reused; screen-space footprint AABBs must not overlap.
    If a building cannot fit after retries, it is skipped.
    """
    catalog = catalog or SpriteLevelCatalog.load()

    occupied: set[tuple[int, int]] = set()
    placements: list[BuildingPlacement] = []

    th_level = catalog.sprite_level("town_hall", town_hall_level)
    th_size = catalog.occupancy_size("town_hall", th_level)
    th_w, th_h = catalog.visual_sprite_size("town_hall", th_level)
    pos = _try_place(
        occupied,
        th_size,
        rng,
        sprite_w=th_w,
        sprite_h=th_h,
        prefer_center=True,
    )
    if pos is None:
        raise RuntimeError("Could not place town hall on empty playable grid")
    _mark(occupied, pos[0], pos[1], th_size)
    placements.append(BuildingPlacement("town_hall", level=th_level, x=pos[0], y=pos[1]))

    rest = [
        name
        for name in SYNTHETIC_BUILDING_TYPES
        if name != "town_hall" and name not in PRIORITY_TYPES
    ]
    rng.shuffle(rest)
    order = [name for name in PRIORITY_TYPES if name in SYNTHETIC_BUILDING_TYPES] + rest
    for building_type in order:
        try:
            resolved = catalog.resolve_for_th(building_type, town_hall_level)
        except KeyError:
            continue
        if resolved is None:
            continue
        place_type, level = resolved
        variant_order = catalog.variant_levels_for_layout(building_type, variant_cycle)
        if variant_order is not None:
            levels_to_place = variant_order
            skip_on_miss = False
        else:
            lo, hi = catalog.count_range_for(building_type, town_hall_level)
            count = rng.randint(lo, hi)
            if catalog.uses_random_variants(building_type):
                levels_to_place = [
                    rng.choice(catalog.levels_for(building_type)) for _ in range(count)
                ]
            else:
                levels_to_place = [level] * count
            skip_on_miss = True
        for place_level in levels_to_place:
            size = catalog.occupancy_size(place_type, place_level)
            sprite_w, sprite_h = catalog.visual_sprite_size(place_type, place_level)
            pos = _try_place(
                occupied,
                size,
                rng,
                sprite_w=sprite_w,
                sprite_h=sprite_h,
            )
            if pos is None:
                if skip_on_miss:
                    break
                continue
            _mark(occupied, pos[0], pos[1], size)
            placements.append(
                BuildingPlacement(place_type, level=place_level, x=pos[0], y=pos[1])
            )

    placements.extend(
        _place_walls(
            occupied,
            placements,
            rng,
            catalog=catalog,
            town_hall_level=town_hall_level,
        )
    )
    return placements


def summarize_placement_levels(
    placements: Sequence[BuildingPlacement],
    catalog: SpriteLevelCatalog,
) -> dict[str, Any]:
    by_type: dict[str, dict[str, Any]] = {}
    mixed: list[str] = []
    for placement in placements:
        sprite = catalog.sprite_relpath(placement.building_type, placement.level)
        entry = by_type.get(placement.building_type)
        if entry is None:
            by_type[placement.building_type] = {
                "level": placement.level,
                "sprite": sprite,
                "count": 1,
                "levels": [placement.level],
                "sprites": [sprite],
            }
            continue
        entry["count"] += 1
        entry["levels"].append(placement.level)
        entry["sprites"].append(sprite)
        if placement.level != entry["level"] and not catalog.uses_random_variants(
            placement.building_type
        ):
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
    use_photo_backgrounds: bool = True,
    catalog: SpriteLevelCatalog | None = None,
) -> dict[str, Any]:
    """Render ``count`` layouts to ``output_dir/th{15,16,17,18}/synthetic_XXXX.png`` + YOLO txt."""
    renderer = IsometricRenderer(
        use_placeholders=True,
        village_background=village_background,
        use_photo_backgrounds=use_photo_backgrounds,
    )
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
            layout_rng,
            town_hall_level=th_level,
            catalog=catalog,
            variant_cycle=idx,
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
    use_photo_backgrounds: bool = True,
) -> list[dict[str, Any]]:
    """Write one review image per TH in {15,16,17,18}; skip missing hall sprites."""
    catalog = catalog or SpriteLevelCatalog.load()
    renderer = IsometricRenderer(
        use_placeholders=True,
        village_background=village_background,
        use_photo_backgrounds=use_photo_backgrounds,
    )
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
            layout_rng,
            town_hall_level=th_level,
            catalog=catalog,
            variant_cycle=th_level,
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
            "background": result.background_path.name if result.background_path else None,
        }
        reports.append(report)
        logging.info(
            "%s TH=%s sprites=%s",
            out_png.name,
            th_level,
            {
                name: (
                    f"{'+'.join(dict.fromkeys(info.get('sprites') or [info['sprite']]))}"
                    f" x{info['count']}"
                )
                for name, info in level_info["by_type"].items()
            },
        )

    return reports


def generate_scenery_previews(
    output_dir: Path = DEFAULT_PREVIEW_DIR,
    seed: int = 42,
    *,
    catalog: SpriteLevelCatalog | None = None,
) -> list[dict[str, Any]]:
    """Write four composites on distinct user sceneries (war uses clan_war.png)."""
    catalog = catalog or SpriteLevelCatalog.load()
    renderer = IsometricRenderer(
        use_placeholders=True,
        village_background=True,
        use_photo_backgrounds=True,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []

    for filename, th_level, seed_offset, scenery_name in SCENERY_PREVIEW_SPECS:
        bg_path = scenery_path_by_name(scenery_name)
        if bg_path is None:
            reports.append(
                {
                    "file": None,
                    "town_hall_level": th_level,
                    "skipped": True,
                    "reason": f"missing scenery {scenery_name}",
                    "background": scenery_name,
                }
            )
            continue
        if th_level not in catalog.levels_for("town_hall"):
            reports.append(
                {
                    "file": None,
                    "town_hall_level": th_level,
                    "skipped": True,
                    "reason": f"missing town_hall/level_{th_level}.webp",
                    "background": scenery_name,
                }
            )
            continue
        layout_rng = random.Random(seed + seed_offset)
        placements = generate_random_layout(
            layout_rng,
            town_hall_level=th_level,
            catalog=catalog,
            variant_cycle=th_level,
        )
        out_png = output_dir / filename
        dr_cfg = DomainRandomizationConfig(
            seed=seed + seed_offset,
            brightness_jitter=0.04,
            contrast_jitter=0.04,
            overlay_opacity=0.04,
            position_jitter_px=0,
        )
        result = renderer.render(
            placements,
            domain_randomization=dr_cfg,
            seed=seed + seed_offset,
            background_path=bg_path,
        )
        result.image.save(out_png, format="PNG")
        level_info = summarize_placement_levels(placements, catalog)
        reports.append(
            {
                "file": str(out_png),
                "town_hall_level": th_level,
                "skipped": False,
                "background": bg_path.name,
                "sprite_levels": level_info["by_type"],
                "mixed_levels": level_info["mixed_levels"],
                "level_policy": catalog.policy,
                "not_official_coc_cap": catalog.not_official_coc_cap,
            }
        )
        logging.info("%s TH=%s background=%s", out_png.name, th_level, bg_path.name)

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
        print(f"  TH{th}  {report['file']}" + (
            f"  bg={report['background']}" if report.get("background") else ""
        ))
        for name, info in (report.get("sprite_levels") or {}).items():
            sprites = list(dict.fromkeys(info.get("sprites") or [info["sprite"]]))
            if len(sprites) > 1:
                print(f"    {name:12} n={info['count']:<3} " + ", ".join(sprites))
            else:
                print(
                    f"    {name:12} level={info['level']:<3} {info['sprite']}  n={info['count']}"
                )
    print("\nCannon / archer / wizard merge sprites:")
    highlight = (
        "canon",
        "ricochet_cannon",
        "archertower",
        "multi-archer_tower",
        "wizztower",
        "super_wizard_tower",
        "eagle",
        "bombtower",
        "firespitter",
        "spelltower",
        "monolith",
        "tesla",
        "builderhut",
        "multi-gear_tower",
        "revenge_tower",
        "wall",
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
                sprites = list(dict.fromkeys(info.get("sprites") or [info["sprite"]]))
                bits.append(
                    f"{name}={' + '.join(sprites) if len(sprites) > 1 else info['sprite']}"
                )
        print(f"  TH{th}: " + (", ".join(bits) if bits else "(none)"))
    print("\nTown hall / eagle / spells / walls:")
    for report in reports:
        th = report["town_hall_level"]
        if report.get("skipped"):
            print(f"  TH{th}: SKIPPED")
            continue
        levels = report.get("sprite_levels") or {}
        th_info = levels.get("town_hall")
        eagle_info = levels.get("eagle")
        spell_info = levels.get("spelltower")
        wall_info = levels.get("wall")
        th_sprite = th_info["sprite"] if th_info else "(missing hall)"
        eagle_sprite = (
            eagle_info["sprite"]
            if eagle_info
            else ("(none — eagle skipped this TH)" if th >= 17 else "(none)")
        )
        if spell_info:
            spell_sprites = list(dict.fromkeys(spell_info.get("sprites") or [spell_info["sprite"]]))
            spell_txt = f"n={spell_info['count']} " + ", ".join(spell_sprites)
        elif th == 15:
            spell_txt = "(none — spell towers skipped at TH15)"
        else:
            spell_txt = "(none)"
        wall_txt = (
            f"{wall_info['sprite']} n={wall_info['count']}"
            if wall_info
            else "(none)"
        )
        print(f"  TH{th} hall={th_sprite}")
        print(f"       eagle={eagle_sprite}")
        print(f"       spells={spell_txt}")
        print(f"       walls={wall_txt}")
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
        help="Procedural village grass instead of user scenery photos (also used if no PNGs exist)",
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
        "--preview-scenery",
        action="store_true",
        help="Write 4 composites on distinct empty-village photos (war uses clan_war.png)",
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

    if args.preview_scenery:
        reports = generate_scenery_previews(output_dir=args.preview_dir, seed=args.seed)
        _print_preview_reports(reports)
        return 0

    if args.preview_th18era:
        reports = generate_th18era_previews(
            output_dir=args.preview_dir,
            seed=args.seed,
            village_background=True,
            use_photo_backgrounds=not args.flat_background,
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
        village_background=True,
        use_photo_backgrounds=not args.flat_background,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
