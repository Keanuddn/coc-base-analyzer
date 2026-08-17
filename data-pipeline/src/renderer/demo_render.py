#!/usr/bin/env python3
"""CLI demo for Phase 1c isometric renderer — no decoded links required."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from link_decoder.schema import BuildingPlacement
from renderer.domain_randomization import DomainRandomizationConfig
from renderer.isometric_renderer import IsometricRenderer

# Hardcoded TH15-style sample layout (center of 44×44 grid).
DEMO_PLACEMENTS: list[BuildingPlacement] = [
    BuildingPlacement("town_hall", level=15, x=22, y=22),
    BuildingPlacement("canon", level=20, x=18, y=20),
    BuildingPlacement("mortar", level=15, x=26, y=20),
    BuildingPlacement("eagle", level=7, x=22, y=16),
    BuildingPlacement("xbow", level=10, x=16, y=24),
    BuildingPlacement("inferno", level=9, x=28, y=24),
]

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[2] / "datasets" / "processed" / "demo" / "sample_base.png"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a demo CoC base from test placements.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output PNG path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for domain randomization")
    parser.add_argument(
        "--no-randomization",
        action="store_true",
        help="Disable domain randomization (deterministic render)",
    )
    parser.add_argument(
        "--flat-background",
        action="store_true",
        help="Legacy solid green fill instead of procedural village grass",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not IsometricRenderer.sprites_available():
        logging.error(
            "ClashKing sprites not found. Run: "
            "data-pipeline/src/renderer/sprites/download_clashking_sprites.sh"
        )
        return 1

    sprite_count = IsometricRenderer.count_sprites()
    logging.info("Found %d sprite WebP files", sprite_count)

    dr_cfg = None
    if not args.no_randomization:
        dr_cfg = DomainRandomizationConfig(seed=args.seed)

    renderer = IsometricRenderer(use_placeholders=True, village_background=not args.flat_background)
    result = renderer.render_to_files(
        DEMO_PLACEMENTS,
        args.output,
        domain_randomization=dr_cfg,
        seed=args.seed,
    )

    logging.info(
        "Rendered %d buildings (%d skipped) → %s",
        result.rendered_count,
        result.skipped_count,
        result.output_path,
    )
    if result.label_path:
        logging.info("YOLO labels → %s (%d boxes)", result.label_path, len(result.labels))
    for warning in result.warnings:
        logging.warning(warning)

    print(f"OK: {result.output_path} ({result.image.size[0]}×{result.image.size[1]} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
