"""Tests for procedural village grass (no ClashKing scenery sprites required)."""

from __future__ import annotations

import random

from PIL import Image

from renderer.domain_randomization import DomainRandomizationConfig, apply_domain_randomization
from renderer.village_background import (
    VillagePalette,
    paint_village_background,
    randomize_village_palette,
    shift_hue,
    village_canvas_size,
    village_diamond_vertices,
    village_origin,
)


def _painted(seed: int = 0, *, draw_trees: bool = True) -> Image.Image:
    canvas = Image.new("RGBA", village_canvas_size(), (0, 0, 0, 0))
    origin_x, origin_y = village_origin()
    paint_village_background(
        canvas,
        origin_x=origin_x,
        origin_y=origin_y,
        rng=random.Random(seed),
        draw_trees=draw_trees,
    )
    return canvas


class TestVillageBackground:
    def test_not_a_solid_fill(self) -> None:
        rgb = _painted(seed=1).convert("RGB")
        colors = rgb.getcolors(maxcolors=500_000)
        assert colors is None or len(colors) > 40

    def test_playable_diamond_is_lighter_than_forest_rim(self) -> None:
        rgb = _painted(seed=2, draw_trees=False).convert("RGB")
        origin_x, origin_y = village_origin()
        diamond = village_diamond_vertices(origin_x, origin_y)
        cx = int(sum(p[0] for p in diamond) / 4)
        cy = int(sum(p[1] for p in diamond) / 4)
        grass = rgb.getpixel((cx, cy))
        forest = rgb.getpixel((4, 4))
        assert grass[1] > forest[1]

    def test_palette_hue_shift_changes_colors(self) -> None:
        base = VillagePalette()
        shifted = shift_hue(base.grass_light, 25)
        assert shifted != base.grass_light

    def test_randomize_palette_is_seeded(self) -> None:
        a = randomize_village_palette(random.Random(7))
        b = randomize_village_palette(random.Random(7))
        c = randomize_village_palette(random.Random(8))
        assert a == b
        assert a != c

    def test_overlay_does_not_crash(self) -> None:
        img = _painted(seed=3)
        cfg = DomainRandomizationConfig(
            brightness_jitter=0.05,
            contrast_jitter=0.05,
            overlay_opacity=0.12,
            seed=3,
        )
        out = apply_domain_randomization(img, config=cfg, rng=random.Random(3))
        assert out.size == img.size
