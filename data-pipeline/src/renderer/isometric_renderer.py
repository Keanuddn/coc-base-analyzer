"""PIL isometric compositor for CoC synthetic base renders (Phase 1c)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from PIL import Image, ImageDraw

from link_decoder.schema import BuildingPlacement
from renderer.domain_randomization import (
    DomainRandomizationConfig,
    apply_domain_randomization,
    jitter_position,
    randomize_background,
)
from renderer.photo_background import paint_photo_background, pick_scenery_background
from renderer.village_background import (
    paint_village_background,
    randomize_village_palette,
    village_canvas_size,
    village_origin,
)

logger = logging.getLogger(__name__)

# Standard Home Village grid (layout editor).
GRID_SIZE = 44
TILE_WIDTH = 44
TILE_HEIGHT = 22

# Official CoC editor footprints (tiles) — collision only, not combat stats.
COC_TILE_FOOTPRINTS: dict[str, int] = {
    "town_hall": 4,
    "clancastle": 3,
    "eagle": 4,
    "inferno": 2,
    "canon": 3,
    "mortar": 3,
    "wizztower": 3,
    "ad": 3,
    "airsweeper": 2,
    "xbow": 3,
    "bombtower": 3,
    "scattershot": 3,
    "ricochet_cannon": 3,
    "super_wizard_tower": 4,  # larger than a regular wizard tower
    "archertower": 3,
    "archer_tower": 3,
    "multi-archer_tower": 3,
    "firespitter": 3,
    "spelltower": 3,
    "spell_tower": 3,
    "monolith": 3,
    "tesla": 2,
    "hidden_tesla": 2,
    "builderhut": 2,
    "builder's_hut": 2,
    "multi-gear_tower": 3,
    "revenge_tower": 3,
    "wall": 1,
}

# Occupancy AABB: max(CoC tiles, ceil(max ClashKing sprite width / TILE_WIDTH)).
# Wide auras (max cannon, eagle, inferno) would otherwise stack visually.
TILE_FOOTPRINTS: dict[str, int] = {
    "town_hall": 6,
    "clancastle": 4,
    "eagle": 6,
    "inferno": 4,
    "canon": 5,
    "mortar": 3,
    "wizztower": 3,
    "ad": 3,
    "airsweeper": 3,
    "xbow": 4,
    "bombtower": 3,
    "scattershot": 4,
    "ricochet_cannon": 4,
    "super_wizard_tower": 4,
    "archertower": 3,
    "archer_tower": 3,
    "multi-archer_tower": 4,  # bulkier merged sprite (132×175) vs archer 3×3
    "firespitter": 4,  # ClashKing max 165px wide → ceil(165/44)=4
    "spelltower": 3,
    "spell_tower": 3,
    "monolith": 4,  # ClashKing max 150px wide → ceil(150/44)=4
    "tesla": 3,
    "hidden_tesla": 3,
    "builderhut": 4,  # weaponized hut max 161px
    "builder's_hut": 4,
    "multi-gear_tower": 4,
    "revenge_tower": 4,
    "wall": 1,  # 1×1 editor tiles; adjacent walls may overlap each other on purpose
}

# Extra tiles reserved around each defense so sprite bodies (not just tile
# squares) stay apart on photo scenery. Walls stay 1×1 and skip this pad.
OCCUPANCY_PAD_TILES = 2
# Screen-space gap between visual footprint AABBs (photo compositing).
VISUAL_OVERLAP_GAP_PX = 8
# 1×1 types that must not inflate from sprite pixel size (walls form a grid).
UNIT_TILE_TYPES: frozenset[str] = frozenset({"wall"})

# Extra pixels above the isometric footprint used when sprite height is unknown.
SPRITE_NORTH_PAD_PX = 140

# YOLOv5 label order from docs/ARCHITECTURE.md (keremberke model).
YOLO_CLASS_NAMES: tuple[str, ...] = (
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

SPRITES_DIR = Path(__file__).resolve().parent / "sprites"
CLASHKING_HOME_VILLAGE = SPRITES_DIR / "clashking" / "home-village"
BUILDING_TYPE_MAP_PATH = SPRITES_DIR / "building_type_map.yaml"

DEFAULT_BACKGROUND = (72, 120, 64)


@dataclass(slots=True)
class YoloLabel:
    class_name: str
    class_id: int
    cx: float
    cy: float
    w: float
    h: float


@dataclass(slots=True)
class RenderResult:
    image: Image.Image
    labels: list[YoloLabel]
    output_path: Path | None = None
    label_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    rendered_count: int = 0
    skipped_count: int = 0
    background_path: Path | None = None


@dataclass(slots=True)
class _PlacedSprite:
    sprite: Image.Image
    screen_x: float
    screen_y: float
    depth: int
    yolo_class: str
    building_type: str


def _load_building_type_map(path: Path = BUILDING_TYPE_MAP_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _slug_for_building_type(building_type: str, type_map: Mapping[str, Any]) -> str | None:
    aliases: Mapping[str, str] = type_map.get("aliases") or {}
    identity: Sequence[str] = type_map.get("identity") or []
    town_hall: Mapping[str, str] = type_map.get("town_hall") or {}

    if building_type in aliases:
        return aliases[building_type]
    if building_type in identity:
        return building_type
    if building_type in {"town_hall", "th13", town_hall.get("yolo_class", "th13")}:
        return town_hall.get("sprite_slug", "town_hall")
    if building_type in {"monolith", "spelltower", "spell_tower", "wall"}:
        if building_type == "monolith":
            return "monolith"
        if building_type == "wall":
            return "wall"
        return "spell_tower"
    return None


def _yolo_class_for_building_type(building_type: str, type_map: Mapping[str, Any]) -> str:
    overrides: Mapping[str, str] = type_map.get("yolo_label_overrides") or {}
    if building_type in overrides:
        return str(overrides[building_type])

    aliases: Mapping[str, str] = type_map.get("aliases") or {}
    town_hall: Mapping[str, str] = type_map.get("town_hall") or {}

    if building_type in aliases:
        return building_type
    if building_type in (town_hall.get("sprite_slug"), "town_hall"):
        return town_hall.get("yolo_class", "th13")
    if building_type == "th13":
        return "th13"
    if building_type == "spell_tower":
        return "spelltower"
    # Reverse lookup: clashking slug → yolo alias
    for alias, slug in aliases.items():
        if slug == building_type:
            return alias
    return building_type


def _yolo_class_id(class_name: str) -> int | None:
    try:
        return YOLO_CLASS_NAMES.index(class_name)
    except ValueError:
        return None


def tile_to_screen(x: float, y: float, *, origin_x: float, origin_y: float) -> tuple[float, float]:
    """Map grid tile (x, y) to screen coordinates (tile center)."""
    screen_x = origin_x + (x - y) * (TILE_WIDTH / 2)
    screen_y = origin_y + (x + y) * (TILE_HEIGHT / 2)
    return screen_x, screen_y


def screen_to_tile(sx: float, sy: float, *, origin_x: float, origin_y: float) -> tuple[float, float]:
    """Inverse of ``tile_to_screen`` — fractional tile coordinates."""
    u = (sx - origin_x) / (TILE_WIDTH / 2)
    v = (sy - origin_y) / (TILE_HEIGHT / 2)
    return (u + v) / 2.0, (v - u) / 2.0


def footprint_size(building_type: str) -> int:
    """Occupancy AABB in tiles (conservative ClashKing width, else CoC editor size)."""
    if building_type in TILE_FOOTPRINTS:
        return TILE_FOOTPRINTS[building_type]
    return COC_TILE_FOOTPRINTS.get(building_type, 1)


def occupancy_tiles(
    building_type: str,
    sprite_width: int | None = None,
    sprite_height: int | None = None,
) -> int:
    """Tiles reserved for collision on the 44×44 diamond.

    max(CoC editor size, conservative table, ceil(sprite_width / TILE_WIDTH),
    ceil(0.5 * sprite_height / TILE_HEIGHT)) plus ``OCCUPANCY_PAD_TILES``.
    Walls stay 1×1 so segments can sit on adjacent tiles.
    """
    if building_type in UNIT_TILE_TYPES:
        return 1
    base = COC_TILE_FOOTPRINTS.get(building_type, 1)
    conservative = TILE_FOOTPRINTS.get(building_type, base)
    size = max(base, conservative)
    if sprite_width is not None and sprite_width > 0:
        size = max(size, math.ceil(sprite_width / TILE_WIDTH))
    if sprite_height is not None and sprite_height > 0:
        # Lower half of the sprite is the building body that must not sit on neighbors.
        size = max(size, math.ceil((sprite_height * 0.55) / TILE_HEIGHT))
    return size + OCCUPANCY_PAD_TILES


def occupied_cells(x: int, y: int, size: int) -> set[tuple[int, int]]:
    return {(x + dx, y + dy) for dx in range(size) for dy in range(size)}


def occupancy_aabb(
    x: int,
    y: int,
    size: int,
    sprite_w: int,
    sprite_h: int,
    *,
    origin_x: float,
    origin_y: float,
) -> tuple[float, float, float, float]:
    """Screen AABB of the visual footprint (occupancy diamond + sprite body).

    Roofs may still overlap slightly; the box covers the isometric diamond plus
    a fraction of extra sprite height so neighboring feet do not sit on the art.
    """
    foot_x, foot_y = footprint_anchor(x, y, size, origin_x=origin_x, origin_y=origin_y)
    diamond_half_w = size * TILE_WIDTH / 2.0
    diamond_h = size * TILE_HEIGHT
    half_w = max(diamond_half_w, sprite_w * 0.42)
    extra = max(0.0, float(sprite_h) - diamond_h)
    body_h = diamond_h + extra * 0.45
    return (foot_x - half_w, foot_y - body_h, foot_x + half_w, foot_y)


def aabbs_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    *,
    gap: float = VISUAL_OVERLAP_GAP_PX,
) -> bool:
    """True if two (left, top, right, bottom) boxes overlap after ``gap`` padding."""
    return not (
        a[2] + gap <= b[0]
        or b[2] + gap <= a[0]
        or a[3] + gap <= b[1]
        or b[3] + gap <= a[1]
    )


def footprint_anchor(
    x: int,
    y: int,
    size: int,
    *,
    origin_x: float,
    origin_y: float,
) -> tuple[float, float]:
    """Bottom-center of the size×size isometric diamond (south vertex).

    Sprites are pasted with their image bottom at this footpoint so the art
    sits on the occupied tiles instead of the northwest corner tile.
    """
    south_x = x + size - 1
    south_y = y + size - 1
    sx, sy = tile_to_screen(south_x, south_y, origin_x=origin_x, origin_y=origin_y)
    return sx, sy + TILE_HEIGHT / 2


def estimated_sprite_size(size: int, sprite_w: int | None = None, sprite_h: int | None = None) -> tuple[int, int]:
    width = sprite_w if sprite_w is not None else size * TILE_WIDTH
    height = sprite_h if sprite_h is not None else size * TILE_HEIGHT + SPRITE_NORTH_PAD_PX
    return width, height


def placement_in_playable_grid(x: int, y: int, size: int) -> bool:
    """True if the occupancy square sits on the 44×44 checkerboard."""
    return x >= 0 and y >= 0 and x + size <= GRID_SIZE and y + size <= GRID_SIZE


def sprite_stays_on_playable(
    x: int,
    y: int,
    size: int,
    *,
    sprite_w: int,
    sprite_h: int,
    origin_x: float | None = None,
    origin_y: float | None = None,
    canvas_size: tuple[int, int] | None = None,
) -> bool:
    """Keep the building base on the grass diamond and the sprite on-canvas.

    Occupied tiles must already sit on the 44×44 checkerboard. Tall roofs may
    stick up; they are pushed south so they do not sit on the forest rim or
    hang off the canvas.
    """
    if not placement_in_playable_grid(x, y, size):
        return False
    if origin_x is None or origin_y is None:
        origin_x, origin_y = village_origin()
    foot_x, foot_y = footprint_anchor(x, y, size, origin_x=origin_x, origin_y=origin_y)
    width, height = estimated_sprite_size(size, sprite_w, sprite_h)
    left = foot_x - width / 2
    right = foot_x + width / 2
    top = foot_y - height
    cw, ch = canvas_size or village_canvas_size()
    if left < 0 or top < 0 or right > cw or foot_y > ch:
        return False
    extra_north = max(0, math.ceil((height - size * TILE_HEIGHT) / TILE_HEIGHT))
    # Stick-up goes toward decreasing x and y (screen-up). Guard both diamond edges,
    # not only the north tip (x+y); otherwise y=0 placements hang into the forest.
    margin = math.ceil(extra_north / 2.0) + 1
    if x < margin or y < margin:
        return False
    if x + size > GRID_SIZE - 1 or y + size > GRID_SIZE - 1:
        return False
    # Widest part of the isometric footprint (not the south/north tips).
    mid_y = foot_y - size * TILE_HEIGHT / 2.0
    diamond_lo = -0.5
    diamond_hi = GRID_SIZE - 0.5
    for px in (left, right):
        tx, ty = screen_to_tile(px, mid_y, origin_x=origin_x, origin_y=origin_y)
        if tx < diamond_lo or ty < diamond_lo or tx > diamond_hi or ty > diamond_hi:
            return False
    return True


def _normalize_placement(raw: BuildingPlacement | Mapping[str, Any]) -> BuildingPlacement:
    if isinstance(raw, BuildingPlacement):
        return raw
    return BuildingPlacement(
        building_type=str(raw["building_type"]),
        level=int(raw["level"]),
        x=int(raw["x"]),
        y=int(raw["y"]),
        rotation=int(raw.get("rotation", 0)),
    )


def _sprite_path(slug: str, level: int, sprites_root: Path | None = None) -> Path:
    root = sprites_root or CLASHKING_HOME_VILLAGE
    return root / slug / f"level_{level}.webp"


def list_sprite_levels(slug: str, sprites_root: Path | None = None) -> list[int]:
    """Return sorted 1-based levels that exist as ``level_{n}.webp`` on disk."""
    folder = (sprites_root or CLASHKING_HOME_VILLAGE) / slug
    if not folder.is_dir():
        return []
    levels: list[int] = []
    for path in folder.glob("level_*.webp"):
        suffix = path.stem.split("_", 1)[1]
        if suffix.isdigit():
            levels.append(int(suffix))
    return sorted(levels)


def _resolve_sprite_path(slug: str, level: int, sprites_root: Path | None = None) -> Path | None:
    direct = _sprite_path(slug, level, sprites_root)
    if direct.is_file():
        return direct
    levels = list_sprite_levels(slug, sprites_root)
    if not levels:
        return None
    capped = min(level, levels[-1])
    return _sprite_path(slug, capped, sprites_root)


def _make_placeholder(size: tuple[int, int] = (64, 64)) -> Image.Image:
    img = Image.new("RGBA", size, (255, 0, 255, 180))
    draw = ImageDraw.Draw(img)
    draw.rectangle((4, 4, size[0] - 5, size[1] - 5), outline=(0, 0, 0, 255), width=2)
    return img


def _paste_sprite(
    canvas: Image.Image,
    sprite: Image.Image,
    foot_x: float,
    foot_y: float,
) -> tuple[int, int, int, int]:
    """Paste sprite with footpoint at (foot_x, foot_y). Returns bbox in canvas coords."""
    if sprite.mode != "RGBA":
        sprite = sprite.convert("RGBA")
    w, h = sprite.size
    paste_x = int(round(foot_x - w / 2))
    paste_y = int(round(foot_y - h))
    canvas_w, canvas_h = canvas.size
    src_x = max(0, -paste_x)
    src_y = max(0, -paste_y)
    dst_x = max(0, paste_x)
    dst_y = max(0, paste_y)
    src_w = min(w - src_x, canvas_w - dst_x)
    src_h = min(h - src_y, canvas_h - dst_y)
    if src_w > 0 and src_h > 0:
        visible = sprite if (src_x, src_y, src_w, src_h) == (0, 0, w, h) else sprite.crop(
            (src_x, src_y, src_x + src_w, src_y + src_h)
        )
        canvas.alpha_composite(visible, dest=(dst_x, dst_y))
    return paste_x, paste_y, paste_x + w, paste_y + h


def _crop_from_bboxes(
    bboxes: Sequence[tuple[int, int, int, int]],
    canvas_size: tuple[int, int],
    *,
    pad: int,
) -> tuple[int, int, int, int]:
    """Axis-aligned crop around building boxes (not the opaque grass fill)."""
    if not bboxes:
        return (0, 0, canvas_size[0], canvas_size[1])
    x1 = min(b[0] for b in bboxes)
    y1 = min(b[1] for b in bboxes)
    x2 = max(b[2] for b in bboxes)
    y2 = max(b[3] for b in bboxes)
    return (
        max(0, x1 - pad),
        max(0, y1 - pad),
        min(canvas_size[0], x2 + pad),
        min(canvas_size[1], y2 + pad),
    )


class IsometricRenderer:
    """Composite ClashKing sprites onto a 44×44 isometric village grid."""

    def __init__(
        self,
        *,
        sprites_root: Path | None = None,
        type_map_path: Path = BUILDING_TYPE_MAP_PATH,
        background: tuple[int, int, int] = DEFAULT_BACKGROUND,
        use_placeholders: bool = True,
        village_background: bool = True,
        use_photo_backgrounds: bool = True,
        backgrounds_dir: Path | None = None,
    ) -> None:
        self.sprites_root = sprites_root or CLASHKING_HOME_VILLAGE
        self.type_map = _load_building_type_map(type_map_path)
        self.background = background
        self.use_placeholders = use_placeholders
        self.village_background = village_background
        self.use_photo_backgrounds = use_photo_backgrounds
        self.backgrounds_dir = backgrounds_dir

    @staticmethod
    def sprites_available(sprites_root: Path | None = None) -> bool:
        root = sprites_root or CLASHKING_HOME_VILLAGE
        return root.is_dir() and any(root.rglob("*.webp"))

    @staticmethod
    def count_sprites(sprites_root: Path | None = None) -> int:
        root = sprites_root or CLASHKING_HOME_VILLAGE
        if not root.is_dir():
            return 0
        return sum(1 for _ in root.rglob("*.webp"))

    def _resolve_photo_background(
        self,
        rng: Any,
        background_path: Path | None,
    ) -> Path | None:
        if not self.village_background or not self.use_photo_backgrounds:
            return None
        if background_path is not None:
            return background_path if background_path.is_file() else None
        return pick_scenery_background(rng, directory=self.backgrounds_dir)

    def _paint_background(
        self,
        canvas: Image.Image,
        *,
        origin_x: float,
        origin_y: float,
        rng: Any,
        dr_cfg: DomainRandomizationConfig,
        photo_path: Path | None,
    ) -> None:
        if photo_path is not None:
            paint_photo_background(
                canvas,
                photo_path,
                origin_x=origin_x,
                origin_y=origin_y,
                rng=rng,
                brightness_jitter=min(0.08, dr_cfg.background_brightness_jitter or 0.06),
            )
            return
        if not self.village_background:
            return
        palette = randomize_village_palette(
            rng,
            hue_shift_deg=dr_cfg.background_hue_shift,
            color_jitter=dr_cfg.background_color_jitter,
            brightness_jitter=dr_cfg.background_brightness_jitter,
        )
        paint_village_background(
            canvas,
            origin_x=origin_x,
            origin_y=origin_y,
            rng=rng,
            palette=palette,
        )

    def render(
        self,
        placements: Sequence[BuildingPlacement | Mapping[str, Any]],
        *,
        domain_randomization: DomainRandomizationConfig | None = None,
        seed: int | None = None,
        background_path: Path | None = None,
    ) -> RenderResult:
        import random

        rng = random.Random(seed if seed is not None else (domain_randomization.seed if domain_randomization else None))
        dr_cfg = domain_randomization or DomainRandomizationConfig(seed=seed)
        bg = randomize_background(
            self.background,
            jitter=dr_cfg.background_color_jitter,
            rng=rng,
        )
        photo_path = self._resolve_photo_background(rng, background_path)

        normalized = [_normalize_placement(p) for p in placements]
        if self.village_background:
            origin_x, origin_y = village_origin()
            temp_size = village_canvas_size()
        else:
            origin_x = GRID_SIZE * (TILE_WIDTH / 2)
            origin_y = TILE_HEIGHT * 2
            temp_size = (GRID_SIZE * TILE_WIDTH * 2, GRID_SIZE * TILE_HEIGHT * 2)

        placed: list[_PlacedSprite] = []
        warnings: list[str] = []
        skipped = 0

        for placement in normalized:
            slug = _slug_for_building_type(placement.building_type, self.type_map)
            if slug is None:
                msg = f"No sprite slug for building_type={placement.building_type!r}"
                logger.warning(msg)
                warnings.append(msg)
                skipped += 1
                continue

            sprite_path = _resolve_sprite_path(slug, placement.level)
            if sprite_path is None:
                msg = (
                    f"Missing sprite for {placement.building_type!r} "
                    f"(slug={slug}, level={placement.level})"
                )
                logger.warning(msg)
                warnings.append(msg)
                if not self.use_placeholders:
                    skipped += 1
                    continue
                sprite = _make_placeholder()
            else:
                sprite = Image.open(sprite_path)

            if placement.rotation % 360 != 0:
                sprite = sprite.rotate(-placement.rotation, expand=True, resample=Image.Resampling.BICUBIC)

            size = occupancy_tiles(
                placement.building_type, sprite.size[0], sprite.size[1]
            )
            foot_x, foot_y = footprint_anchor(
                placement.x,
                placement.y,
                size,
                origin_x=origin_x,
                origin_y=origin_y,
            )
            foot_x, foot_y = jitter_position(
                foot_x,
                foot_y,
                max_px=dr_cfg.position_jitter_px,
                rng=rng,
            )

            yolo_class = _yolo_class_for_building_type(placement.building_type, self.type_map)
            placed.append(
                _PlacedSprite(
                    sprite=sprite,
                    screen_x=foot_x,
                    screen_y=foot_y,
                    depth=placement.x + placement.y + 2 * (size - 1),
                    yolo_class=yolo_class,
                    building_type=placement.building_type,
                )
            )

        if not placed:
            if self.village_background:
                canvas = Image.new("RGBA", temp_size, (0, 0, 0, 0))
                self._paint_background(
                    canvas,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    rng=rng,
                    dr_cfg=dr_cfg,
                    photo_path=photo_path,
                )
            else:
                canvas = Image.new("RGBA", (512, 512), (*bg, 255))
            result_img = apply_domain_randomization(canvas, config=dr_cfg, rng=rng)
            return RenderResult(
                image=result_img,
                labels=[],
                warnings=warnings,
                rendered_count=0,
                skipped_count=skipped,
                background_path=photo_path,
            )

        bboxes: list[tuple[int, int, int, int]] = []
        scratch = Image.new("RGBA", temp_size, (0, 0, 0, 0))
        if self.village_background:
            self._paint_background(
                scratch,
                origin_x=origin_x,
                origin_y=origin_y,
                rng=rng,
                dr_cfg=dr_cfg,
                photo_path=photo_path,
            )

        sorted_placed = sorted(placed, key=lambda p: p.depth)
        for item in sorted_placed:
            bbox = _paste_sprite(scratch, item.sprite, item.screen_x, item.screen_y)
            bboxes.append(bbox)

        if self.village_background:
            # Keep the full diamond + forest rim so buildings are judged in-bounds.
            crop = (0, 0, temp_size[0], temp_size[1])
            canvas = scratch
        else:
            pad = 24
            crop = _crop_from_bboxes(bboxes, temp_size, pad=pad)
            cropped = scratch.crop(crop)
            canvas = Image.new("RGBA", cropped.size, (*bg, 255))
            canvas.alpha_composite(cropped)

        img_w, img_h = canvas.size
        labels: list[YoloLabel] = []
        for item, bbox in zip(sorted_placed, bboxes, strict=False):
            x1, y1, x2, y2 = bbox
            x1 = max(0, min(img_w, x1 - crop[0]))
            y1 = max(0, min(img_h, y1 - crop[1]))
            x2 = max(0, min(img_w, x2 - crop[0]))
            y2 = max(0, min(img_h, y2 - crop[1]))
            if x2 <= x1 or y2 <= y1:
                continue
            class_id = _yolo_class_id(item.yolo_class)
            if class_id is None:
                unlabeled = {
                    str(name) for name in (self.type_map.get("yolo_unlabeled") or [])
                }
                if item.yolo_class in unlabeled or item.building_type in unlabeled:
                    continue
                warnings.append(f"No YOLO class id for {item.yolo_class!r} ({item.building_type})")
                continue
            cx = ((x1 + x2) / 2) / img_w
            cy = ((y1 + y2) / 2) / img_h
            w = (x2 - x1) / img_w
            h = (y2 - y1) / img_h
            labels.append(
                YoloLabel(
                    class_name=item.yolo_class,
                    class_id=class_id,
                    cx=cx,
                    cy=cy,
                    w=w,
                    h=h,
                )
            )

        result_img = apply_domain_randomization(canvas, config=dr_cfg, rng=rng)
        return RenderResult(
            image=result_img,
            labels=labels,
            warnings=warnings,
            rendered_count=len(placed),
            skipped_count=skipped,
            background_path=photo_path,
        )

    def render_to_files(
        self,
        placements: Sequence[BuildingPlacement | Mapping[str, Any]],
        output_png: Path,
        *,
        domain_randomization: DomainRandomizationConfig | None = None,
        seed: int | None = None,
        background_path: Path | None = None,
    ) -> RenderResult:
        result = self.render(
            placements,
            domain_randomization=domain_randomization,
            seed=seed,
            background_path=background_path,
        )
        output_png.parent.mkdir(parents=True, exist_ok=True)
        label_path = output_png.with_suffix(".txt")
        result.image.save(output_png, format="PNG")
        _write_yolo_labels(label_path, result.labels)
        result.output_path = output_png
        result.label_path = label_path
        return result


def _write_yolo_labels(path: Path, labels: Sequence[YoloLabel]) -> None:
    lines = [
        f"{label.class_id} {label.cx:.6f} {label.cy:.6f} {label.w:.6f} {label.h:.6f}"
        for label in labels
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
