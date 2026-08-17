"""PIL isometric compositor for CoC synthetic base renders (Phase 1c)."""

from __future__ import annotations

import logging
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
    if building_type in {"monolith", "spelltower", "spell_tower"}:
        return "monolith" if building_type == "monolith" else "spell_tower"
    return None


def _yolo_class_for_building_type(building_type: str, type_map: Mapping[str, Any]) -> str:
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


def tile_to_screen(x: int, y: int, *, origin_x: float, origin_y: float) -> tuple[float, float]:
    """Map grid tile (x, y) to screen coordinates (footpoint)."""
    screen_x = origin_x + (x - y) * (TILE_WIDTH / 2)
    screen_y = origin_y + (x + y) * (TILE_HEIGHT / 2)
    return screen_x, screen_y


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


def _sprite_path(slug: str, level: int) -> Path:
    return CLASHKING_HOME_VILLAGE / slug / f"level_{level}.webp"


def _resolve_sprite_path(slug: str, level: int) -> Path | None:
    direct = _sprite_path(slug, level)
    if direct.is_file():
        return direct
    folder = CLASHKING_HOME_VILLAGE / slug
    if not folder.is_dir():
        return None
    levels = sorted(
        int(p.stem.split("_", 1)[1])
        for p in folder.glob("level_*.webp")
        if p.stem.startswith("level_")
    )
    if not levels:
        return None
    capped = min(level, levels[-1])
    return _sprite_path(slug, capped)


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
    ) -> None:
        self.sprites_root = sprites_root or CLASHKING_HOME_VILLAGE
        self.type_map = _load_building_type_map(type_map_path)
        self.background = background
        self.use_placeholders = use_placeholders
        self.village_background = village_background

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

    def render(
        self,
        placements: Sequence[BuildingPlacement | Mapping[str, Any]],
        *,
        domain_randomization: DomainRandomizationConfig | None = None,
        seed: int | None = None,
    ) -> RenderResult:
        import random

        rng = random.Random(seed if seed is not None else (domain_randomization.seed if domain_randomization else None))
        dr_cfg = domain_randomization or DomainRandomizationConfig(seed=seed)
        bg = randomize_background(
            self.background,
            jitter=dr_cfg.background_color_jitter,
            rng=rng,
        )

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

            foot_x, foot_y = tile_to_screen(
                placement.x,
                placement.y,
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
                    depth=placement.x + placement.y,
                    yolo_class=yolo_class,
                    building_type=placement.building_type,
                )
            )

        if not placed:
            if self.village_background:
                canvas = Image.new("RGBA", temp_size, (0, 0, 0, 0))
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
            else:
                canvas = Image.new("RGBA", (512, 512), (*bg, 255))
            result_img = apply_domain_randomization(canvas, config=dr_cfg, rng=rng)
            return RenderResult(
                image=result_img,
                labels=[],
                warnings=warnings,
                rendered_count=0,
                skipped_count=skipped,
            )

        bboxes: list[tuple[int, int, int, int]] = []
        if self.village_background:
            scratch = Image.new("RGBA", temp_size, (0, 0, 0, 0))
            palette = randomize_village_palette(
                rng,
                hue_shift_deg=dr_cfg.background_hue_shift,
                color_jitter=dr_cfg.background_color_jitter,
                brightness_jitter=dr_cfg.background_brightness_jitter,
            )
            paint_village_background(
                scratch,
                origin_x=origin_x,
                origin_y=origin_y,
                rng=rng,
                palette=palette,
            )
        else:
            scratch = Image.new("RGBA", temp_size, (0, 0, 0, 0))

        sorted_placed = sorted(placed, key=lambda p: p.depth)
        for item in sorted_placed:
            bbox = _paste_sprite(scratch, item.sprite, item.screen_x, item.screen_y)
            bboxes.append(bbox)

        pad = 40 if self.village_background else 24
        crop = _crop_from_bboxes(bboxes, temp_size, pad=pad)
        cropped = scratch.crop(crop)
        if self.village_background:
            canvas = cropped
        else:
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
        )

    def render_to_files(
        self,
        placements: Sequence[BuildingPlacement | Mapping[str, Any]],
        output_png: Path,
        *,
        domain_randomization: DomainRandomizationConfig | None = None,
        seed: int | None = None,
    ) -> RenderResult:
        result = self.render(
            placements,
            domain_randomization=domain_randomization,
            seed=seed,
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
