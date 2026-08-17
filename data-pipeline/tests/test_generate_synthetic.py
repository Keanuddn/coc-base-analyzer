"""Tests for bulk synthetic YOLO generation from the isometric renderer."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from dataset.generate_synthetic import (
    MERGED_PLACEMENT_TYPES,
    REQUESTED_TOWN_HALL_LEVELS,
    SYNTHETIC_BUILDING_TYPES,
    TILE_FOOTPRINTS,
    TOWN_HALL_LEVELS,
    SpriteLevelCatalog,
    generate_random_layout,
    generate_synthetic_dataset,
    generate_th18era_previews,
    visual_tier_level,
)
from renderer.isometric_renderer import GRID_SIZE, IsometricRenderer, YOLO_CLASS_NAMES

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
    },
    "identity": [
        "cannon",
        "ricochet_cannon",
        "super_wizard_tower",
        "town_hall",
        "wizard_tower",
    ],
    "town_hall": {"sprite_slug": "town_hall", "yolo_class": "th13"},
    "yolo_label_overrides": {
        "ricochet_cannon": "canon",
        "super_wizard_tower": "wizztower",
    },
    "era_merges": {
        "canon": {
            "regular_slug": "cannon",
            "max_regular_th": 15,
            "merged_slug": "ricochet_cannon",
            "merged_from_th": 16,
            "yolo_class": "canon",
            "count_range": [2, 3],
        },
        "wizztower": {
            "regular_slug": "wizard_tower",
            "max_regular_th": 17,
            "merged_slug": "super_wizard_tower",
            "merged_from_th": 18,
            "yolo_class": "wizztower",
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


class TestGenerateRandomLayout:
    def test_includes_town_hall_and_only_allowed_types(self) -> None:
        catalog = _fake_catalog()
        placements = generate_random_layout(
            random.Random(0), town_hall_level=15, catalog=catalog
        )
        types = {p.building_type for p in placements}
        assert "town_hall" in types
        assert types <= set(SYNTHETIC_BUILDING_TYPES) | MERGED_PLACEMENT_TYPES
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
        placements = generate_random_layout(
            random.Random(7), town_hall_level=16, catalog=_fake_catalog()
        )
        occupied: dict[tuple[int, int], str] = {}
        for placement in placements:
            size = TILE_FOOTPRINTS[placement.building_type]
            assert 0 <= placement.x < GRID_SIZE
            assert 0 <= placement.y < GRID_SIZE
            assert placement.x + size <= GRID_SIZE
            assert placement.y + size <= GRID_SIZE
            for dx in range(size):
                for dy in range(size):
                    cell = (placement.x + dx, placement.y + dy)
                    assert cell not in occupied, f"overlap at {cell}"
                    occupied[cell] = placement.building_type

    def test_seed_is_deterministic(self) -> None:
        catalog = _fake_catalog()
        a = generate_random_layout(random.Random(42), town_hall_level=15, catalog=catalog)
        b = generate_random_layout(random.Random(42), town_hall_level=15, catalog=catalog)
        assert [(p.building_type, p.x, p.y, p.level) for p in a] == [
            (p.building_type, p.x, p.y, p.level) for p in b
        ]


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

    def test_varies_th_level_in_output_paths(self, tmp_path: Path) -> None:
        generate_synthetic_dataset(count=4, output_dir=tmp_path, seed=3)
        pngs = list(tmp_path.rglob("*.png"))
        th_parts = {p.parent.name for p in pngs}
        assert th_parts == {"th15", "th16", "th17", "th18"}


class TestVisualTierProxy:
    def test_default_th_set_is_15_through_18(self) -> None:
        assert TOWN_HALL_LEVELS == (15, 16, 17, 18)
        assert REQUESTED_TOWN_HALL_LEVELS == (15, 16, 17, 18)

    def test_one_sprite_level_per_building_type_per_image(self) -> None:
        catalog = _fake_catalog()
        for th_level in (15, 16, 17, 18):
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            by_type: dict[str, set[int]] = {}
            for placement in placements:
                by_type.setdefault(placement.building_type, set()).add(placement.level)
            for building_type, levels in by_type.items():
                assert len(levels) == 1, f"TH{th_level} {building_type} mixed {levels}"

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

    def test_th16_plus_places_ricochet_not_regular_cannon(self) -> None:
        catalog = _fake_catalog()
        expected = {16: 2, 17: 3, 18: 4}
        for th_level, ricochet_level in expected.items():
            assert catalog.resolve_for_th("canon", th_level) == (
                "ricochet_cannon",
                ricochet_level,
            )
            placements = generate_random_layout(
                random.Random(th_level), town_hall_level=th_level, catalog=catalog
            )
            regular = [p for p in placements if p.building_type == "canon"]
            ricochets = [p for p in placements if p.building_type == "ricochet_cannon"]
            assert not regular
            assert ricochets
            assert 2 <= len(ricochets) <= 3
            assert {p.level for p in ricochets} == {ricochet_level}
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

    def test_th18_places_super_wizard_not_wizard_tower(self) -> None:
        catalog = _fake_catalog()
        assert catalog.resolve_for_th("wizztower", 18) == ("super_wizard_tower", 2)
        placements = generate_random_layout(
            random.Random(18), town_hall_level=18, catalog=catalog
        )
        assert not any(p.building_type == "wizztower" for p in placements)
        merged = [p for p in placements if p.building_type == "super_wizard_tower"]
        assert merged
        assert {p.level for p in merged} == {2}
        assert catalog.sprite_relpath("super_wizard_tower", 2) == (
            "super_wizard_tower/level_2.webp"
        )


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
            assert levels[cannon_type]["level"] == cannon_lv
            assert levels[cannon_type]["sprite"] == cannon_sprite
            assert wizard_type in levels
            assert levels[wizard_type]["level"] == wizard_lv
            assert levels[wizard_type]["sprite"] == wizard_sprite
            if th >= 16:
                assert "canon" not in levels
            if th == 18:
                assert "wizztower" not in levels
