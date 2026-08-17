"""Procedural CoC-like village grass (no ClashKing scenery sprites exist).

ClashKing's atlas is buildings-only (`home-village/{slug}/level_n.webp`). This
module paints a 44×44 isometric playable diamond with checkerboard grass, faint
grid lines, and a darker forest rim of simple ellipses — not Supercell art.
"""

from __future__ import annotations

import colorsys
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw

# Keep in sync with isometric_renderer (avoid circular import).
GRID_SIZE = 44
TILE_WIDTH = 44
TILE_HEIGHT = 22

# Playable square: two checker shades (in-game grass is a faint isometric checker).
# Forest rim is distinctly darker so the 44×44 village reads as a diamond.
DEFAULT_GRASS_LIGHT = (112, 168, 62)
DEFAULT_GRASS_DARK = (86, 142, 50)
DEFAULT_FOREST = (36, 72, 34)
DEFAULT_GRID = (58, 112, 40)
DEFAULT_TREE_CANOPY = (30, 68, 28)
DEFAULT_TREE_CANOPY_DARK = (20, 50, 20)
DEFAULT_TREE_TRUNK = (52, 38, 22)

FOREST_TILES = 7
SPRITE_TOP_PAD = 80


def _tile_to_screen(x: int, y: int, *, origin_x: float, origin_y: float) -> tuple[float, float]:
    screen_x = origin_x + (x - y) * (TILE_WIDTH / 2)
    screen_y = origin_y + (x + y) * (TILE_HEIGHT / 2)
    return screen_x, screen_y


@dataclass(frozen=True, slots=True)
class VillagePalette:
    grass_light: tuple[int, int, int] = DEFAULT_GRASS_LIGHT
    grass_dark: tuple[int, int, int] = DEFAULT_GRASS_DARK
    forest: tuple[int, int, int] = DEFAULT_FOREST
    grid: tuple[int, int, int] = DEFAULT_GRID
    tree_canopy: tuple[int, int, int] = DEFAULT_TREE_CANOPY
    tree_canopy_dark: tuple[int, int, int] = DEFAULT_TREE_CANOPY_DARK
    tree_trunk: tuple[int, int, int] = DEFAULT_TREE_TRUNK


def village_origin() -> tuple[float, float]:
    """Footpoint origin so the 44×44 diamond plus forest rim fits on the canvas."""
    origin_x = (GRID_SIZE + FOREST_TILES) * (TILE_WIDTH / 2)
    origin_y = FOREST_TILES * TILE_HEIGHT + SPRITE_TOP_PAD
    return origin_x, origin_y


