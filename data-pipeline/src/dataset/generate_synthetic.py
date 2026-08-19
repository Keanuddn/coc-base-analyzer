"""Generate bulk synthetic YOLO-labeled village renders (perfect labels).

Layouts are random-but-plausible occupancy on the 44×44 editor grid.
**Which buildings exist at a TH, and how many**, come from
``renderer/sprites/th_unlocks.yaml`` ``count_by_th`` (internet-sourced; see
``knowledge-base/SOURCES.md``). Types without a sourced row are omitted.
Exact wiki counts are placed (not a random subset). If occupancy cannot fit
every copy, as many as possible are placed and a warning is logged.

Sprite levels use a **visual-tier proxy** (not an official CoC cap),
with sourced merge windows:

* Cannons max at TH15 (``cannon/level_21.webp`` purple). TH16 places
  remaining regular cannons **plus** ``ricochet_cannon`` (wiki 3+2).
  TH17–18: 0 regular + 3 ricochet. Regulars stay YOLO ``canon``;
  ricochet is ``ricochetcannon`` (not aliased to canon).
* Archer towers: remaining regulars labeled ``archertower`` plus
  ``multi-archer_tower`` (YOLO ``multiarchertower``) per wiki.
* Wizard towers max at TH17. TH18 places remaining regulars **plus**
  ``super_wizard_tower``. Regulars stay ``wizztower``; Super Wizard is
  ``superwizztower`` (not aliased to wizztower).
* Eagle artillery TH11–16; removed at TH17 (merged into Inferno Artillery).
* Firespitter TH17+; Multi-Gear Tower TH17+; Revenge Tower TH18.
* Spell towers: wiki Number Available is 2 at TH15–18 (user confirmed
  TH15 2026-08-17). Place 2 per layout; cycle ClashKing ``level_1``–``4``
  evenly so all four designs appear in the dataset.
* Monolith TH15+; Hidden Tesla TH7+; weaponized Builder Hut TH14+.
* Walls (``wall/``): visual-tier from maxed TH18. 1×1 tiles, unlabeled.
  Walls may touch each other; non-wall buildings prefer a 1.25-tile gap
  (ceil → two empty tiles) and fall back to one empty tile if a copy
  would otherwise not fit. Town hall / walls stay a single sprite.
* Other defenses use ClashKing max / max-1 / max-2 / max-3 for
  TH18 / 17 / 16 / 15 — **one** TH-max sprite per type (TH15 cannons
  are always ``cannon/level_21.webp``). Mix max and previous **only**
  when the wiki documents two distinct building levels at that same TH
  (Ricochet / Multi-Archer L1+L2 at TH16, Super Wizard L1+L2 at TH18,
  Firespitter / Multi-Gear L1+L2 at TH17, Revenge L1+L2 at TH18,
  Monolith L1+L2 at TH15). Spell towers still cycle the four designs.
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
    BUILDING_GAP_TILES,
    BUILDING_TYPE_MAP_PATH,
    CLASHKING_HOME_VILLAGE,
    COC_TILE_FOOTPRINTS,
    GRID_SIZE,
    SPRITE_RENDER_SCALE,
    TILE_FOOTPRINTS,
    TILE_WIDTH,
    YOLO_CLASS_NAMES,
    IsometricRenderer,
    list_sprite_levels,
    occupancy_tiles,
    occupied_cells,
    gap_pad_tiles,
    placement_in_playable_grid,
    scale_sprite_size,
    sprite_stays_on_playable,
    town_hall_yolo_class,
    _load_building_type_map,
    _slug_for_building_type,
    _yolo_class_id,
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
    "ricochet_cannon",
    "multi-archer_tower",
    "super_wizard_tower",
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

# Wiki Number Available after required merges. Source: Town Hall page
# https://clashofclans.fandom.com/wiki/Town_Hall  (accessed 2026-08-17).
# Fallback if th_unlocks.yaml is missing a count_by_th row.
WIKI_COUNT_BY_TH: dict[str, dict[int, int]] = {
    "town_hall": {15: 1, 16: 1, 17: 1, 18: 1},
    "clancastle": {15: 1, 16: 1, 17: 1, 18: 1},
    "canon": {15: 7, 16: 3, 17: 0, 18: 0},
    "archertower": {15: 8, 16: 4, 17: 2, 18: 2},
    "wizztower": {15: 5, 16: 5, 17: 5, 18: 2},
    "mortar": {15: 4, 16: 4, 17: 4, 18: 4},
    "ad": {15: 4, 16: 4, 17: 4, 18: 4},
    "airsweeper": {15: 2, 16: 2, 17: 2, 18: 2},
    "tesla": {15: 5, 16: 5, 17: 5, 18: 5},
    "bombtower": {15: 2, 16: 2, 17: 2, 18: 2},
    "xbow": {15: 4, 16: 4, 17: 4, 18: 4},
    "inferno": {15: 3, 16: 3, 17: 3, 18: 3},
    "eagle": {15: 1, 16: 1, 17: 0, 18: 0},
    "scattershot": {15: 2, 16: 2, 17: 2, 18: 2},
    "builderhut": {15: 5, 16: 5, 17: 5, 18: 5},
    "spelltower": {15: 2, 16: 2, 17: 2, 18: 2},
    "monolith": {15: 1, 16: 1, 17: 1, 18: 1},
    "ricochet_cannon": {15: 0, 16: 2, 17: 3, 18: 3},
    "multi-archer_tower": {15: 0, 16: 2, 17: 3, 18: 3},
    "firespitter": {15: 0, 16: 0, 17: 2, 18: 2},
    "multi-gear_tower": {15: 0, 16: 0, 17: 1, 18: 1},
    "super_wizard_tower": {15: 0, 16: 0, 17: 0, 18: 2},
    "revenge_tower": {15: 0, 16: 0, 17: 0, 18: 1},
}

# Wiki: two *building* levels both require this TH (not "previous TH max").
# Accessed 2026-08-17. Default is exact TH-max sprite; mix only these.
# https://clashofclans.fandom.com/wiki/Ricochet_Cannon (L1+L2 → TH16)
# https://clashofclans.fandom.com/wiki/Multi-Archer_Tower (L1+L2 → TH16)
# https://clashofclans.fandom.com/wiki/Super_Wizard_Tower/Home_Village (L1+L2 → TH18)
# https://clashofclans.fandom.com/wiki/Firespitter (L1+L2 → TH17; L3 → TH18)
# https://www.clasher.us/clash-of-clans/unit/multi-gear-tower-home-village (L1+L2 → TH17)
# https://clashofclans.fandom.com/wiki/Revenge_Tower (L1+L2 → TH18)
# https://clashofclans.fandom.com/wiki/Monolith (L1+L2 → TH15; L3 → TH16)
# Cross-check: https://www.clash.ninja/guides/max-levels-for-each-th
WIKI_MIX_LEVELS_BY_TH: dict[str, dict[int, tuple[int, ...]]] = {
    "ricochet_cannon": {16: (1, 2)},
    "multi-archer_tower": {16: (1, 2)},
    "super_wizard_tower": {18: (1, 2)},
    "firespitter": {17: (1, 2)},
    "multi-gear_tower": {17: (1, 2)},
    "revenge_tower": {18: (1, 2)},
    "monolith": {15: (1, 2)},
}

# Occupancy fallbacks only — placement uses count_by_th / WIKI_COUNT_BY_TH.
COUNT_RANGES: dict[str, tuple[int, int]] = {
    name: (counts.get(15, 0), max(counts.values()) if counts else 0)
    for name, counts in WIKI_COUNT_BY_TH.items()
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
    "ricochet_cannon",
    "multi-archer_tower",
    "super_wizard_tower",
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
        if merge is not None:
            # Remaining regulars stay at the pre-merge max sprite (e.g. cannon 21).
            era_max = int(merge["max_regular_th"])
        return visual_tier_level(
            self.levels_for(building_type),
            town_hall_level,
            era_max=era_max,
        )

    def mixes_sprite_levels(self, building_type: str, town_hall_level: int) -> bool:
        """True only when wiki documents two building levels at this TH."""
        if building_type in {"town_hall", "wall"}:
            return False
        if self.uses_random_variants(building_type):
            return False
        mix = self._mix_visual_levels(building_type, town_hall_level)
        return mix is not None and len(mix) > 1

    def previous_sprite_level(self, building_type: str, level: int) -> int | None:
        """Next-lower ClashKing file in the catalog, if any."""
        below = [lv for lv in sorted(self.levels_for(building_type)) if lv < level]
        return below[-1] if below else None

    def _mix_visual_levels(
        self, building_type: str, town_hall_level: int
    ) -> list[int] | None:
        """Wiki visual levels to mix at this TH, or None for exact TH-max.

        Prefer ``th_unlocks.yaml`` ``visual_levels_by_th`` / ``mix_levels``.
        Fallback: ``WIKI_MIX_LEVELS_BY_TH``. ``mix_levels: true`` without a
        per-TH map means mix max+previous **only at min_th** (unlock TH).
        """
        avail = self._availability(building_type)
        by_th: Mapping[str, Any] | None = None
        mix_flag = False
        if isinstance(avail, Mapping):
            raw = avail.get("visual_levels_by_th") or avail.get("mix_levels_by_th")
            if isinstance(raw, Mapping):
                by_th = raw
            mix_flag = bool(avail.get("mix_levels"))
        if by_th is not None:
            levels = by_th.get(town_hall_level)
            if levels is None:
                levels = by_th.get(str(town_hall_level))
            if levels is not None:
                return [int(x) for x in levels]
        fallback = WIKI_MIX_LEVELS_BY_TH.get(building_type)
        if fallback is not None and town_hall_level in fallback:
            return list(fallback[town_hall_level])
        if mix_flag and isinstance(avail, Mapping):
            min_th = avail.get("min_th")
            if min_th is not None and int(min_th) == town_hall_level:
                max_lv = self.sprite_level(building_type, town_hall_level)
                prev = self.previous_sprite_level(building_type, max_lv)
                if prev is not None:
                    return [prev, max_lv]
        return None

    def sprite_levels_for_th(self, building_type: str, town_hall_level: int) -> list[int]:
        """TH-max ClashKing sprite, plus previous only when wiki lists both.

        Regular defenses (cannon, AT, mortar, …) return one level — the
        visual-tier TH-max. Merge/new buildings listed in
        ``WIKI_MIX_LEVELS_BY_TH`` / yaml return both wiki levels at that TH
        (e.g. ``ricochet_cannon`` 1 and 2 at TH16).
        """
        max_lv = self.sprite_level(building_type, town_hall_level)
        mix = self._mix_visual_levels(building_type, town_hall_level)
        if not mix:
            return [max_lv]
        catalog_levels = set(self.levels_for(building_type))
        available = [lv for lv in mix if lv in catalog_levels]
        return available or [max_lv]

    def mixed_levels_for_layout(
        self,
        building_type: str,
        town_hall_level: int,
        count: int,
        rng: random.Random,
    ) -> list[int]:
        """Round-robin wiki visual levels when this TH has two of them.

        Two copies (TH16 ricochet) always show both ClashKing files.
        Types without a wiki mix list use the single TH-max sprite.
        """
        available = self.sprite_levels_for_th(building_type, town_hall_level)
        if count <= 0:
            return []
        if len(available) == 1:
            return [available[0]] * count
        start = rng.randrange(len(available))
        return [available[(start + i) % len(available)] for i in range(count)]

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
        if self.count_for(building_type, town_hall_level) <= 0:
            return None
        merge = self._merge_rule(building_type)
        if merge is None:
            return building_type, self.sprite_level(building_type, town_hall_level)
        # Regular remaining copies keep the unmerged sprite; merged slugs are
        # placed separately from their own count_by_th rows.
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

    def cycled_variant_levels(self, building_type: str, cycle: int, count: int) -> list[int]:
        """Consecutive ClashKing variants wrapping around, offset by cycle.

        Two spell towers per layout × four designs → cycle so all four appear
        evenly across TH15–18 previews and a bulk batch.
        """
        levels = self.levels_for(building_type)
        if not levels or count <= 0:
            return []
        offset = cycle % len(levels)
        rotated = levels[offset:] + levels[:offset]
        if count >= len(rotated):
            return list(rotated)
        return rotated[:count]

    def count_for(self, building_type: str, town_hall_level: int) -> int:
        """Exact wiki Number Available at this TH (0 if absent)."""
        avail = self._availability(building_type)
        if avail is not None:
            if not self._rule_allows(avail, town_hall_level):
                return 0
            by_th = avail.get("count_by_th") or avail.get("wiki_count_by_th")
            if isinstance(by_th, Mapping):
                if town_hall_level in by_th:
                    return int(by_th[town_hall_level])
                key = str(town_hall_level)
                if key in by_th:
                    return int(by_th[key])
        fallback = WIKI_COUNT_BY_TH.get(building_type)
        if fallback is not None:
            return int(fallback.get(town_hall_level, 0))
        return 0

    def expected_counts(self, town_hall_level: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for name in SYNTHETIC_BUILDING_TYPES:
            n = self.count_for(name, town_hall_level)
            if n > 0:
                counts[name] = n
        return counts

    def count_range_for(self, building_type: str, town_hall_level: int) -> tuple[int, int]:
        n = self.count_for(building_type, town_hall_level)
        return n, n

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
            return scale_sprite_size(*dims)
        from renderer.isometric_renderer import SPRITE_NORTH_PAD_PX, TILE_HEIGHT

        tiles = COC_TILE_FOOTPRINTS.get(building_type, TILE_FOOTPRINTS.get(building_type, 3))
        raw_w, raw_h = tiles * TILE_WIDTH, tiles * TILE_HEIGHT + SPRITE_NORTH_PAD_PX
        return scale_sprite_size(raw_w, raw_h)

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
    pad: int | None = None,
) -> bool:
    if not placement_in_playable_grid(x, y, size):
        return False
    if occupied_cells(x, y, size) & occupied:
        return False
    # Prefer BUILDING_GAP_TILES (1.25 → 2 empty tiles). Callers may pass pad=1
    # so leftover copies still fit and wiki counts stay exact. Walls ignore this.
    if pad is None:
        pad = gap_pad_tiles()
    dilated = occupied_cells(x - pad, y - pad, size + 2 * pad)
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
    pad: int | None = None,
) -> tuple[int, int] | None:
    limit = GRID_SIZE - size
    if limit < 0:
        return None
    use_pad = gap_pad_tiles() if pad is None else pad

    def _ok(x: int, y: int) -> bool:
        return _fits(
            occupied,
            x,
            y,
            size,
            sprite_w=sprite_w,
            sprite_h=sprite_h,
            pad=use_pad,
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
        if use_pad > 1:
            return _try_place(
                occupied,
                size,
                rng,
                sprite_w=sprite_w,
                sprite_h=sprite_h,
                prefer_center=True,
                max_attempts=max_attempts,
                pad=1,
            )
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
    if use_pad > 1:
        return _try_place(
            occupied,
            size,
            rng,
            sprite_w=sprite_w,
            sprite_h=sprite_h,
            prefer_center=False,
            max_attempts=max_attempts,
            pad=1,
        )
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
    """Place a TH plus the sourced defense set without grid overlap.

    Town hall sprite is exactly ``town_hall_level``. Other types use one
    visual-tier file, with cannon/archer/wizard remaining regulars plus
    merged buildings from ``count_by_th``. Availability is
    ``th_unlocks.yaml``: eagle ≤ TH16, firespitter ≥ TH17, spell towers 2
    at TH15–18, remaining cannons/archers/wizards after merges as sourced.
    Non-wall buildings prefer a 1.25-tile gap (ceil → 2 empty tiles) and
    fall back to 1 empty tile so wiki counts still fit; walls are 1×1 and
    may touch. Occupied tiles are never reused. If a building cannot fit
    after retries, as many copies as possible are placed and a warning is
    logged.
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
        count = catalog.count_for(building_type, town_hall_level)
        if count <= 0:
            continue
        if catalog.uses_random_variants(building_type):
            levels_to_place = catalog.cycled_variant_levels(
                building_type, variant_cycle, count
            )
        elif catalog.mixes_sprite_levels(place_type, town_hall_level):
            levels_to_place = catalog.mixed_levels_for_layout(
                place_type, town_hall_level, count, rng
            )
        else:
            levels_to_place = [level] * count
        placed_n = 0
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
                continue
            _mark(occupied, pos[0], pos[1], size)
            placements.append(
                BuildingPlacement(place_type, level=place_level, x=pos[0], y=pos[1])
            )
            placed_n += 1
        if placed_n < count:
            logging.warning(
                "TH%s %s: placed %d/%d (occupancy)",
                town_hall_level,
                place_type,
                placed_n,
                count,
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
    town_hall_level: int | None = None,
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
        allows_mix = catalog.uses_random_variants(placement.building_type)
        if town_hall_level is not None:
            allows_mix = allows_mix or catalog.mixes_sprite_levels(
                placement.building_type, town_hall_level
            )
        if placement.level != entry["level"] and not allows_mix:
            mixed.append(f"{placement.building_type}@{placement.level}")
    return {
        "by_type": dict(sorted(by_type.items())),
        "mixed_levels": mixed,
    }


def compare_defense_counts(
    placements: Sequence[BuildingPlacement],
    catalog: SpriteLevelCatalog,
    town_hall_level: int,
) -> dict[str, Any]:
    """Actual vs yaml expected counts (walls excluded)."""
    expected = catalog.expected_counts(town_hall_level)
    actual: dict[str, int] = {}
    for placement in placements:
        if placement.building_type == "wall":
            continue
        actual[placement.building_type] = actual.get(placement.building_type, 0) + 1
    rows: list[dict[str, Any]] = []
    short: list[str] = []
    for name in sorted(set(expected) | set(actual)):
        exp = expected.get(name, 0)
        got = actual.get(name, 0)
        rows.append({"type": name, "expected": exp, "actual": got})
        if got < exp:
            short.append(f"{name} {got}/{exp}")
    return {
        "expected": expected,
        "actual": actual,
        "rows": rows,
        "short": short,
        "sprite_scale": SPRITE_RENDER_SCALE,
        "building_gap_tiles": BUILDING_GAP_TILES,
    }


def tally_yolo_label_dir(directory: Path) -> dict[str, Any]:
    """Count boxes per class from YOLO txt files under ``directory``."""
    by_class: dict[str, int] = {name: 0 for name in YOLO_CLASS_NAMES}
    unknown = 0
    files = 0
    if not directory.is_dir():
        return {"files": 0, "by_class": by_class, "unknown_ids": 0, "total_boxes": 0}
    for txt in sorted(directory.rglob("*.txt")):
        files += 1
        for line in txt.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            class_id = int(parts[0])
            if 0 <= class_id < len(YOLO_CLASS_NAMES):
                by_class[YOLO_CLASS_NAMES[class_id]] += 1
            else:
                unknown += 1
    return {
        "files": files,
        "by_class": by_class,
        "unknown_ids": unknown,
        "total_boxes": sum(by_class.values()) + unknown,
    }


def _infer_th_from_path(path: Path) -> int | None:
    """Infer TH level from ``th15/`` parent folder or ``th15_`` filename prefix."""
    for part in path.parts:
        lower = part.lower()
        if lower.startswith("th") and lower[2:].isdigit():
            return int(lower[2:])
    stem = path.stem.lower()
    if stem.startswith("th") and len(stem) >= 4 and stem[2:4].isdigit():
        return int(stem[2:4])
    return None


def relabel_synthetic_town_halls(output_dir: Path) -> dict[str, Any]:
    """Rewrite existing YOLO txts so the hall box matches the folder TH.

    Only remaps class id 12 (``th13``) → ``th14``…``th18``. Box geometry is
    unchanged so scenery and placements stay identical. Idempotent.
    """
    old_id = _yolo_class_id("th13")
    if old_id is None:
        raise RuntimeError("th13 missing from YOLO_CLASS_NAMES")

    files_seen = 0
    files_changed = 0
    halls_relabeled = 0
    skipped_no_th = 0
    skipped_no_hall = 0

    for txt in sorted(output_dir.rglob("*.txt")):
        files_seen += 1
        th_level = _infer_th_from_path(txt)
        if th_level is None:
            skipped_no_th += 1
            continue
        new_name = town_hall_yolo_class(th_level)
        new_id = _yolo_class_id(new_name)
        if new_id is None or new_id == old_id:
            continue
        original = txt.read_text(encoding="utf-8")
        changed_here = 0
        out_lines: list[str] = []
        for line in original.splitlines():
            parts = line.split()
            if len(parts) >= 5 and int(parts[0]) == old_id:
                parts[0] = str(new_id)
                changed_here += 1
                out_lines.append(" ".join(parts))
            else:
                out_lines.append(line)
        if changed_here == 0:
            skipped_no_hall += 1
            continue
        trailing = "\n" if original.endswith("\n") or not original else ""
        txt.write_text("\n".join(out_lines) + trailing, encoding="utf-8")
        files_changed += 1
        halls_relabeled += changed_here

    return {
        "output_dir": str(output_dir),
        "files_seen": files_seen,
        "files_changed": files_changed,
        "halls_relabeled": halls_relabeled,
        "skipped_no_th": skipped_no_th,
        "skipped_no_hall": skipped_no_hall,
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
        "class_counts": tally_yolo_label_dir(output_dir),
        "nc": len(YOLO_CLASS_NAMES),
        "class_names": list(YOLO_CLASS_NAMES),
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
        level_info = summarize_placement_levels(
            placements, catalog, town_hall_level=th_level
        )
        counts = compare_defense_counts(placements, catalog, th_level)
        report = {
            "file": str(out_png),
            "town_hall_level": th_level,
            "skipped": False,
            "sprite_levels": level_info["by_type"],
            "mixed_levels": level_info["mixed_levels"],
            "level_policy": catalog.policy,
            "not_official_coc_cap": catalog.not_official_coc_cap,
            "background": result.background_path.name if result.background_path else None,
            "counts": counts,
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
        level_info = summarize_placement_levels(
            placements, catalog, town_hall_level=th_level
        )
        counts = compare_defense_counts(placements, catalog, th_level)
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
                "counts": counts,
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
    print(
        f"\nDefense counts vs wiki (scale={SPRITE_RENDER_SCALE}, "
        f"gap={BUILDING_GAP_TILES} tile between non-wall buildings):"
    )
    for report in reports:
        th = report["town_hall_level"]
        if report.get("skipped"):
            print(f"  TH{th}: SKIPPED")
            continue
        counts = report.get("counts") or {}
        rows = counts.get("rows") or []
        print(f"  TH{th}:")
        for row in rows:
            flag = "" if row["actual"] == row["expected"] else "  <-- short"
            print(
                f"    {row['type']:22} {row['actual']:>2}/{row['expected']:<2}{flag}"
            )
        short = counts.get("short") or []
        if short:
            print(f"    occupancy shortfalls: {', '.join(short)}")
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
    parser.add_argument(
        "--relabel-town-halls",
        action="store_true",
        help=(
            "Rewrite existing synthetic YOLO txts in --output so the hall box "
            "uses th15–th18 from the folder name (no PNG re-render)"
        ),
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

    if args.relabel_town_halls:
        summary = relabel_synthetic_town_halls(args.output)
        print(json.dumps(summary, indent=2))
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
    class_counts = summary.get("class_counts") or {}
    by_class = class_counts.get("by_class") or {}
    print("\nPer-class YOLO boxes:")
    for idx, name in enumerate(YOLO_CLASS_NAMES):
        print(f"  {idx:2d} {name:20} {by_class.get(name, 0)}")
    print(f"  files={class_counts.get('files', 0)} total_boxes={class_counts.get('total_boxes', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
