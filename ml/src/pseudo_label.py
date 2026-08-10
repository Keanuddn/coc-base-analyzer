#!/usr/bin/env python3
"""Generate pseudo-labels for regression screenshots using keremberke YOLOv5.

IMPORTANT: Pseudo-labels are noisy — especially on TH14+ bases where the baseline
model lacks classes (Monolith, Spell Tower) and TH-level-specific skins. Every
pseudo-label MUST be manually reviewed before treating them as ground truth.

Deprecated hero-pad classes (kingpad, queenpad, rcpad, wardenpad) are filtered
out by default — they no longer exist in current CoC bases and produce junk on
TH15/16 screenshots.

Output layout:
  ml/tests/regression_set/labels/<relative_path>.txt   — YOLO format sidecars
  ml/tests/regression_set/labels/_pseudo_label_metadata.json — provenance + flags
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PIL import Image

from model_utils import (
    ML_ROOT,
    REPO_ROOT,
    deprecated_class_names,
    filter_deprecated_yolo_lines,
    model_class_names,
    load_keremberke_yolov5,
    yolov5_predictions_to_yolo_lines,
)

DEFAULT_REGRESSION_DIR = ML_ROOT / "tests" / "regression_set"
DEFAULT_LABELS_DIR = DEFAULT_REGRESSION_DIR / "labels"
DEFAULT_CONFIG = ML_ROOT / "configs" / "train_config.yaml"
DEFAULT_CONF = 0.35
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def load_train_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def find_regression_images(regression_dir: Path, *, include_extras: bool = True) -> list[Path]:
    images: list[Path] = []
    for path in sorted(regression_dir.rglob("*")):
        if not include_extras and "_extras" in path.parts:
            continue
        if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
            images.append(path)
    return images


def relative_to_regression(image_path: Path, regression_dir: Path) -> Path:
    return image_path.relative_to(regression_dir)


def pseudo_label_image(
    model,
    image_path: Path,
    class_names: list[str],
    imgsz: int,
    *,
    include_deprecated: bool = False,
) -> tuple[list[str], int, int]:
    with Image.open(image_path) as img:
        width, height = img.size
    results = model(str(image_path), size=imgsz)
    predictions = results.pred[0]
    raw_lines = yolov5_predictions_to_yolo_lines(predictions, class_names, width, height)
    lines, removed = filter_deprecated_yolo_lines(raw_lines, include_deprecated=include_deprecated)
    return lines, len(raw_lines), removed


def write_pseudo_labels(
    regression_dir: Path,
    labels_dir: Path,
    *,
    conf: float,
    iou: float,
    imgsz: int,
    include_extras: bool,
    include_deprecated: bool,
    dry_run: bool,
) -> dict:
    class_names = model_class_names()
    model = load_keremberke_yolov5(conf=conf, iou=iou)

    images = find_regression_images(regression_dir, include_extras=include_extras)
    metadata: dict = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "model": "keremberke/yolov5m-clash-of-clans",
        "conf": conf,
        "iou": iou,
        "imgsz": imgsz,
        "include_deprecated": include_deprecated,
        "filtered_deprecated_classes": [] if include_deprecated else deprecated_class_names(),
        "manual_review_required": True,
        "disclaimer": (
            "These labels are model-generated guesses. Expect false positives on "
            "TH14+ buildings and missed detections for Monolith, Spell Tower, and "
            "new TH skins. Deprecated hero-pad classes are excluded by default. "
            "Do NOT use without human review."
        ),
        "labels": {},
    }

    total_boxes = 0
    total_raw_boxes = 0
    total_deprecated_removed = 0
    for image_path in images:
        rel = relative_to_regression(image_path, regression_dir)
        label_rel = rel.with_suffix(".txt")
        label_path = labels_dir / label_rel
        lines, raw_count, removed = pseudo_label_image(
            model, image_path, class_names, imgsz, include_deprecated=include_deprecated
        )
        total_boxes += len(lines)
        total_raw_boxes += raw_count
        total_deprecated_removed += removed

        metadata["labels"][str(rel)] = {
            "pseudo_label": True,
            "label_file": str(label_path.relative_to(regression_dir)),
            "detection_count": len(lines),
            "raw_detection_count": raw_count,
            "deprecated_removed": removed,
            "source_image": str(rel),
        }

        if dry_run:
            logging.info("[dry-run] %s → %d boxes (%d raw, %d deprecated removed)", rel, len(lines), raw_count, removed)
            continue

        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        logging.info(
            "Wrote %s (%d boxes, %d deprecated removed)",
            label_path.relative_to(REPO_ROOT),
            len(lines),
            removed,
        )

    if not dry_run:
        labels_dir.mkdir(parents=True, exist_ok=True)
        meta_path = labels_dir / "_pseudo_label_metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        logging.info("Metadata: %s", meta_path.relative_to(REPO_ROOT))

    return {
        "images": len(images),
        "total_boxes": total_boxes,
        "total_raw_boxes": total_raw_boxes,
        "deprecated_removed": total_deprecated_removed,
        "metadata": metadata,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pseudo-label regression screenshots with keremberke YOLOv5."
    )
    parser.add_argument(
        "--regression-dir",
        type=Path,
        default=DEFAULT_REGRESSION_DIR,
        help="Root of regression screenshot tree",
    )
    parser.add_argument(
        "--labels-dir",
        type=Path,
        default=None,
        help="Output labels root (default: <regression-dir>/labels/)",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--conf", type=float, default=None, help=f"Confidence threshold (default: {DEFAULT_CONF})")
    parser.add_argument("--iou", type=float, default=None)
    parser.add_argument("--imgsz", type=int, default=None)
    parser.add_argument("--no-extras", action="store_true", help="Skip _extras/ folder")
    parser.add_argument(
        "--include-deprecated",
        action="store_true",
        help="Keep deprecated hero-pad classes (kingpad, queenpad, rcpad, wardenpad)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    cfg = load_train_config(args.config)
    pl_cfg = cfg.get("pseudo_label", {})
    conf = args.conf if args.conf is not None else pl_cfg.get("conf", DEFAULT_CONF)
    iou = args.iou if args.iou is not None else pl_cfg.get("iou", 0.45)
    imgsz = args.imgsz if args.imgsz is not None else pl_cfg.get("imgsz", 640)
    labels_dir = args.labels_dir or (args.regression_dir / "labels")

    filter_note = ""
    if not args.include_deprecated:
        deprecated = ", ".join(deprecated_class_names())
        filter_note = f"    Filtering deprecated classes: {deprecated}.\n"

    print(
        "\n⚠️  Pseudo-labels require MANUAL REVIEW before training on them as ground truth.\n"
        "    Expect false positives and missed TH14+ buildings.\n"
        f"{filter_note}"
    )

    result = write_pseudo_labels(
        args.regression_dir,
        labels_dir,
        conf=conf,
        iou=iou,
        imgsz=imgsz,
        include_extras=not args.no_extras,
        include_deprecated=args.include_deprecated,
        dry_run=args.dry_run,
    )
    print(
        json.dumps(
            {
                "images": result["images"],
                "total_boxes": result["total_boxes"],
                "total_raw_boxes": result["total_raw_boxes"],
                "deprecated_removed": result["deprecated_removed"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