def village_canvas_size() -> tuple[int, int]:
    width = int((GRID_SIZE + 2 * FOREST_TILES) * TILE_WIDTH)
    height = int((GRID_SIZE + 2 * FOREST_TILES) * TILE_HEIGHT + SPRITE_TOP_PAD)
    return width, height


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def shift_hue(rgb: tuple[int, int, int], degrees: float) -> tuple[int, int, int]:
    r, g, b = (c / 255.0 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (_clamp_byte(r * 255), _clamp_byte(g * 255), _clamp_byte(b * 255))


def adjust_brightness(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return (
        _clamp_byte(rgb[0] * factor),
        _clamp_byte(rgb[1] * factor),
        _clamp_byte(rgb[2] * factor),
    )


def jitter_rgb(
    rgb: tuple[int, int, int],
    amount: int,
    rng: random.Random,
) -> tuple[int, int, int]:
    if amount <= 0:
        return rgb
    return (
        _clamp_byte(rgb[0] + rng.randint(-amount, amount)),
        _clamp_byte(rgb[1] + rng.randint(-amount, amount)),
        _clamp_byte(rgb[2] + rng.randint(-amount, amount)),
    )


def randomize_village_palette(
    rng: random.Random,
    *,
    hue_shift_deg: float = 8.0,
    color_jitter: int = 14,
    brightness_jitter: float = 0.10,
    base: VillagePalette | None = None,
) -> VillagePalette:
    """Hue / brightness / channel jitter applied to grass (not building sprites)."""
    palette = base or VillagePalette()
    hue = rng.uniform(-hue_shift_deg, hue_shift_deg) if hue_shift_deg > 0 else 0.0
    bright = 1.0 + rng.uniform(-brightness_jitter, brightness_jitter)

    def _one(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        return jitter_rgb(adjust_brightness(shift_hue(rgb, hue), bright), color_jitter, rng)

    return VillagePalette(
        grass_light=_one(palette.grass_light),
        grass_dark=_one(palette.grass_dark),
        forest=_one(palette.forest),
        grid=_one(palette.grid),
        tree_canopy=_one(palette.tree_canopy),
        tree_canopy_dark=_one(palette.tree_canopy_dark),
        tree_trunk=_one(palette.tree_trunk),
    )


def village_diamond_vertices(origin_x: float, origin_y: float) -> list[tuple[float, float]]:
    """Screen-space corners of the playable 44×44 diamond (tile extents)."""
    last = GRID_SIZE - 1
    top = _tile_to_screen(0, 0, origin_x=origin_x, origin_y=origin_y)
    right = _tile_to_screen(last, 0, origin_x=origin_x, origin_y=origin_y)
    bottom = _tile_to_screen(last, last, origin_x=origin_x, origin_y=origin_y)
    left = _tile_to_screen(0, last, origin_x=origin_x, origin_y=origin_y)
    return [
        (top[0], top[1] - TILE_HEIGHT / 2),
        (right[0] + TILE_WIDTH / 2, right[1]),
        (bottom[0], bottom[1] + TILE_HEIGHT / 2),
        (left[0] - TILE_WIDTH / 2, left[1]),
    ]


def _grid_vertex(i: int, j: int, *, origin_x: float, origin_y: float) -> tuple[int, int]:
    sx, sy = _tile_to_screen(i, j, origin_x=origin_x, origin_y=origin_y)
    return int(round(sx)), int(round(sy - TILE_HEIGHT / 2))


def _tile_diamond(x: int, y: int, *, origin_x: float, origin_y: float) -> list[tuple[int, int]]:
    sx, sy = _tile_to_screen(x, y, origin_x=origin_x, origin_y=origin_y)
    return [
        (int(round(sx)), int(round(sy - TILE_HEIGHT / 2))),
        (int(round(sx + TILE_WIDTH / 2)), int(round(sy))),
        (int(round(sx)), int(round(sy + TILE_HEIGHT / 2))),
        (int(round(sx - TILE_WIDTH / 2)), int(round(sy))),
    ]


def _draw_tree(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    scale: float,
    palette: VillagePalette,
    rng: random.Random,
) -> None:
    """Simple pine-ish ellipses — original shapes, not game assets."""
    canopy_w = 9.0 * scale + rng.uniform(-1.5, 1.5)
    canopy_h = 14.0 * scale + rng.uniform(-2.0, 2.0)
    cx, cy = int(round(x)), int(round(y))
    trunk_w = max(2, int(round(2.2 * scale)))
    trunk_h = max(4, int(round(6.0 * scale)))
    draw.ellipse(
        (cx - trunk_w, cy - 2, cx + trunk_w, cy + trunk_h),
        fill=palette.tree_trunk,
    )
    # Two stacked canopies for a cheap conifer silhouette.
    draw.ellipse(
        (
            cx - int(canopy_w),
            cy - int(canopy_h * 1.15),
            cx + int(canopy_w),
            cy + int(canopy_h * 0.15),
        ),
        fill=palette.tree_canopy,
    )
    draw.ellipse(
        (
            cx - int(canopy_w * 0.7),
            cy - int(canopy_h * 1.55),
            cx + int(canopy_w * 0.65),
            cy - int(canopy_h * 0.25),
        ),
        fill=palette.tree_canopy_dark,
    )


def _draw_forest_ring(
    draw: ImageDraw.ImageDraw,
    *,
    origin_x: float,
    origin_y: float,
    palette: VillagePalette,
    rng: random.Random,
) -> None:
    step = 2
    for y in range(0, GRID_SIZE, step):
        k = 2 + rng.randint(0, FOREST_TILES - 3)
        sx, sy = _tile_to_screen(-k, y, origin_x=origin_x, origin_y=origin_y)
        _draw_tree(draw, sx, sy, rng.uniform(0.85, 1.45), palette, rng)
        k = 2 + rng.randint(0, FOREST_TILES - 3)
        sx, sy = _tile_to_screen(GRID_SIZE - 1 + k, y, origin_x=origin_x, origin_y=origin_y)
        _draw_tree(draw, sx, sy, rng.uniform(0.85, 1.45), palette, rng)
    for x in range(0, GRID_SIZE, step):
        k = 2 + rng.randint(0, FOREST_TILES - 3)
        sx, sy = _tile_to_screen(x, -k, origin_x=origin_x, origin_y=origin_y)
        _draw_tree(draw, sx, sy, rng.uniform(0.9, 1.5), palette, rng)
        k = 2 + rng.randint(0, FOREST_TILES - 3)
        sx, sy = _tile_to_screen(x, GRID_SIZE - 1 + k, origin_x=origin_x, origin_y=origin_y)
        _draw_tree(draw, sx, sy, rng.uniform(0.85, 1.4), palette, rng)
    # Extra clumps near the four diamond tips.
    for gx, gy in ((-3, -3), (GRID_SIZE + 2, -3), (-3, GRID_SIZE + 2), (GRID_SIZE + 2, GRID_SIZE + 2)):
        sx, sy = _tile_to_screen(gx, gy, origin_x=origin_x, origin_y=origin_y)
        _draw_tree(draw, sx, sy, rng.uniform(1.1, 1.7), palette, rng)


def _grass_noise_layer(size: tuple[int, int], rng: random.Random) -> Image.Image:
    """Low-res luminance noise, upscaled — organic grass mottling without numpy."""
    width, height = size
    nw, nh = max(8, width // 3), max(8, height // 3)
    small = Image.frombytes("L", (nw, nh), rng.randbytes(nw * nh))
    noise = small.resize(size, Image.Resampling.BILINEAR)
    # Keep the overlay green-tinted and low-alpha so it does not grey out the grass.
    r = noise.point(lambda p: 35 + p // 5)
    g = noise.point(lambda p: 65 + p // 3)
    b = noise.point(lambda p: 28 + p // 7)
    a = noise.point(lambda p: 26 + p // 12)
    return Image.merge("RGBA", (r, g, b, a))


def paint_village_background(
    canvas: Image.Image,
    *,
    origin_x: float,
    origin_y: float,
    rng: random.Random,
    palette: VillagePalette | None = None,
    draw_trees: bool = True,
) -> None:
    """Paint forest + playable diamond onto ``canvas`` (RGBA, in-place) before sprites."""
    pal = palette or VillagePalette()
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, canvas.size[0], canvas.size[1]), fill=(*pal.forest, 255))

    diamond = [(int(round(x)), int(round(y))) for x, y in village_diamond_vertices(origin_x, origin_y)]
    draw.polygon(diamond, fill=(*pal.grass_dark, 255))

    for x in range(GRID_SIZE):
        for y in range(GRID_SIZE):
            color = pal.grass_light if (x + y) % 2 == 0 else pal.grass_dark
            draw.polygon(_tile_diamond(x, y, origin_x=origin_x, origin_y=origin_y), fill=(*color, 255))

    canvas.alpha_composite(_grass_noise_layer(canvas.size, rng))

    grid_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid_layer)
    line = (*pal.grid, 48)
    for i in range(GRID_SIZE + 1):
        a = _grid_vertex(i, 0, origin_x=origin_x, origin_y=origin_y)
        b = _grid_vertex(i, GRID_SIZE, origin_x=origin_x, origin_y=origin_y)
        grid_draw.line([a, b], fill=line, width=1)
        c = _grid_vertex(0, i, origin_x=origin_x, origin_y=origin_y)
        d = _grid_vertex(GRID_SIZE, i, origin_x=origin_x, origin_y=origin_y)
        grid_draw.line([c, d], fill=line, width=1)
    canvas.alpha_composite(grid_layer)

    if draw_trees:
        _draw_forest_ring(draw, origin_x=origin_x, origin_y=origin_y, palette=pal, rng=rng)
