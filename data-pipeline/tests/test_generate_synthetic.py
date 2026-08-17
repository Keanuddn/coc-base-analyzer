"""Tests for bulk synthetic YOLO generation from the isometric renderer."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from dataset.generate_synthetic import (
    SYNTHETIC_BUILDING_TYPES,
    TILE_FOOTPRINTS,
    SpriteLevelCatalog,
    generate_random_layout,
    generate_synthetic_dataset,
    generate_th_strict_previews,
    summarize_placement_levels,
)
from renderer.isometric_renderer import GRID_SIZE, IsometricRenderer, YOLO_CLASS_NAMES

_LOW_LEVEL_TYPES = ("canon", "mortar", "wizztower", "ad", "xbow", "bombtower")


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
        "ad": list(range(1, 17)),
        "bombtower": list(range(1, 14)),
        "airsweeper": list(range(1, 8)),
        "clancastle": list(range(1, 15)),
        "town_hall": list(range(1, 19)),
    }
    kwargs: dict[str, object] = {
        "levels_by_type": levels,
        "policy": "sprite-max",
        "not_official_coc_cap": True,
    }
    kwargs.update(overrides)
    return SpriteLevelCatalog(**kwargs)  # type: ignore[arg-type]


class TestGenerateRandomLayout:
    def test_includes_town_hall_and_only_allowed_types(self) -> None:
        placements = generate_random_layout(random.Random(0), town_hall_level=15)
        types = {p.building_type for p in placements}
        assert "town_hall" in types
        assert types <= set(SYNTHETIC_BUILDING_TYPES)
        assert all(p.building_type != "kingpad" for p in placements)
        th = next(p for p in placements if p.building_type == "town_hall")
        assert th.level == 15

    def test_th16_sets_town_hall_level(self) -> None:
        placements = generate_random_layout(random.Random(1), town_hall_level=16)
        th = next(p for p in placements if p.building_type == "town_hall")
        assert th.level == 16

    def test_buildings_do_not_overlap_on_grid(self) -> None:
        placements = generate_random_layout(random.Random(7), town_hall_level=16)
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
        a = generate_random_layout(random.Random(42), town_hall_level=15)
        b = generate_random_layout(random.Random(42), town_hall_level=15)
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
        assert "th15" in th_parts
        assert "th16" in th_parts


class TestSpriteMaxLevelPolicy:
    def test_th16_is_max_sprite_index_th15_is_max_minus_one(self) -> None:
        catalog = _fake_catalog()
        assert catalog.sprite_level("canon", 16) == 21
        assert catalog.sprite_level("canon", 15) == 20
        assert catalog.sprite_level("town_hall", 15) == 15
        assert catalog.sprite_level("town_hall", 16) == 16

    def test_single_file_building_uses_same_level_for_both_ths(self) -> None:
        catalog = _fake_catalog()
        catalog.levels_by_type["eagle"] = [7]
        assert catalog.sprite_level("eagle", 15) == 7
        assert catalog.sprite_level("eagle", 16) == 7

    def test_all_cannons_share_one_level_per_th_and_ths_differ(self) -> None:
        catalog = _fake_catalog()
        th15 = generate_random_layout(random.Random(0), town_hall_level=15, catalog=catalog)
        th16 = generate_random_layout(random.Random(1), town_hall_level=16, catalog=catalog)
        cannons15 = [p.level for p in th15 if p.building_type == "canon"]
        cannons16 = [p.level for p in th16 if p.building_type == "canon"]
        assert cannons15
        assert cannons16
        assert len(set(cannons15)) == 1
        assert len(set(cannons16)) == 1
        assert cannons15[0] == 20
        assert cannons16[0] == 21
        assert cannons15[0] != cannons16[0]

    def test_every_building_type_is_one_file_and_no_leftovers(self) -> None:
        catalog = _fake_catalog()
        for th, seed in ((15, 3), (16, 4)):
            placements = generate_random_layout(
                random.Random(seed), town_hall_level=th, catalog=catalog
            )
            by_type: dict[str, set[int]] = {}
            for placement in placements:
                by_type.setdefault(placement.building_type, set()).add(placement.level)
                assert placement.level == catalog.sprite_level(placement.building_type, th)
            assert all(len(levels) == 1 for levels in by_type.values())
            summary = summarize_placement_levels(placements, catalog)
            assert summary["leftovers"] == []

    def test_th16_cannon_mortar_never_level_1_to_5(self) -> None:
        catalog = _fake_catalog()
        for seed in range(40):
            placements = generate_random_layout(
                random.Random(seed),
                town_hall_level=16,
                catalog=catalog,
            )
            for placement in placements:
                if placement.building_type not in _LOW_LEVEL_TYPES:
                    continue
                assert placement.level > 5, placement
                assert placement.level == catalog.sprite_level(placement.building_type, 16)


@pytest.mark.skipif(
    not IsometricRenderer.sprites_available(),
    reason="ClashKing sprites not downloaded — run download_clashking_sprites.sh",
)
class TestThStrictPreviews:
    def test_writes_four_named_preview_pngs(self, tmp_path: Path) -> None:
        reports = generate_th_strict_previews(output_dir=tmp_path, seed=1)
        names = {
            "preview_th_strict_th15_a.png",
            "preview_th_strict_th15_b.png",
            "preview_th_strict_th16_a.png",
            "preview_th_strict_th16_b.png",
        }
        assert {p.name for p in tmp_path.glob("*.png")} == names
        assert len(reports) == 4
        assert {r["town_hall_level"] for r in reports} == {15, 16}
        for report in reports:
            assert report["leftovers"] == []
            th = report["town_hall_level"]
            assert report["sprite_level"]["town_hall"] == th
            for name, level in report["sprite_level"].items():
                assert set(report["sprite_levels"][name]) == {level}
