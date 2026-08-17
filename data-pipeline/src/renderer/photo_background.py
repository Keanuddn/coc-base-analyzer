"""Align user empty-village screenshots to the 44×44 isometric playable diamond.

ClashKing has no scenery tiles. These photos are the real CoC camera: a light
grass / tan / stone checkerboard diamond with forest, ruins, or lava around it.
The renderer warps that diamond onto ``village_diamond_vertices`` so sprites
sit on the village grid, not on trees or lava.
"""

from __future__ import annotations

import colorsys
import functools
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageEnhance, ImageFilter, ImageStat

from renderer.village_background import village_canvas_size, village_diamond_vertices, village_origin

logger = logging.getLogger(__name__)

BACKGROUNDS_DIR = Path(__file__).resolve().parent / "backgrounds"

# Fractions of screenshot width/height if automatic edge-finding fails.
# Measured on the 1024×665 empty-village captures (inner checkered diamond).
_FALLBACK_LEFT = 0.145
_FALLBACK_RIGHT = 0.862
_FALLBACK_TOP = 0.158
_FALLBACK_BOTTOM = 0.875

_MIN_DIAMOND_WIDTH_FRAC = 0.42
_MIN_DIAMOND_HEIGHT_FRAC = 0.38

Quad = Sequence[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class PlayableDiamond:
    top: tuple[float, float]
    right: tuple[float, float]
    bottom: tuple[float, float]
    left: tuple[float, float]

    def as_quad(self) -> tuple[tuple[float, float], ...]:
        return (self.top, self.right, self.bottom, self.left)


def list_scenery_backgrounds(directory: Path | None = None) -> list[Path]:
    """PNG scenery files only (skips README and other non-images)."""
    root = directory or BACKGROUNDS_DIR
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*.png") if path.is_file())


def pick_scenery_background(
    rng: random.Random,
    *,
    directory: Path | None = None,
    exclude: frozenset[str] = frozenset(),
) -> Path | None:
    paths = [p for p in list_scenery_backgrounds(directory) if p.name not in exclude]
    if not paths:
        return None
    return rng.choice(paths)


def scenery_path_by_name(name: str, directory: Path | None = None) -> Path | None:
    root = directory or BACKGROUNDS_DIR
    path = root / name
    return path if path.is_file() else None


def _luminance(rgb: tuple[float, ...]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _rgb_to_hsv(rgb: tuple[float, ...]) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)


def _window_mean(image: Image.Image, x: int, y: int, radius: int) -> tuple[float, float, float]:
    x0 = max(0, x - radius)
    y0 = max(0, y - radius)
    x1 = min(image.width, x + radius + 1)
    y1 = min(image.height, y + radius + 1)
    stats = ImageStat.Stat(image.crop((x0, y0, x1, y1)))
    mean = stats.mean
    return (mean[0], mean[1], mean[2])


def _classify_playable(base_rgb: tuple[float, float, float]) -> str:
    hue, sat, _val = _rgb_to_hsv(base_rgb)
    if sat < 0.18:
        return "ruins"
    if 0.08 < hue < 0.18 and sat > 0.30:
        return "war"
    return "grass"


def _luminance_drop_for_mode(mode: str) -> float:
    # War tan has a stronger checker; grass/ruins stop before the dark rim.
    if mode == "war":
        return 32.0
    if mode == "ruins":
        return 22.0
    return 20.0


def _smooth(values: list[float], radius: int = 9) -> list[float]:
    out: list[float] = []
    n = len(values)
    for i in range(n):
        sl = values[max(0, i - radius) : i + radius + 1]
        out.append(sum(sl) / len(sl))
    return out


def _first_drop(profile: list[float], start: int, step: int, threshold: float) -> int:
    i = start
    last = start
    n = len(profile)
    while 0 <= i < n:
        if profile[i] < threshold:
            return last
        last = i
        i += step
    return last


def calibrated_diamond(width: int, height: int) -> PlayableDiamond:
    """Fixed mapping for similarly framed empty-village screenshots."""
    cx = width / 2.0
    cy = height / 2.0
    left = width * _FALLBACK_LEFT
    right = width * _FALLBACK_RIGHT
    top = height * _FALLBACK_TOP
    bottom = height * _FALLBACK_BOTTOM
    return PlayableDiamond(
        top=(cx, top),
        right=(right, cy),
        bottom=(cx, bottom),
        left=(left, cy),
    )


def detect_playable_diamond(image: Image.Image) -> PlayableDiamond:
    """Find the inner light grass / tan / stone diamond (not the forest/lava rim)."""
    rgb = image.convert("RGB")
    blurred = rgb.filter(ImageFilter.BoxBlur(3))
    width, height = blurred.size
    cx, cy = width // 2, height // 2
    base = _window_mean(blurred, cx, cy, 16)
    mode = _classify_playable(base)
    drop = _luminance_drop_for_mode(mode)
    threshold = _luminance(base) - drop

    row = [_luminance(blurred.getpixel((x, cy))) for x in range(width)]
    col = [_luminance(blurred.getpixel((cx, y))) for y in range(height)]
    row_s = _smooth(row)
    col_s = _smooth(col)

    left_x = _first_drop(row_s, cx, -1, threshold)
    right_x = _first_drop(row_s, cx, 1, threshold)
    top_y = _first_drop(col_s, cy, -1, threshold)
    bottom_y = _first_drop(col_s, cy, 1, threshold)

    diamond_w = right_x - left_x
    diamond_h = bottom_y - top_y
    if diamond_w < _MIN_DIAMOND_WIDTH_FRAC * width or diamond_h < _MIN_DIAMOND_HEIGHT_FRAC * height:
        logger.warning(
            "Playable diamond detection failed (%dx%d in %dx%d, mode=%s); using calibrated mapping",
            diamond_w,
            diamond_h,
            width,
            height,
            mode,
        )
        return calibrated_diamond(width, height)

    return PlayableDiamond(
        top=(float(cx), float(top_y)),
        right=(float(right_x), float(cy)),
        bottom=(float(cx), float(bottom_y)),
        left=(float(left_x), float(cy)),
    )


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (8×8 perspective system)."""
    n = len(matrix)
    aug = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda r: abs(aug[r][i]))
        aug[i], aug[pivot] = aug[pivot], aug[i]
        diag = aug[i][i]
        if abs(diag) < 1e-12:
            raise ValueError("Singular perspective system")
        inv = 1.0 / diag
        for c in range(i, n + 1):
            aug[i][c] *= inv
        for r in range(n):
            if r == i:
                continue
            factor = aug[r][i]
            if factor == 0.0:
                continue
            for c in range(i, n + 1):
                aug[r][c] -= factor * aug[i][c]
    return [aug[i][n] for i in range(n)]


def perspective_coeffs(
    source: Quad,
    destination: Quad,
) -> tuple[float, ...]:
    """PIL PERSPECTIVE coefficients mapping destination pixels → source pixels."""
    matrix: list[list[float]] = []
    vector: list[float] = []
    for (u, v), (x, y) in zip(source, destination, strict=True):
        matrix.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        vector.append(u)
        matrix.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        vector.append(v)
    return tuple(_solve_linear_system(matrix, vector))


def _edge_fill(image: Image.Image) -> tuple[int, int, int]:
    """Dark rim color so warped photos do not flash magenta at canvas corners."""
    w, h = image.size
    samples = [
        image.getpixel((2, 2)),
        image.getpixel((w - 3, 2)),
        image.getpixel((2, h - 3)),
        image.getpixel((w - 3, h - 3)),
        image.getpixel((w // 2, 2)),
        image.getpixel((2, h // 2)),
    ]
    rgb = [p[:3] for p in samples]
    return (
        int(sum(p[0] for p in rgb) / len(rgb)),
        int(sum(p[1] for p in rgb) / len(rgb)),
        int(sum(p[2] for p in rgb) / len(rgb)),
    )


def jitter_photo_brightness(
    image: Image.Image,
    rng: random.Random,
    *,
    amount: float = 0.06,
) -> Image.Image:
    """Slight exposure jitter on the scenery only (not building sprites)."""
    if amount <= 0:
        return image
    factor = 1.0 + rng.uniform(-amount, amount)
    if abs(factor - 1.0) < 0.005:
        return image
    rgb = ImageEnhance.Brightness(image.convert("RGB")).enhance(factor)
    if image.mode == "RGBA":
        out = rgb.convert("RGBA")
        out.putalpha(image.getchannel("A"))
        return out
    return rgb.convert(image.mode)


def align_scenery_to_village_grid(
    photo: Image.Image,
    *,
    origin_x: float | None = None,
    origin_y: float | None = None,
    canvas_size: tuple[int, int] | None = None,
) -> Image.Image:
    """Perspective-warp ``photo`` so its playable diamond matches the 44×44 grid."""
    if origin_x is None or origin_y is None:
        origin_x, origin_y = village_origin()
    size = canvas_size or village_canvas_size()
    src = detect_playable_diamond(photo).as_quad()
    dst = tuple((float(x), float(y)) for x, y in village_diamond_vertices(origin_x, origin_y))
    rgb = photo.convert("RGB")
    fill = _edge_fill(rgb)
    coeffs = perspective_coeffs(src, dst)
    warped = rgb.transform(
        size,
        Image.Transform.PERSPECTIVE,
        coeffs,
        resample=Image.Resampling.BICUBIC,
        fillcolor=fill,
    )
    return warped.convert("RGBA")


@functools.lru_cache(maxsize=16)
def _aligned_scenery_cached(
    path: str,
    origin_x: float,
    origin_y: float,
    canvas_w: int,
    canvas_h: int,
) -> Image.Image:
    with Image.open(path) as photo:
        aligned = align_scenery_to_village_grid(
            photo,
            origin_x=origin_x,
            origin_y=origin_y,
            canvas_size=(canvas_w, canvas_h),
        )
    return aligned.copy()


def load_aligned_scenery(
    path: Path,
    *,
    origin_x: float | None = None,
    origin_y: float | None = None,
    canvas_size: tuple[int, int] | None = None,
    rng: random.Random | None = None,
    brightness_jitter: float = 0.06,
) -> Image.Image:
    if origin_x is None or origin_y is None:
        origin_x, origin_y = village_origin()
    width, height = canvas_size or village_canvas_size()
    aligned = _aligned_scenery_cached(str(path.resolve()), origin_x, origin_y, width, height).copy()
    if rng is not None and brightness_jitter > 0:
        aligned = jitter_photo_brightness(aligned, rng, amount=brightness_jitter)
    return aligned


def paint_photo_background(
    canvas: Image.Image,
    photo_path: Path,
    *,
    origin_x: float,
    origin_y: float,
    rng: random.Random,
    brightness_jitter: float = 0.06,
) -> None:
    """Fill ``canvas`` with an aligned scenery photo (in-place)."""
    aligned = load_aligned_scenery(
        photo_path,
        origin_x=origin_x,
        origin_y=origin_y,
        canvas_size=canvas.size,
        rng=rng,
        brightness_jitter=brightness_jitter,
    )
    if aligned.size != canvas.size:
        aligned = aligned.resize(canvas.size, Image.Resampling.BICUBIC)
    canvas.alpha_composite(aligned.convert("RGBA"))
