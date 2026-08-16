"""Tests for bulk synthetic YOLO generation from the isometric renderer."""

from __future__ import annotations

import random
from pathlib import Path

from dataset.generate_synthetic import (
    SYNTHETIC_BUILDING_TYPES,
    TILE_FOOTPRINTS,
    generate_random_layout,
    generate_synthetic_dataset,
)
from renderer.isometric_renderer import GRID_SIZE, YOLO_CLASS_NAMES


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
