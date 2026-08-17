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
    generate_th_capped_previews,
    top_third_levels,
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
        "high_pool_size": 3,
        "leftover_pool_size": 3,
        "leftover_probability": 0.4,
        "leftover_buildings_max": 2,
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
    def test_cannon_high_pool_is_top_three_and_in_top_third(self) -> None:
        catalog = _fake_catalog()
        assert catalog.high_pool("canon") == [19, 20, 21]
        assert catalog.leftover_pool("canon") == [16, 17, 18]
        assert set(catalog.high_pool("canon")) <= set(top_third_levels(catalog.levels_for("canon")))
        assert min(catalog.leftover_pool("canon")) > 5

    def test_th16_sampled_levels_are_in_top_third_without_leftovers(self) -> None:
        catalog = _fake_catalog()
        for seed in range(30):
            placements = generate_random_layout(
                random.Random(seed),
                town_hall_level=16,
                catalog=catalog,
                leftover_probability=0.0,
            )
            th = next(p for p in placements if p.building_type == "town_hall")
            assert th.level == 16
            for placement in placements:
                if placement.building_type == "town_hall":
                    continue
                available = catalog.levels_for(placement.building_type)
                assert placement.level in catalog.high_pool(placement.building_type)
                assert placement.level in top_third_levels(available)

    def test_th16_cannon_mortar_never_level_1_to_5(self) -> None:
        catalog = _fake_catalog()
        for seed in range(40):
            placements = generate_random_layout(
                random.Random(seed),
                town_hall_level=16,
                catalog=catalog,
                leftover_probability=1.0,
            )
            for placement in placements:
                if placement.building_type not in _LOW_LEVEL_TYPES:
                    continue
                assert placement.level > 5, placement
                allowed = set(catalog.high_pool(placement.building_type)) | set(
                    catalog.leftover_pool(placement.building_type)
                )
                assert placement.level in allowed

    def test_leftover_count_is_at_most_two(self) -> None:
        catalog = _fake_catalog()
        placements = generate_random_layout(
            random.Random(0),
            town_hall_level=16,
            catalog=catalog,
            leftover_probability=1.0,
        )
        leftover_n = sum(
            1
            for p in placements
            if p.building_type != "town_hall" and p.level not in catalog.high_pool(p.building_type)
        )
        assert 1 <= leftover_n <= 2


@pytest.mark.skipif(
    not IsometricRenderer.sprites_available(),
    reason="ClashKing sprites not downloaded — run download_clashking_sprites.sh",
)
class TestThCappedPreviews:
    def test_writes_four_named_preview_pngs(self, tmp_path: Path) -> None:
        reports = generate_th_capped_previews(output_dir=tmp_path, seed=1)
        names = {
            "preview_th_capped_th15_a.png",
            "preview_th_capped_th15_b.png",
            "preview_th_capped_th16_a.png",
            "preview_th_capped_th16_b.png",
        }
        assert {p.name for p in tmp_path.glob("*.png")} == names
        assert len(reports) == 4
        assert {r["town_hall_level"] for r in reports} == {15, 16}
