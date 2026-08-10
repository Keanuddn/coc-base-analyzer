"""Domain randomization for synthetic training renders (Phase 1c)."""

from __future__ import annotations

import random
from dataclasses import dataclass

from PIL import Image, ImageEnhance


@dataclass(slots=True)
class DomainRandomizationConfig:
    """Stochastic augmentations applied during render."""

    brightness_jitter: float = 0.12
    contrast_jitter: float = 0.12
    position_jitter_px: float = 3.0
    background_color_jitter: int = 18
    seed: int | None = None


def _jitter_channel(value: int, amount: int, rng: random.Random) -> int:
    return max(0, min(255, value + rng.randint(-amount, amount)))


def randomize_background(
    base_rgb: tuple[int, int, int],
    *,
    jitter: int,
    rng: random.Random,
) -> tuple[int, int, int]:
    if jitter <= 0:
        return base_rgb
    return (
        _jitter_channel(base_rgb[0], jitter, rng),
        _jitter_channel(base_rgb[1], jitter, rng),
        _jitter_channel(base_rgb[2], jitter, rng),
    )


def jitter_position(
    x: float,
    y: float,
    *,
    max_px: float,
    rng: random.Random,
) -> tuple[float, float]:
    if max_px <= 0:
        return x, y
    return (
        x + rng.uniform(-max_px, max_px),
        y + rng.uniform(-max_px, max_px),
    )


def apply_domain_randomization(
    image: Image.Image,
    *,
    config: DomainRandomizationConfig | None = None,
    rng: random.Random | None = None,
) -> Image.Image:
    """Apply lighting jitter to a composited RGBA image (alpha preserved)."""
    cfg = config or DomainRandomizationConfig()
    local_rng = rng or random.Random(cfg.seed)

    if cfg.brightness_jitter <= 0 and cfg.contrast_jitter <= 0:
        return image

    rgb = image.convert("RGB")
    alpha = image.getchannel("A") if image.mode == "RGBA" else None

    if cfg.brightness_jitter > 0:
        factor = 1.0 + local_rng.uniform(-cfg.brightness_jitter, cfg.brightness_jitter)
        rgb = ImageEnhance.Brightness(rgb).enhance(factor)

    if cfg.contrast_jitter > 0:
        factor = 1.0 + local_rng.uniform(-cfg.contrast_jitter, cfg.contrast_jitter)
        rgb = ImageEnhance.Contrast(rgb).enhance(factor)

    if alpha is not None:
        out = rgb.convert("RGBA")
        out.putalpha(alpha)
        return out
    return rgb
