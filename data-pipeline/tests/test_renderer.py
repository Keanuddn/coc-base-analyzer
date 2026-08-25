"""Smoke tests for Phase 1c isometric renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from link_decoder.schema import BuildingPlacement
from renderer.domain_randomization import DomainRandomizationConfig
from renderer.isometric_renderer import IsometricRenderer, YOLO_CLASS_NAMES

SPRITES_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "renderer"
    / "sprites"
    / "clashking"
    / "home-village"
)

pytestmark = pytest.mark.skipif(
    not IsometricRenderer.sprites_available(SPRITES_ROOT),
    reason="ClashKing sprites not downloaded — run download_clashking_sprites.sh",
)


@pytest.fixture
def renderer() -> IsometricRenderer:
    return IsometricRenderer(sprites_root=SPRITES_ROOT, use_placeholders=False)


@pytest.fixture
def sample_placements() -> list[BuildingPlacement]:
    return [
        BuildingPlacement("canon", level=10, x=20, y=22),
        BuildingPlacement("mortar", level=10, x=24, y=22),
        BuildingPlacement("eagle", level=5, x=22, y=18),
        BuildingPlacement("xbow", level=8, x=18, y=24),
        BuildingPlacement("town_hall", level=13, x=22, y=22),
    ]


class TestIsometricRenderer:
    def test_sprites_present(self) -> None:
        count = IsometricRenderer.count_sprites(SPRITES_ROOT)
        assert count >= 400

    def test_render_produces_image(self, renderer: IsometricRenderer, sample_placements: list[BuildingPlacement]) -> None:
        result = renderer.render(sample_placements, seed=0)
        assert result.rendered_count == len(sample_placements)
        assert result.skipped_count == 0
        assert result.image.size[0] >= 200
        assert result.image.size[1] >= 200
        assert len(result.labels) >= 4  # th13 + defenses with YOLO ids

    def test_render_to_files(self, renderer: IsometricRenderer, sample_placements: list[BuildingPlacement], tmp_path: Path) -> None:
        out = tmp_path / "test_base.png"
        result = renderer.render_to_files(sample_placements, out, seed=1)
        assert out.is_file()
        assert result.label_path is not None
        assert result.label_path.is_file()
        label_lines = result.label_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(label_lines) == len(result.labels)
        for line in label_lines:
            parts = line.split()
            assert len(parts) == 5
            class_id, cx, cy, w, h = parts
            assert 0 <= int(class_id) < len(YOLO_CLASS_NAMES)
            for val in (cx, cy, w, h):
                f = float(val)
                assert 0.0 <= f <= 1.0

    def test_domain_randomization_does_not_crash(
        self,
        renderer: IsometricRenderer,
        sample_placements: list[BuildingPlacement],
    ) -> None:
        cfg = DomainRandomizationConfig(seed=99, brightness_jitter=0.2, position_jitter_px=5)
        result = renderer.render(sample_placements, domain_randomization=cfg, seed=99)
        assert result.rendered_count == len(sample_placements)

    def test_village_background_is_not_solid_green(
        self,
        renderer: IsometricRenderer,
        sample_placements: list[BuildingPlacement],
    ) -> None:
        cfg = DomainRandomizationConfig(
            brightness_jitter=0,
            contrast_jitter=0,
            position_jitter_px=0,
            background_color_jitter=0,
            background_hue_shift=0,
            background_brightness_jitter=0,
            overlay_opacity=0,
            seed=0,
        )
        result = renderer.render(sample_placements, domain_randomization=cfg, seed=0)
        colors = result.image.convert("RGB").getcolors(maxcolors=500_000)
        assert colors is None or len(colors) > 80

    def test_flat_background_corners_are_uniform(
        self,
        sample_placements: list[BuildingPlacement],
    ) -> None:
        renderer = IsometricRenderer(
            sprites_root=SPRITES_ROOT,
            use_placeholders=False,
            village_background=False,
            use_photo_backgrounds=False,
        )
        cfg = DomainRandomizationConfig(
            brightness_jitter=0,
            contrast_jitter=0,
            position_jitter_px=0,
            background_color_jitter=0,
            background_hue_shift=0,
            background_brightness_jitter=0,
            overlay_opacity=0,
            seed=0,
        )
        result = renderer.render(sample_placements, domain_randomization=cfg, seed=0)
        rgb = result.image.convert("RGB")
        corners = [rgb.getpixel((0, 0)), rgb.getpixel((rgb.size[0] - 1, 0))]
        assert corners[0] == corners[1]

    def test_labels_cover_buildings_only(
        self,
        renderer: IsometricRenderer,
        sample_placements: list[BuildingPlacement],
    ) -> None:
        result = renderer.render(sample_placements, seed=0)
        assert len(result.labels) == result.rendered_count
        for label in result.labels:
            assert 0.0 <= label.cx <= 1.0
            assert 0.0 <= label.cy <= 1.0
            assert 0.0 < label.w <= 1.0
            assert 0.0 < label.h <= 1.0

    def test_missing_sprite_skipped_without_placeholder(self, renderer: IsometricRenderer) -> None:
        placements = [BuildingPlacement("nonexistent_building_xyz", level=1, x=10, y=10)]
        result = renderer.render(placements, seed=0)
        assert result.rendered_count == 0
        assert result.skipped_count == 1

    def test_keremberke_ids_frozen_and_new_classes_appended(self) -> None:
        assert YOLO_CLASS_NAMES[:16] == (
            "ad",
            "airsweeper",
            "bombtower",
            "canon",
            "clancastle",
            "eagle",
            "inferno",
            "kingpad",
            "mortar",
            "queenpad",
            "rcpad",
            "scattershot",
            "th13",
            "wardenpad",
            "wizztower",
            "xbow",
        )
        assert YOLO_CLASS_NAMES[16:] == (
            "archertower",
            "tesla",
            "monolith",
            "spelltower",
            "ricochetcannon",
            "multiarchertower",
            "firespitter",
            "multigeartower",
            "revengetower",
            "superwizztower",
            "builderhut",
            "th14",
            "th15",
            "th16",
            "th17",
            "th18",
            "goldstorage",
            "elixirstorage",
            "darkelixirstorage",
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
        )
        assert YOLO_CLASS_NAMES[12] == "th13"
        assert YOLO_CLASS_NAMES[26] == "builderhut"
        assert YOLO_CLASS_NAMES[27] == "th14"
        assert YOLO_CLASS_NAMES[31] == "th18"
        assert YOLO_CLASS_NAMES[32] == "goldstorage"
        assert YOLO_CLASS_NAMES[33] == "elixirstorage"
        assert YOLO_CLASS_NAMES[34] == "darkelixirstorage"
        assert YOLO_CLASS_NAMES[35] == "goldmine"
        assert YOLO_CLASS_NAMES[36] == "elixircollector"
        assert YOLO_CLASS_NAMES[37] == "darkelixirdrill"
        assert YOLO_CLASS_NAMES[38] == "armycamp"
        assert YOLO_CLASS_NAMES[39] == "barracks"
        assert YOLO_CLASS_NAMES[40] == "darkbarracks"
        assert YOLO_CLASS_NAMES[41] == "laboratory"
        assert YOLO_CLASS_NAMES[42] == "spellfactory"
        assert YOLO_CLASS_NAMES[43] == "darkspellfactory"
        assert YOLO_CLASS_NAMES[44] == "workshop"
        assert YOLO_CLASS_NAMES[45] == "pethouse"
        assert YOLO_CLASS_NAMES[46] == "blacksmith"
        assert YOLO_CLASS_NAMES[47] == "herohall"
        assert len(YOLO_CLASS_NAMES) == 48

    def test_th15_plus_defenses_get_dedicated_classes(
        self, renderer: IsometricRenderer
    ) -> None:
        placements = [
            BuildingPlacement("archertower", level=21, x=10, y=10),
            BuildingPlacement("tesla", level=15, x=14, y=10),
            BuildingPlacement("monolith", level=2, x=18, y=10),
            BuildingPlacement("spelltower", level=1, x=22, y=10),
            BuildingPlacement("ricochet_cannon", level=2, x=10, y=16),
            BuildingPlacement("multi-archer_tower", level=2, x=14, y=16),
            BuildingPlacement("firespitter", level=2, x=18, y=16),
            BuildingPlacement("multi-gear_tower", level=2, x=22, y=16),
            BuildingPlacement("revenge_tower", level=1, x=10, y=22),
            BuildingPlacement("super_wizard_tower", level=2, x=16, y=22),
            BuildingPlacement("builderhut", level=5, x=22, y=22),
            BuildingPlacement("wall", level=19, x=8, y=8),
        ]
        result = renderer.render(placements, seed=0)
        by_name = {label.class_name: label.class_id for label in result.labels}
        expected = {
            "archertower": 16,
            "tesla": 17,
            "monolith": 18,
            "spelltower": 19,
            "ricochetcannon": 20,
            "multiarchertower": 21,
            "firespitter": 22,
            "multigeartower": 23,
            "revengetower": 24,
            "superwizztower": 25,
            "builderhut": 26,
        }
        for name, class_id in expected.items():
            assert by_name[name] == class_id, name
        assert "canon" not in by_name
        assert "wizztower" not in by_name
        assert "wall" not in by_name
        assert all(label.class_name != "wall" for label in result.labels)

    def test_ricochet_and_super_wizard_use_dedicated_classes(
        self, renderer: IsometricRenderer
    ) -> None:
        placements = [
            BuildingPlacement("ricochet_cannon", level=4, x=18, y=20),
            BuildingPlacement("super_wizard_tower", level=2, x=24, y=22),
        ]
        result = renderer.render(placements, seed=0)
        assert result.rendered_count == 2
        names = {label.class_name for label in result.labels}
        assert names == {"ricochetcannon", "superwizztower"}
        assert "canon" not in names
        assert "wizztower" not in names

    def test_town_hall_sprite_level_gets_matching_yolo_class(
        self, renderer: IsometricRenderer
    ) -> None:
        expected = {
            13: ("th13", 12),
            14: ("th14", 27),
            15: ("th15", 28),
            16: ("th16", 29),
            17: ("th17", 30),
            18: ("th18", 31),
        }
        for level, (name, class_id) in expected.items():
            result = renderer.render(
                [BuildingPlacement("town_hall", level=level, x=22, y=22)],
                seed=0,
            )
            assert result.rendered_count == 1, level
            assert result.labels[0].class_name == name, level
            assert result.labels[0].class_id == class_id, level
