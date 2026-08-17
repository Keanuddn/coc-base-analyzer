"""Tests for empty-village photo backgrounds and diamond alignment."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw

from renderer.photo_background import (
    BACKGROUNDS_DIR,
    align_scenery_to_village_grid,
    detect_playable_diamond,
    jitter_photo_brightness,
    list_scenery_backgrounds,
    scenery_path_by_name,
)
from renderer.village_background import village_canvas_size, village_diamond_vertices, village_origin


def _synthetic_village_photo(
    size: tuple[int, int] = (400, 260),
    *,
    fill: tuple[int, int, int] = (24, 48, 22),
    grass: tuple[int, int, int] = (150, 190, 70),
) -> Image.Image:
    """Light isometric diamond on a dark forest — stand-in for a CoC screenshot."""
    width, height = size
    img = Image.new("RGB", size, fill)
    draw = ImageDraw.Draw(img)
    cx, cy = width / 2, height / 2
    dw, dh = width * 0.70, height * 0.62
    diamond = [
        (cx, cy - dh / 2),
        (cx + dw / 2, cy),
        (cx, cy + dh / 2),
        (cx - dw / 2, cy),
    ]
    draw.polygon(diamond, fill=grass)
    return img


class TestListSceneryBackgrounds:
    def test_lists_pngs_not_readme(self) -> None:
        paths = list_scenery_backgrounds()
        names = {p.name for p in paths}
        assert "README.md" not in names
        if paths:
            assert all(p.suffix.lower() == ".png" for p in paths)
            assert "clan_war.png" in names

    def test_clan_war_lookup(self) -> None:
        if not (BACKGROUNDS_DIR / "clan_war.png").is_file():
            return
        path = scenery_path_by_name("clan_war.png")
        assert path is not None
        assert path.name == "clan_war.png"


class TestDetectPlayableDiamond:
    def test_finds_light_diamond_vertices(self) -> None:
        photo = _synthetic_village_photo()
        diamond = detect_playable_diamond(photo)
        width, height = photo.size
        assert diamond.left[0] < width * 0.30
        assert diamond.right[0] > width * 0.70
        assert diamond.top[1] < height * 0.30
        assert diamond.bottom[1] > height * 0.70
        assert diamond.right[0] - diamond.left[0] > width * 0.5

    def test_war_tan_diamond_is_detected(self) -> None:
        photo = _synthetic_village_photo(fill=(18, 12, 10), grass=(190, 165, 80))
        diamond = detect_playable_diamond(photo)
        assert diamond.right[0] - diamond.left[0] > photo.size[0] * 0.5


class TestAlignScenery:
    def test_warped_canvas_matches_village_size(self) -> None:
        photo = _synthetic_village_photo()
        aligned = align_scenery_to_village_grid(photo)
        assert aligned.size == village_canvas_size()
        assert aligned.mode == "RGBA"

    def test_diamond_center_stays_light_grass(self) -> None:
        photo = _synthetic_village_photo()
        origin_x, origin_y = village_origin()
        aligned = align_scenery_to_village_grid(photo, origin_x=origin_x, origin_y=origin_y)
        verts = village_diamond_vertices(origin_x, origin_y)
        cx = int(sum(p[0] for p in verts) / 4)
        cy = int(sum(p[1] for p in verts) / 4)
        pixel = aligned.convert("RGB").getpixel((cx, cy))
        # Grass is much greener/brighter than the forest fill.
        assert pixel[1] > 80
        assert pixel[1] >= pixel[2]

    def test_brightness_jitter_is_seeded(self) -> None:
        photo = _synthetic_village_photo().convert("RGBA")
        a = jitter_photo_brightness(photo, random.Random(3), amount=0.2)
        b = jitter_photo_brightness(photo, random.Random(3), amount=0.2)
        c = jitter_photo_brightness(photo, random.Random(9), amount=0.2)
        assert list(a.getdata()) == list(b.getdata())
        assert list(a.getdata()) != list(c.getdata())


class TestRendererPhotoBackground:
    def test_explicit_background_is_recorded(self, tmp_path: Path) -> None:
        from link_decoder.schema import BuildingPlacement
        from renderer.domain_randomization import DomainRandomizationConfig
        from renderer.isometric_renderer import IsometricRenderer

        photo = _synthetic_village_photo()
        path = tmp_path / "classic_grass.png"
        photo.save(path)

        renderer = IsometricRenderer(
            use_placeholders=True,
            village_background=True,
            use_photo_backgrounds=True,
            backgrounds_dir=tmp_path,
        )
        cfg = DomainRandomizationConfig(
            brightness_jitter=0,
            contrast_jitter=0,
            position_jitter_px=0,
            overlay_opacity=0,
            background_brightness_jitter=0,
            seed=0,
        )
        result = renderer.render(
            [BuildingPlacement("canon", level=1, x=20, y=20)],
            domain_randomization=cfg,
            seed=0,
            background_path=path,
        )
        assert result.background_path == path
        assert result.rendered_count == 1
        # Labels are buildings only — no extra class for scenery/UI.
        assert all(label.class_name == "canon" for label in result.labels)

    def test_flat_fallback_without_pngs(self, tmp_path: Path) -> None:
        from link_decoder.schema import BuildingPlacement
        from renderer.isometric_renderer import IsometricRenderer

        renderer = IsometricRenderer(
            use_placeholders=True,
            village_background=True,
            use_photo_backgrounds=True,
            backgrounds_dir=tmp_path,
        )
        result = renderer.render(
            [BuildingPlacement("canon", level=1, x=20, y=20)],
            seed=1,
        )
        assert result.background_path is None
        assert result.image.size[0] > 100
