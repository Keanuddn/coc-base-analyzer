"""Tests for bulk synthetic YOLO generation from the isometric renderer."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from dataset.generate_synthetic import (
    MERGED_PLACEMENT_TYPES,
    MIN_WALL_SEGMENTS,
    REQUESTED_TOWN_HALL_LEVELS,
    SPELL_TOWER_VARIANT_FILES,
    SYNTHETIC_BUILDING_TYPES,
    TILE_FOOTPRINTS,
    TOWN_HALL_LEVELS,
    WIKI_COUNT_BY_TH,
    RESOURCE_ARMY_TYPES,
    SpriteLevelCatalog,
    generate_random_layout,
    generate_scenery_previews,
    generate_synthetic_dataset,
    generate_th18era_previews,
    relabel_synthetic_town_halls,
    visual_tier_level,
)
from renderer.isometric_renderer import (
    BUILDING_GAP_TILES,
    COC_TILE_FOOTPRINTS,
    GRID_SIZE,
    IsometricRenderer,
    OCCUPANCY_PAD_TILES,
    SPRITE_RENDER_SCALE,
    YOLO_CLASS_NAMES,
    gap_pad_tiles,
    occupancy_tiles,
    occupied_cells,
)

_TYPE_MAP = {
    "aliases": {
        "ad": "air_defense",
        "airsweeper": "air_sweeper",
        "bombtower": "bomb_tower",
        "canon": "cannon",
        "clancastle": "clan_castle",
        "eagle": "eagle_artillery",
        "inferno": "inferno_tower",
        "mortar": "mortar",
        "scattershot": "scattershot",
        "wizztower": "wizard_tower",
        "xbow": "x-bow",
        "archertower": "archer_tower",
        "firespitter": "firespitter",
        "spelltower": "spell_tower",
        "tesla": "hidden_tesla",
        "builderhut": "builder's_hut",
        "monolith": "monolith",
        "goldstorage": "gold_storage",
        "elixirstorage": "elixir_storage",
        "darkelixirstorage": "dark_elixir_storage",
        "goldmine": "gold_mine",
        "elixircollector": "elixir_collector",
        "darkelixirdrill": "dark_elixir_drill",
        "armycamp": "army_camp",
        "barracks": "barracks",
        "darkbarracks": "dark_barracks",
        "laboratory": "laboratory",
        "spellfactory": "spell_factory",
        "darkspellfactory": "dark_spell_factory",
        "workshop": "workshop",
        "pethouse": "pet_house",
        "blacksmith": "blacksmith",
        "herohall": "hero_hall",
    },
    "identity": [
        "cannon",
        "ricochet_cannon",
        "super_wizard_tower",
        "town_hall",
        "wizard_tower",
        "archer_tower",
        "multi-archer_tower",
        "firespitter",
        "spell_tower",
        "wall",
        "monolith",
        "hidden_tesla",
        "multi-gear_tower",
        "revenge_tower",
        "builder's_hut",
    ],
    "town_hall": {"sprite_slug": "town_hall", "yolo_class": "th13"},
    "yolo_label_overrides": {
        "ricochet_cannon": "ricochetcannon",
        "super_wizard_tower": "superwizztower",
        "multi-archer_tower": "multiarchertower",
        "multi-gear_tower": "multigeartower",
        "revenge_tower": "revengetower",
    },
    "yolo_unlabeled": [
        "wall",
    ],
    "random_sprite_variants": {
        "spelltower": {
            "slug": "spell_tower",
            "place_all": False,
            "files": [
                "spell_tower/level_1.webp",
                "spell_tower/level_2.webp",
                "spell_tower/level_3.webp",
                "spell_tower/level_4.webp",
            ],
        },
    },
    "era_availability": {
        "eagle": {"min_th": 11, "max_th": 16, "removed_at": 17, "count_range": [1, 1]},
        "firespitter": {"min_th": 17},
        "spelltower": {
            "min_th": 15,
            "max_th": 18,
            "count_by_th": {15: 2, 16: 2, 17: 2, 18: 2},
        },
        "monolith": {"min_th": 15, "count_range": [1, 1]},
        "tesla": {"min_th": 7},
        "builderhut": {"min_th": 14},
        "multi-gear_tower": {"min_th": 17, "count_range": [1, 1]},
        "revenge_tower": {"min_th": 18, "count_range": [1, 1]},
    },
    "era_merges": {
        "canon": {
            "regular_slug": "cannon",
            "max_regular_th": 15,
            "merged_slug": "ricochet_cannon",
            "merged_from_th": 16,
            "yolo_class": "ricochetcannon",
            "count_range": [2, 3],
        },
        "archertower": {
            "regular_slug": "archer_tower",
            "max_regular_th": 15,
            "merged_slug": "multi-archer_tower",
            "merged_from_th": 16,
            "yolo_class": "multiarchertower",
            "count_range": [2, 3],
        },
        "wizztower": {
            "regular_slug": "wizard_tower",
            "max_regular_th": 17,
            "merged_slug": "super_wizard_tower",
            "merged_from_th": 18,
            "yolo_class": "superwizztower",
            "count_range": [1, 3],
        },
    },
}


def _fake_catalog(**overrides: object) -> SpriteLevelCatalog:
    """Sprite coverage snapshot matching ClashKing folders — not official CoC caps."""
    levels = {
        "canon": list(range(1, 22)),
        "mortar": list(range(1, 19)),
        "inferno": list(range(1, 13)),
        "eagle": list(range(1, 8)),
        "xbow": list(range(1, 14)),
        "scattershot": list(range(1, 8)),
        "wizztower": list(range(1, 18)),
        "ricochet_cannon": list(range(1, 5)),
        "super_wizard_tower": list(range(1, 3)),
        "ad": list(range(1, 17)),
        "bombtower": list(range(1, 14)),
        "airsweeper": list(range(1, 8)),
        "clancastle": list(range(1, 15)),
        "town_hall": list(range(1, 19)),
        "archertower": list(range(1, 22)),
        "multi-archer_tower": list(range(1, 5)),
        "firespitter": list(range(1, 4)),
        "spelltower": list(range(1, 5)),
        "wall": list(range(1, 20)),
        "monolith": list(range(1, 6)),
        "tesla": list(range(1, 18)),
        "builderhut": list(range(1, 9)),
        "multi-gear_tower": list(range(1, 4)),
        "revenge_tower": list(range(1, 3)),
        "goldstorage": list(range(1, 20)),
        "elixirstorage": list(range(1, 20)),
        "darkelixirstorage": list(range(1, 14)),
        "goldmine": list(range(1, 18)),
        "elixircollector": list(range(1, 18)),
        "darkelixirdrill": list(range(1, 12)),
        "armycamp": list(range(1, 15)),
        "barracks": list(range(1, 20)),
        "darkbarracks": list(range(1, 14)),
        "laboratory": list(range(1, 17)),
        "spellfactory": list(range(1, 10)),
        "darkspellfactory": list(range(1, 9)),
        "workshop": list(range(1, 10)),
        "pethouse": list(range(1, 13)),
        "blacksmith": list(range(1, 10)),
        "herohall": list(range(1, 13)),
    }
    kwargs: dict[str, object] = {
        "levels_by_type": levels,
        "era_max_town_hall": 18,
        "requested_town_hall_levels": (15, 16, 17, 18),
        "policy": "visual-tier-proxy",
        "not_official_coc_cap": True,
        "type_map": _TYPE_MAP,
    }
    kwargs.update(overrides)
    return SpriteLevelCatalog(**kwargs)  # type: ignore[arg-type]


def _assert_non_overlapping_in_bounds(
    placements: list,
    catalog: SpriteLevelCatalog,
) -> None:
    occupied: dict[tuple[int, int], str] = {}
    for placement in placements:
        size = catalog.occupancy_size(placement.building_type, placement.level)
        assert 0 <= placement.x <= GRID_SIZE - size
        assert 0 <= placement.y <= GRID_SIZE - size
        assert placement.x + size <= GRID_SIZE
        assert placement.y + size <= GRID_SIZE
        for cell in occupied_cells(placement.x, placement.y, size):
            assert cell not in occupied, f"overlap at {cell}"
            occupied[cell] = placement.building_type


class TestGenerateRandomLayout:
    def test_includes_town_hall_and_only_allowed_types(self) -> None:
        catalog = _fake_catalog()
        placements = generate_random_layout(
            random.Random(0), town_hall_level=15, catalog=catalog
        )
        types = {p.building_type for p in placements}
        assert "town_hall" in types
        assert types <= set(SYNTHETIC_BUILDING_TYPES) | MERGED_PLACEMENT_TYPES | {"wall"}
        assert all(p.building_type != "kingpad" for p in placements)
        th = next(p for p in placements if p.building_type == "town_hall")
        assert th.level == 15

    def test_th16_sets_town_hall_level(self) -> None:
        placements = generate_random_layout(
            random.Random(1), town_hall_level=16, catalog=_fake_catalog()
        )
        th = next(p for p in placements if p.building_type == "town_hall")
        assert th.level == 16

    def test_th17_and_th18_set_exact_town_hall_sprite(self) -> None:
        for th_level in (17, 18):
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=_fake_catalog()
            )
            th = next(p for p in placements if p.building_type == "town_hall")
            assert th.level == th_level

    def test_buildings_do_not_overlap_on_grid(self) -> None:
        catalog = _fake_catalog()
        placements = generate_random_layout(
            random.Random(7), town_hall_level=16, catalog=catalog
        )
        _assert_non_overlapping_in_bounds(placements, catalog)

    def test_all_placements_inside_playable_grid_minus_size(self) -> None:
        catalog = _fake_catalog()
        for seed in (0, 7, 42, 99):
            for th_level in (15, 16, 17, 18):
                placements = generate_random_layout(
                    random.Random(seed + th_level),
                    town_hall_level=th_level,
                    catalog=catalog,
                )
                assert placements
                _assert_non_overlapping_in_bounds(placements, catalog)

    def test_th18_layout_has_ricochet_and_super_wizard(self) -> None:
        catalog = _fake_catalog()
        placements = generate_random_layout(
            random.Random(18), town_hall_level=18, catalog=catalog
        )
        types = {p.building_type for p in placements}
        assert "ricochet_cannon" in types
        assert "super_wizard_tower" in types
        assert "multi-archer_tower" in types
        assert "canon" not in types
        assert "wizztower" in types
        assert "archertower" in types
        assert occupancy_tiles("ricochet_cannon") == COC_TILE_FOOTPRINTS["ricochet_cannon"]
        assert occupancy_tiles("super_wizard_tower") == COC_TILE_FOOTPRINTS["super_wizard_tower"]
        ricochets = [p for p in placements if p.building_type == "ricochet_cannon"]
        wizards = [p for p in placements if p.building_type == "super_wizard_tower"]
        assert ricochets and wizards
        _assert_non_overlapping_in_bounds(placements, catalog)

    def test_seed_is_deterministic(self) -> None:
        catalog = _fake_catalog()
        a = generate_random_layout(random.Random(42), town_hall_level=15, catalog=catalog)
        b = generate_random_layout(random.Random(42), town_hall_level=15, catalog=catalog)
        assert [(p.building_type, p.x, p.y, p.level) for p in a] == [
            (p.building_type, p.x, p.y, p.level) for p in b
        ]

    def test_conservative_footprints_cover_coc_and_sprite_aabb(self) -> None:
        assert occupancy_tiles("town_hall") == COC_TILE_FOOTPRINTS["town_hall"]
        assert occupancy_tiles("eagle") == COC_TILE_FOOTPRINTS["eagle"]
        assert occupancy_tiles("inferno") == COC_TILE_FOOTPRINTS["inferno"]
        assert occupancy_tiles("canon") == COC_TILE_FOOTPRINTS["canon"]
        assert occupancy_tiles("super_wizard_tower") >= occupancy_tiles("wizztower")
        assert BUILDING_GAP_TILES == 1.25
        assert gap_pad_tiles() == 2
        assert SPRITE_RENDER_SCALE == 0.80
        assert OCCUPANCY_PAD_TILES == 0


class TestGenerateSyntheticDataset:
    def test_writes_png_and_yolo_txt_pairs(self, tmp_path: Path) -> None:
        result = generate_synthetic_dataset(count=2, output_dir=tmp_path, seed=0)
        assert result["images"] == 2
        pngs = sorted(tmp_path.rglob("*.png"))
        assert len(pngs) == 2
        for png in pngs:
            txt = png.with_suffix(".txt")
            assert txt.is_file()
            lines = [ln for ln in txt.read_text(encoding="utf-8").splitlines() if ln.strip()]
            assert lines
            for line in lines:
                parts = line.split()
                assert len(parts) == 5
                class_id = int(parts[0])
                assert 0 <= class_id < len(YOLO_CLASS_NAMES)
                assert YOLO_CLASS_NAMES[class_id] not in {"kingpad", "queenpad", "rcpad", "wardenpad"}
                for val in parts[1:]:
                    f = float(val)
                    assert 0.0 <= f <= 1.0

    def test_new_defense_class_ids_appear_and_walls_unlabeled(self, tmp_path: Path) -> None:
        generate_synthetic_dataset(count=4, output_dir=tmp_path, seed=0)
        by_th: dict[str, set[str]] = {}
        for txt in tmp_path.rglob("*.txt"):
            names: set[str] = set()
            for line in txt.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) < 5:
                    continue
                names.add(YOLO_CLASS_NAMES[int(parts[0])])
            by_th[txt.parent.name] = names
            assert "wall" not in names
        assert "archertower" in by_th["th15"]
        assert "tesla" in by_th["th15"]
        assert "monolith" in by_th["th15"]
        assert "spelltower" in by_th["th15"]
        assert "builderhut" in by_th["th15"]
        assert "goldstorage" in by_th["th15"]
        assert "elixirstorage" in by_th["th15"]
        assert "darkelixirstorage" in by_th["th15"]
        assert "goldmine" in by_th["th15"]
        assert "elixircollector" in by_th["th15"]
        assert "darkelixirdrill" in by_th["th15"]
        assert "ricochetcannon" not in by_th["th15"]
        assert "firespitter" not in by_th["th15"]
        assert "ricochetcannon" in by_th["th16"]
        assert "multiarchertower" in by_th["th16"]
        assert "monolith" in by_th["th16"]
        assert "firespitter" in by_th["th17"]
        assert "multigeartower" in by_th["th17"]
        assert "revengetower" in by_th["th18"]
        assert "superwizztower" in by_th["th18"]
        assert "archertower" in by_th["th18"]
        assert "th15" in by_th["th15"]
        assert "th13" not in by_th["th15"]
        assert "th16" in by_th["th16"]
        assert "th13" not in by_th["th16"]
        assert "th17" in by_th["th17"]
        assert "th13" not in by_th["th17"]
        assert "th18" in by_th["th18"]
        assert "th13" not in by_th["th18"]

    def test_varies_th_level_in_output_paths(self, tmp_path: Path) -> None:
        generate_synthetic_dataset(count=4, output_dir=tmp_path, seed=3)
        pngs = list(tmp_path.rglob("*.png"))
        th_parts = {p.parent.name for p in pngs}
        assert th_parts == {"th15", "th16", "th17", "th18"}


class TestVisualTierProxy:
    def test_default_th_set_is_15_through_18(self) -> None:
        assert TOWN_HALL_LEVELS == (15, 16, 17, 18)
        assert REQUESTED_TOWN_HALL_LEVELS == (15, 16, 17, 18)

    def test_walls_and_town_hall_keep_one_sprite_level(self) -> None:
        catalog = _fake_catalog()
        for th_level in (15, 16, 17, 18):
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            by_type: dict[str, set[int]] = {}
            for placement in placements:
                by_type.setdefault(placement.building_type, set()).add(placement.level)
            for building_type in ("town_hall", "wall"):
                assert len(by_type[building_type]) == 1, building_type

    def test_defenses_mix_max_and_previous_clashking_sprite(self) -> None:
        catalog = _fake_catalog()
        assert catalog.sprite_levels_for_th("ricochet_cannon", 16) == [1, 2]
        assert catalog.sprite_levels_for_th("ricochet_cannon", 17) == [3]
        assert catalog.sprite_levels_for_th("canon", 15) == [21]
        assert catalog.sprite_levels_for_th("archertower", 15) == [21]
        assert catalog.sprite_levels_for_th("multi-archer_tower", 16) == [1, 2]
        assert catalog.sprite_levels_for_th("super_wizard_tower", 18) == [1, 2]
        assert catalog.sprite_levels_for_th("firespitter", 17) == [1, 2]
        assert catalog.sprite_levels_for_th("firespitter", 18) == [3]
        assert catalog.sprite_levels_for_th("monolith", 15) == [1, 2]
        assert catalog.sprite_relpath("ricochet_cannon", 1) == "ricochet_cannon/level_1.webp"
        assert catalog.sprite_relpath("ricochet_cannon", 2) == "ricochet_cannon/level_2.webp"
        placements = generate_random_layout(
            random.Random(16), town_hall_level=16, catalog=catalog
        )
        ricochets = [p for p in placements if p.building_type == "ricochet_cannon"]
        assert len(ricochets) == 2
        assert {p.level for p in ricochets} == {1, 2}
        th15 = generate_random_layout(
            random.Random(15), town_hall_level=15, catalog=catalog
        )
        th15_cannons = [p for p in th15 if p.building_type == "canon"]
        assert th15_cannons
        assert {p.level for p in th15_cannons} == {21}
        th15_archers = [p for p in th15 if p.building_type == "archertower"]
        assert {p.level for p in th15_archers} == {21}
        for th_level in (15, 16, 17, 18):
            layout = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            by_type: dict[str, set[int]] = {}
            for placement in layout:
                by_type.setdefault(placement.building_type, set()).add(placement.level)
            for building_type, levels in by_type.items():
                if catalog.uses_random_variants(building_type):
                    continue
                if catalog.mixes_sprite_levels(building_type, th_level):
                    allowed = set(catalog.sprite_levels_for_th(building_type, th_level))
                    assert levels <= allowed, f"TH{th_level} {building_type} {levels}"
                    continue
                assert len(levels) == 1, f"TH{th_level} {building_type} mixed {levels}"
                assert levels == set(
                    catalog.sprite_levels_for_th(building_type, th_level)
                ), f"TH{th_level} {building_type} {levels}"

    def test_th_offsets_match_max_minus_n(self) -> None:
        catalog = _fake_catalog()
        expected = {18: 18, 17: 17, 16: 16, 15: 15}
        for th_level, mortar_level in expected.items():
            assert catalog.defense_level_for_th("mortar", th_level) == mortar_level

    def test_clamp_at_one_and_lowest_available_not_wrap(self) -> None:
        assert visual_tier_level([1, 2, 3], town_hall_level=15) == 1
        assert visual_tier_level([6, 7], town_hall_level=15) == 6
        assert visual_tier_level([7], town_hall_level=15) == 7
        assert visual_tier_level([7], town_hall_level=18) == 7
        catalog = _fake_catalog()
        catalog.levels_by_type["airsweeper"] = [6, 7]
        assert catalog.defense_level_for_th("airsweeper", 15) == 6
        assert catalog.defense_level_for_th("airsweeper", 18) == 7

    def test_skips_missing_town_hall_sprites(self) -> None:
        catalog = _fake_catalog()
        catalog.levels_by_type["town_hall"] = list(range(1, 17))
        assert catalog.available_town_hall_levels() == [15, 16]
        assert catalog.skipped_town_hall_levels() == [17, 18]


class TestEraMerges:
    """User-corrected merge rules: cannons max TH15, wizards max TH17."""

    def test_th15_uses_highest_regular_cannon(self) -> None:
        catalog = _fake_catalog()
        assert catalog.resolve_for_th("canon", 15) == ("canon", 21)
        placements = generate_random_layout(
            random.Random(1), town_hall_level=15, catalog=catalog
        )
        cannons = [p for p in placements if p.building_type == "canon"]
        assert cannons
        assert {p.level for p in cannons} == {21}
        assert catalog.sprite_relpath("canon", 21) == "cannon/level_21.webp"
        assert not any(p.building_type == "ricochet_cannon" for p in placements)

    def test_th16_plus_places_remaining_cannons_and_ricochet(self) -> None:
        catalog = _fake_catalog()
        expected = {16: 2, 17: 3, 18: 4}
        remaining = {16: 3, 17: 0, 18: 0}
        for th_level, ricochet_level in expected.items():
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            regular = [p for p in placements if p.building_type == "canon"]
            ricochets = [p for p in placements if p.building_type == "ricochet_cannon"]
            assert len(regular) == remaining[th_level]
            assert len(ricochets) == WIKI_COUNT_BY_TH["ricochet_cannon"][th_level]
            assert {p.level for p in ricochets} == set(
                catalog.sprite_levels_for_th("ricochet_cannon", th_level)
            )
            if regular:
                assert {p.level for p in regular} == {21}
            assert catalog.sprite_relpath("ricochet_cannon", ricochet_level) == (
                f"ricochet_cannon/level_{ricochet_level}.webp"
            )

    def test_wizard_towers_max_at_th17(self) -> None:
        catalog = _fake_catalog()
        expected = {15: 15, 16: 16, 17: 17}
        for th_level, wizard_level in expected.items():
            assert catalog.resolve_for_th("wizztower", th_level) == (
                "wizztower",
                wizard_level,
            )
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            wizards = [p for p in placements if p.building_type == "wizztower"]
            assert wizards
            assert {p.level for p in wizards} == {wizard_level}
            assert catalog.sprite_relpath("wizztower", wizard_level) == (
                f"wizard_tower/level_{wizard_level}.webp"
            )
            assert not any(p.building_type == "super_wizard_tower" for p in placements)

    def test_th18_places_remaining_wizards_and_super_wizard(self) -> None:
        catalog = _fake_catalog()
        assert catalog.resolve_for_th("wizztower", 18) == ("wizztower", 17)
        placements = generate_random_layout(
            random.Random(18), town_hall_level=18, catalog=catalog
        )
        regular = [p for p in placements if p.building_type == "wizztower"]
        merged = [p for p in placements if p.building_type == "super_wizard_tower"]
        assert len(regular) == 2
        assert {p.level for p in regular} == {17}
        assert len(merged) == 2
        assert {p.level for p in merged} == {1, 2}
        assert catalog.sprite_relpath("super_wizard_tower", 2) == (
            "super_wizard_tower/level_2.webp"
        )
        assert catalog.sprite_relpath("super_wizard_tower", 1) == (
            "super_wizard_tower/level_1.webp"
        )


class TestAddedDefenses:
    """Archer merge, bomb tower, firespitter, spell tower variants."""

    def test_th15_has_regular_cannon_and_archer_not_merged(self) -> None:
        catalog = _fake_catalog()
        placements = generate_random_layout(
            random.Random(1), town_hall_level=15, catalog=catalog
        )
        types = {p.building_type for p in placements}
        assert "canon" in types
        assert "archertower" in types
        assert "ricochet_cannon" not in types
        assert "multi-archer_tower" not in types
        archers = [p for p in placements if p.building_type == "archertower"]
        assert {p.level for p in archers} == {21}
        assert catalog.sprite_relpath("archertower", 21) == "archer_tower/level_21.webp"

    def test_th16_has_remaining_regulars_plus_merged(self) -> None:
        catalog = _fake_catalog()
        expected = {16: 2, 17: 3, 18: 4}
        remaining_archers = {16: 4, 17: 2, 18: 2}
        remaining_cannons = {16: 3, 17: 0, 18: 0}
        for th_level, merged_level in expected.items():
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            types = {p.building_type for p in placements}
            assert "ricochet_cannon" in types
            assert "multi-archer_tower" in types
            archers = [p for p in placements if p.building_type == "archertower"]
            cannons = [p for p in placements if p.building_type == "canon"]
            assert len(archers) == remaining_archers[th_level]
            assert len(cannons) == remaining_cannons[th_level]
            merged = [p for p in placements if p.building_type == "multi-archer_tower"]
            assert len(merged) == WIKI_COUNT_BY_TH["multi-archer_tower"][th_level]
            assert {p.level for p in merged} == set(
                catalog.sprite_levels_for_th("multi-archer_tower", th_level)
            )
            assert catalog.sprite_relpath("multi-archer_tower", merged_level) == (
                f"multi-archer_tower/level_{merged_level}.webp"
            )

    def test_th18_has_super_wizard_ricochet_multi_archer(self) -> None:
        catalog = _fake_catalog()
        placements = generate_random_layout(
            random.Random(18), town_hall_level=18, catalog=catalog
        )
        types = {p.building_type for p in placements}
        assert "super_wizard_tower" in types
        assert "ricochet_cannon" in types
        assert "multi-archer_tower" in types
        assert "wizztower" in types
        assert "canon" not in types
        assert "archertower" in types
        assert len([p for p in placements if p.building_type == "wizztower"]) == 2
        assert len([p for p in placements if p.building_type == "super_wizard_tower"]) == 2

    def test_bomb_tower_visual_tier_th15_to_18(self) -> None:
        catalog = _fake_catalog()
        expected = {15: 10, 16: 11, 17: 12, 18: 13}
        for th_level, bomb_level in expected.items():
            assert catalog.resolve_for_th("bombtower", th_level) == (
                "bombtower",
                bomb_level,
            )
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            bombs = [p for p in placements if p.building_type == "bombtower"]
            assert bombs
            assert {p.level for p in bombs} == {bomb_level}
            assert catalog.sprite_relpath("bombtower", bomb_level) == (
                f"bomb_tower/level_{bomb_level}.webp"
            )

    def test_firespitter_only_from_th17(self) -> None:
        catalog = _fake_catalog()
        for th_level in (15, 16):
            assert catalog.resolve_for_th("firespitter", th_level) is None
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            assert not any(p.building_type == "firespitter" for p in placements)
        expected = {17: 2, 18: 3}
        for th_level, spit_level in expected.items():
            assert catalog.resolve_for_th("firespitter", th_level) == (
                "firespitter",
                spit_level,
            )
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            spitters = [p for p in placements if p.building_type == "firespitter"]
            assert spitters
            assert {p.level for p in spitters} == set(
                catalog.sprite_levels_for_th("firespitter", th_level)
            )
            assert catalog.sprite_relpath("firespitter", spit_level) == (
                f"firespitter/level_{spit_level}.webp"
            )

    def test_spell_towers_two_per_layout_th15_through_18(self) -> None:
        catalog = _fake_catalog()
        seen: set[str] = set()
        for th_level in (15, 16, 17, 18):
            assert catalog.resolve_for_th("spelltower", th_level) is not None
            placements = generate_random_layout(
                random.Random(th_level),
                town_hall_level=th_level,
                catalog=catalog,
                variant_cycle=th_level,
            )
            towers = [p for p in placements if p.building_type == "spelltower"]
            assert len(towers) == 2
            files = {
                catalog.sprite_relpath(p.building_type, p.level) for p in towers
            }
            assert files <= set(SPELL_TOWER_VARIANT_FILES)
            seen.update(files)
        assert seen == set(SPELL_TOWER_VARIANT_FILES)

    def test_th16_emits_spell_tower_and_eagle(self) -> None:
        catalog = _fake_catalog()
        assert catalog.resolve_for_th("spelltower", 16) is not None
        placements = generate_random_layout(
            random.Random(16), town_hall_level=16, catalog=catalog
        )
        assert any(p.building_type == "spelltower" for p in placements)
        assert any(p.building_type == "eagle" for p in placements)

    def test_wiki_counts_exact_per_th(self) -> None:
        catalog = _fake_catalog()
        occupancy_ok = {
            "goldmine",
            "elixircollector",
            "darkelixirdrill",
            "armycamp",
            "barracks",
            "darkbarracks",
            "laboratory",
            "spellfactory",
            "darkspellfactory",
            "workshop",
            "pethouse",
            "blacksmith",
            "herohall",
            "goldstorage",
            "elixirstorage",
            "darkelixirstorage",
            "mortar",
            "inferno",
            "xbow",
            "scattershot",
            "ad",
            "airsweeper",
        }
        for th_level in (15, 16, 17, 18):
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            by_type: dict[str, int] = {}
            for placement in placements:
                if placement.building_type == "wall":
                    continue
                by_type[placement.building_type] = by_type.get(placement.building_type, 0) + 1
            for name, expected in WIKI_COUNT_BY_TH.items():
                want = expected[th_level]
                got = by_type.get(name, 0)
                if name in occupancy_ok:
                    assert got <= want, f"TH{th_level} {name}: {got} > {want}"
                    continue
                assert got == want, f"TH{th_level} {name}: {got} != {want}"

    def test_th15_places_goldmine_collectors_drill_camps(self) -> None:
        catalog = _fake_catalog()
        placements = generate_random_layout(
            random.Random(15), town_hall_level=15, catalog=catalog
        )
        by_type: dict[str, int] = {}
        for placement in placements:
            if placement.building_type == "wall":
                continue
            by_type[placement.building_type] = by_type.get(placement.building_type, 0) + 1
        assert by_type.get("goldmine", 0) >= 1
        assert by_type.get("elixircollector", 0) >= 1
        assert by_type.get("darkelixirdrill", 0) >= 1
        assert by_type["goldmine"] <= WIKI_COUNT_BY_TH["goldmine"][15]
        assert by_type["elixircollector"] <= WIKI_COUNT_BY_TH["elixircollector"][15]
        assert by_type["darkelixirdrill"] <= WIKI_COUNT_BY_TH["darkelixirdrill"][15]
        assert by_type.get("armycamp", 0) <= WIKI_COUNT_BY_TH["armycamp"][15]

    def test_th15_to_th18_place_four_army_camps(self) -> None:
        catalog = _fake_catalog()
        assert occupancy_tiles("armycamp") == COC_TILE_FOOTPRINTS["armycamp"] == 5
        assert TILE_FOOTPRINTS["armycamp"] == 5
        for th_level in (15, 16, 17, 18):
            for seed in (th_level, th_level + 77, 0):
                placements = generate_random_layout(
                    random.Random(seed), town_hall_level=th_level, catalog=catalog
                )
                by_type: dict[str, int] = {}
                for placement in placements:
                    if placement.building_type == "wall":
                        continue
                    by_type[placement.building_type] = (
                        by_type.get(placement.building_type, 0) + 1
                    )
                camps = by_type.get("armycamp", 0)
                mines = by_type.get("goldmine", 0)
                collectors = by_type.get("elixircollector", 0)
                drills = by_type.get("darkelixirdrill", 0)
                want_camps = WIKI_COUNT_BY_TH["armycamp"][th_level]
                assert camps == want_camps, (
                    f"TH{th_level} seed={seed} armycamp {camps}/{want_camps}"
                )
                assert mines == WIKI_COUNT_BY_TH["goldmine"][th_level], (
                    f"TH{th_level} seed={seed} goldmine {mines}/7"
                )
                assert collectors == WIKI_COUNT_BY_TH["elixircollector"][th_level]
                assert drills == WIKI_COUNT_BY_TH["darkelixirdrill"][th_level]
                assert by_type.get("barracks", 0) == 1
                assert by_type.get("laboratory", 0) == 1
                assert by_type.get("herohall", 0) == 1

    def test_non_wall_buildings_keep_one_tile_gap(self) -> None:
        catalog = _fake_catalog()
        placements = generate_random_layout(
            random.Random(15), town_hall_level=15, catalog=catalog
        )
        occupied: dict[tuple[int, int], str] = {}
        for placement in placements:
            if placement.building_type == "wall":
                continue
            if placement.building_type in RESOURCE_ARMY_TYPES:
                continue
            size = catalog.occupancy_size(placement.building_type, placement.level)
            for cell in occupied_cells(placement.x, placement.y, size):
                occupied[cell] = placement.building_type
        for placement in placements:
            if placement.building_type == "wall":
                continue
            if placement.building_type in RESOURCE_ARMY_TYPES:
                continue
            size = catalog.occupancy_size(placement.building_type, placement.level)
            dilated = occupied_cells(
                placement.x - 1,
                placement.y - 1,
                size + 2,
            )
            own = occupied_cells(placement.x, placement.y, size)
            for cell in dilated - own:
                other = occupied.get(cell)
                assert other is None, f"gap missing at {cell} vs {other}"

    def test_sourced_gap_defenses_by_th(self) -> None:
        catalog = _fake_catalog()
        th15 = generate_random_layout(random.Random(15), town_hall_level=15, catalog=catalog)
        types15 = {p.building_type for p in th15}
        assert "monolith" in types15
        assert "tesla" in types15
        assert catalog.resolve_for_th("builderhut", 15) is not None
        assert "multi-gear_tower" not in types15
        assert "revenge_tower" not in types15
        assert catalog.resolve_for_th("monolith", 15) == ("monolith", 2)
        th17 = generate_random_layout(random.Random(17), town_hall_level=17, catalog=catalog)
        types17 = {p.building_type for p in th17}
        assert "multi-gear_tower" in types17
        assert "revenge_tower" not in types17
        th18 = generate_random_layout(random.Random(18), town_hall_level=18, catalog=catalog)
        types18 = {p.building_type for p in th18}
        assert "revenge_tower" in types18
        assert "multi-gear_tower" in types18
        assert "monolith" in types18

    def test_eagle_only_through_th16(self) -> None:
        catalog = _fake_catalog()
        for th_level in (15, 16):
            assert catalog.resolve_for_th("eagle", th_level) is not None
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            assert any(p.building_type == "eagle" for p in placements)
            assert not any(p.building_type == "firespitter" for p in placements)
        for th_level in (17, 18):
            assert catalog.resolve_for_th("eagle", th_level) is None
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            assert not any(p.building_type == "eagle" for p in placements)
            assert any(p.building_type == "firespitter" for p in placements)

    def test_eagle_sprite_matches_th_not_th14_leftover(self) -> None:
        catalog = _fake_catalog()
        assert catalog.resolve_for_th("eagle", 15) == ("eagle", 6)
        assert catalog.resolve_for_th("eagle", 16) == ("eagle", 7)
        assert catalog.sprite_relpath("eagle", 6) == "eagle_artillery/level_6.webp"
        assert catalog.sprite_relpath("eagle", 7) == "eagle_artillery/level_7.webp"
        for th_level, eagle_level in ((15, 6), (16, 7)):
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            eagles = [p for p in placements if p.building_type == "eagle"]
            assert eagles
            assert {p.level for p in eagles} == {eagle_level}

    def test_th18_never_emits_eagle(self) -> None:
        catalog = _fake_catalog()
        for seed in range(8):
            placements = generate_random_layout(
                random.Random(seed), town_hall_level=18, catalog=catalog
            )
            assert not any(p.building_type == "eagle" for p in placements)

    def test_walls_scale_with_th_and_do_not_overlap_buildings(self) -> None:
        catalog = _fake_catalog()
        expected = {18: 19, 17: 18, 16: 17, 15: 16}
        for th_level, wall_level in expected.items():
            assert catalog.sprite_level("wall", th_level) == wall_level
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            walls = [p for p in placements if p.building_type == "wall"]
            buildings = [p for p in placements if p.building_type != "wall"]
            assert len(walls) >= MIN_WALL_SEGMENTS
            assert {p.level for p in walls} == {wall_level}
            assert catalog.sprite_relpath("wall", wall_level) == (
                f"wall/level_{wall_level}.webp"
            )
            assert all(catalog.occupancy_size("wall", p.level) == 1 for p in walls)
            _assert_non_overlapping_in_bounds(placements, catalog)
            occupied_buildings: set[tuple[int, int]] = set()
            for placement in buildings:
                size = catalog.occupancy_size(placement.building_type, placement.level)
                occupied_buildings.update(
                    occupied_cells(placement.x, placement.y, size)
                )
            for wall in walls:
                assert (wall.x, wall.y) not in occupied_buildings

    def test_multi_archer_footprint_matches_coc_editor(self) -> None:
        assert occupancy_tiles("archertower") == 3
        assert occupancy_tiles("multi-archer_tower") == 3
        assert occupancy_tiles("bombtower") == 3
        assert occupancy_tiles("spelltower") == 3
        assert occupancy_tiles("firespitter") == 3
        assert occupancy_tiles("wall") == 1
        assert occupancy_tiles("wall", 72, 70) == 1
        assert occupancy_tiles("town_hall") == 4
        assert occupancy_tiles("super_wizard_tower") == 4


@pytest.mark.skipif(
    not IsometricRenderer.sprites_available(),
    reason="ClashKing sprites not downloaded — run download_clashking_sprites.sh",
)
class TestTh18EraPreviews:
    def test_writes_four_named_preview_pngs(self, tmp_path: Path) -> None:
        reports = generate_th18era_previews(output_dir=tmp_path, seed=1)
        names = {
            "preview_th18era_th15.png",
            "preview_th18era_th16.png",
            "preview_th18era_th17.png",
            "preview_th18era_th18.png",
        }
        written = {p.name for p in tmp_path.glob("*.png")}
        skipped = {r["town_hall_level"] for r in reports if r.get("skipped")}
        expected_written = {
            f"preview_th18era_th{th}.png" for th in (15, 16, 17, 18) if th not in skipped
        }
        assert written == expected_written
        assert written <= names
        assert len(reports) == 4
        generated = {r["town_hall_level"] for r in reports if not r.get("skipped")}
        assert generated | skipped == {15, 16, 17, 18}
        catalog = SpriteLevelCatalog.load()
        expected_cannon = {
            15: ("canon", 21, "cannon/level_21.webp"),
            16: ("ricochet_cannon", 2, "ricochet_cannon/level_2.webp"),
            17: ("ricochet_cannon", 3, "ricochet_cannon/level_3.webp"),
            18: ("ricochet_cannon", 4, "ricochet_cannon/level_4.webp"),
        }
        expected_wizard = {
            15: ("wizztower", 15, "wizard_tower/level_15.webp"),
            16: ("wizztower", 16, "wizard_tower/level_16.webp"),
            17: ("wizztower", 17, "wizard_tower/level_17.webp"),
            18: ("super_wizard_tower", 2, "super_wizard_tower/level_2.webp"),
        }
        for report in reports:
            if report.get("skipped"):
                continue
            th = report["town_hall_level"]
            levels = report["sprite_levels"]
            cannon_type, cannon_lv, cannon_sprite = expected_cannon[th]
            wizard_type, wizard_lv, wizard_sprite = expected_wizard[th]
            assert cannon_type in levels
            used_cannon = set(levels[cannon_type].get("levels") or [levels[cannon_type]["level"]])
            assert used_cannon == set(catalog.sprite_levels_for_th(cannon_type, th))
            assert catalog.sprite_relpath(cannon_type, cannon_lv) == cannon_sprite
            assert wizard_type in levels
            used_wizard = set(levels[wizard_type].get("levels") or [levels[wizard_type]["level"]])
            assert used_wizard == set(catalog.sprite_levels_for_th(wizard_type, th))
            assert catalog.sprite_relpath(wizard_type, wizard_lv) == wizard_sprite
            if th >= 16:
                assert "ricochet_cannon" in levels
                assert "multi-archer_tower" in levels
            if th == 15:
                assert "archertower" in levels
                assert levels["archertower"]["count"] == 8
                assert levels["canon"]["count"] == 7
                assert "multi-archer_tower" not in levels
                assert "ricochet_cannon" not in levels
                assert "eagle" in levels
                assert "firespitter" not in levels
                assert "spelltower" in levels
                assert levels["spelltower"]["count"] == 2
                assert "monolith" in levels
            if th == 16:
                assert "eagle" in levels
                assert "firespitter" not in levels
                assert "spelltower" in levels
                assert levels["spelltower"]["count"] == 2
                assert "canon" in levels
                assert levels["canon"]["count"] == 3
                assert "archertower" in levels
            if th >= 17:
                assert "eagle" not in levels
                assert "firespitter" in levels
                assert "multi-gear_tower" in levels
                assert "spelltower" in levels
                assert levels["spelltower"]["count"] == 2
            if th == 18:
                assert "wizztower" in levels
                assert levels["wizztower"]["count"] == 2
                assert "revenge_tower" in levels


@pytest.mark.skipif(
    not IsometricRenderer.sprites_available(),
    reason="ClashKing sprites not downloaded — run download_clashking_sprites.sh",
)
class TestSceneryPreviews:
    def test_war_preview_is_th18_and_labeled_files_match(self, tmp_path: Path) -> None:
        from renderer.photo_background import scenery_path_by_name

        if scenery_path_by_name("clan_war.png") is None:
            pytest.skip("clan_war.png scenery missing")
        reports = generate_scenery_previews(output_dir=tmp_path, seed=42)
        by_file = {Path(r["file"]).name: r for r in reports if r.get("file")}
        assert "preview_bg_war.png" in by_file
        war = by_file["preview_bg_war.png"]
        assert war["town_hall_level"] == 18
        levels = war["sprite_levels"]
        assert levels["town_hall"]["sprite"] == "town_hall/level_18.webp"
        assert "eagle" not in levels
        assert "firespitter" in levels
        assert "ricochet_cannon" in levels
        assert "multi-archer_tower" in levels
        assert "super_wizard_tower" in levels
        assert "spelltower" in levels
        assert levels["spelltower"]["count"] == 2
        assert "revenge_tower" in levels
        assert "monolith" in levels
        assert "wall" in levels
        assert levels["wall"]["count"] >= MIN_WALL_SEGMENTS
        assert "wizztower" in levels
        assert levels["wizztower"]["count"] == 2

        if "preview_bg_th16.png" in by_file:
            th16 = by_file["preview_bg_th16.png"]["sprite_levels"]
            assert "spelltower" in th16
            assert th16["spelltower"]["count"] == 2
            assert "eagle" in th16
            assert th16["eagle"]["sprite"] == "eagle_artillery/level_7.webp"
            assert "firespitter" not in th16
            assert "canon" in th16
            assert th16["canon"]["count"] == 3
            assert set(th16["canon"].get("levels") or [th16["canon"]["level"]]) == {21}
            assert th16["ricochet_cannon"]["count"] == 2
            assert set(th16["ricochet_cannon"].get("levels") or []) == {1, 2}

        if "preview_bg_th15.png" in by_file:
            th15 = by_file["preview_bg_th15.png"]["sprite_levels"]
            assert th15["town_hall"]["sprite"] == "town_hall/level_15.webp"
            assert "eagle" in th15
            assert th15["eagle"]["sprite"] == "eagle_artillery/level_6.webp"
            assert "spelltower" in th15
            assert th15["spelltower"]["count"] == 2
            assert "firespitter" not in th15
            assert "ricochet_cannon" not in th15
            assert "monolith" in th15
            assert set(th15["canon"].get("levels") or [th15["canon"]["level"]]) == {21}
            assert th15["canon"]["sprite"] == "cannon/level_21.webp"
            assert set(th15["archertower"].get("levels") or [th15["archertower"]["level"]]) == {21}


class TestWallYoloSkip:
    def test_walls_render_without_yolo_labels(self, tmp_path: Path) -> None:
        if not IsometricRenderer.sprites_available():
            pytest.skip("ClashKing sprites not downloaded")
        from link_decoder.schema import BuildingPlacement

        renderer = IsometricRenderer(use_placeholders=True, village_background=False)
        placements = [
            BuildingPlacement("town_hall", level=18, x=20, y=20),
            BuildingPlacement("wall", level=19, x=10, y=10),
            BuildingPlacement("wall", level=19, x=11, y=10),
        ]
        result = renderer.render(placements, seed=0)
        assert result.rendered_count >= 1
        assert all(label.class_name != "wall" for label in result.labels)


class TestRelabelSyntheticTownHalls:
    def test_rewrites_th13_hall_id_from_folder_and_keeps_geometry(
        self, tmp_path: Path
    ) -> None:
        th18 = tmp_path / "th18"
        th18.mkdir()
        (th18 / "synthetic_0003.png").write_bytes(b"fake")
        original = "12 0.438676 0.487832 0.062304 0.130531\n23 0.5 0.5 0.1 0.1\n"
        (th18 / "synthetic_0003.txt").write_text(original, encoding="utf-8")
        th15 = tmp_path / "th15"
        th15.mkdir()
        (th15 / "synthetic_0000.png").write_bytes(b"fake")
        (th15 / "synthetic_0000.txt").write_text(
            "12 0.439067 0.484882 0.059953 0.134956\n4 0.6 0.6 0.05 0.05\n",
            encoding="utf-8",
        )

        summary = relabel_synthetic_town_halls(tmp_path)
        assert summary["files_changed"] == 2
        assert summary["halls_relabeled"] == 2

        th18_lines = (th18 / "synthetic_0003.txt").read_text(encoding="utf-8").splitlines()
        assert th18_lines[0] == "31 0.438676 0.487832 0.062304 0.130531"
        assert th18_lines[1] == "23 0.5 0.5 0.1 0.1"
        th15_lines = (th15 / "synthetic_0000.txt").read_text(encoding="utf-8").splitlines()
        assert th15_lines[0] == "28 0.439067 0.484882 0.059953 0.134956"
        assert th15_lines[1] == "4 0.6 0.6 0.05 0.05"

        again = relabel_synthetic_town_halls(tmp_path)
        assert again["halls_relabeled"] == 0
