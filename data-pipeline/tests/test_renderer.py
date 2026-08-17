"""Smoke tests for Phase 1c isometric renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from link_decoder.schema import BuildingPlacement
from renderer.domain_randomization import DomainRandomizationConfig
from renderer.isometric_renderer import IsometricRenderer

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
            assert 0 <= int(class_id) < 16
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

    def test_ricochet_and_super_wizard_label_as_pre_merge_classes(
        self, renderer: IsometricRenderer
    ) -> None:
        placements = [
            BuildingPlacement("ricochet_cannon", level=4, x=18, y=20),
            BuildingPlacement("super_wizard_tower", level=2, x=24, y=22),
        ]
        result = renderer.render(placements, seed=0)
        assert result.rendered_count == 2
        names = {label.class_name for label in result.labels}
        assert names == {"canon", "wizztower"}
        assert "ricochet_cannon" not in names
        assert "super_wizard_tower" not in names
