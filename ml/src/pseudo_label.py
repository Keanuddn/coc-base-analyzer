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
from PIL import Image, ImageDraw, ImageFont

from model_utils import (
    ML_ROOT,
    REPO_ROOT,
    deprecated_class_indices,
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
HALL_NAMES = {"th13", "th14", "th15", "th16", "th17", "th18"}
V6_WEIGHTS = ML_ROOT / "runs" / "coc_yolo_v6" / "weights" / "best.pt"
V5_WEIGHTS = ML_ROOT / "runs" / "coc_yolo_v5" / "weights" / "best.pt"
NEW_TH17_TH18_QUEUE = [
    DEFAULT_REGRESSION_DIR / "th18" / "th18_vinsmoke_sanji.png",
    DEFAULT_REGRESSION_DIR / "th18" / "th18_lukas.png",
    DEFAULT_REGRESSION_DIR / "th18" / "th18_aggressor.png",
    DEFAULT_REGRESSION_DIR / "th17" / "th17_img_7307.png",
    DEFAULT_REGRESSION_DIR / "th17" / "th17_img_7306.png",
]


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


def declared_th_from_path(image_path: Path) -> str | None:
    folder = image_path.parent.name.lower()
    return folder if folder in HALL_NAMES else None


def _xyxy_to_yolo_line(
    cls_id: int,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: int,
    height: int,
) -> str:
    cx = min(max(((x1 + x2) / 2) / width, 0.0), 1.0)
    cy = min(max(((y1 + y2) / 2) / height, 0.0), 1.0)
    w = min(max((x2 - x1) / width, 0.0), 1.0)
    h = min(max((y2 - y1) / height, 0.0), 1.0)
    return f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def remap_hall_and_filter_lines(
    detections: list[tuple[int, float, float, float, float, float]],
    names: list[str],
    width: int,
    height: int,
    *,
    declared_th: str | None,
    include_deprecated: bool,
) -> list[str]:
    """Keep one hall box remapped to the folder TH; drop pads; drop eagle on TH17/18."""
    deprecated = set() if include_deprecated else deprecated_class_indices()
    name_to_id = {name: idx for idx, name in enumerate(names)}
    hall_ids = {name_to_id[n] for n in HALL_NAMES if n in name_to_id}
    target_hall = name_to_id.get(declared_th) if declared_th else None
    eagle_id = name_to_id.get("eagle")
    drop_eagle = declared_th in {"th17", "th18"} and eagle_id is not None

    kept: list[tuple[int, float, float, float, float]] = []
    halls: list[tuple[int, float, float, float, float, float]] = []
    for cls_id, x1, y1, x2, y2, conf in detections:
        if cls_id in deprecated:
            continue
        if drop_eagle and cls_id == eagle_id:
            continue
        if cls_id in hall_ids:
            halls.append((cls_id, x1, y1, x2, y2, conf))
            continue
        kept.append((cls_id, x1, y1, x2, y2))

    if halls:
        _, x1, y1, x2, y2, _conf = max(halls, key=lambda row: row[5])
        cls_id = target_hall if target_hall is not None else halls[0][0]
        kept.append((cls_id, x1, y1, x2, y2))

    return [_xyxy_to_yolo_line(cls_id, x1, y1, x2, y2, width, height) for cls_id, x1, y1, x2, y2 in kept]


def save_yolo_overlay(image_path: Path, lines: list[str], names: list[str], overlay_path: Path) -> None:
    """Draw the saved (remapped) labels, not the raw detector overlay."""
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as src:
        img = src.convert("RGB")
    draw = ImageDraw.Draw(img)
    width, height = img.size
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    except OSError:
        font = ImageFont.load_default()
    for line in lines:
        parts = line.split()
        cls_id = int(parts[0])
        cx, cy, w, h = map(float, parts[1:5])
        x1 = (cx - w / 2) * width
        y1 = (cy - h / 2) * height
        x2 = (cx + w / 2) * width
        y2 = (cy + h / 2) * height
        color = "#22d3ee"
        draw.rectangle([x1, y1, x2, y2], outline=color, width=1)
        name = names[cls_id] if 0 <= cls_id < len(names) else str(cls_id)
        draw.text((x1 + 2, max(y1 - 14, 0)), name, fill=color, font=font)
    img.save(overlay_path, quality=90)


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


def write_finetune_labels(
    images: list[Path],
    labels_dir: Path,
    *,
    weights: Path,
    conf: float,
    iou: float,
    include_deprecated: bool,
    overlay_dir: Path | None,
) -> dict:
    """Pseudo-label with a fine-tuned Ultralytics checkpoint; remap hall from folder name."""
    from ultralytics import YOLO

    names = model_class_names()
    model = YOLO(str(weights))
    summary: dict = {"model": str(weights), "conf": conf, "images": []}

    for image_path in images:
        with Image.open(image_path) as img:
            width, height = img.size
        results = model.predict(
            source=str(image_path),
            conf=conf,
            iou=iou,
            max_det=1000,
            verbose=False,
        )
        detections: list[tuple[int, float, float, float, float, float]] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(
                    (
                        int(box.cls.item()),
                        float(x1),
                        float(y1),
                        float(x2),
                        float(y2),
                        float(box.conf.item()),
                    )
                )
        declared = declared_th_from_path(image_path)
        hall_ids = {idx for idx, name in enumerate(names) if name in HALL_NAMES}
        if declared and not any(det[0] in hall_ids for det in detections):
            hall_results = model.predict(
                source=str(image_path),
                conf=min(conf, 0.08),
                iou=iou,
                max_det=1000,
                verbose=False,
            )
            for result in hall_results:
                boxes = result.boxes
                if boxes is None:
                    continue
                for box in boxes:
                    cls_id = int(box.cls.item())
                    if cls_id not in hall_ids:
                        continue
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    detections.append(
                        (cls_id, float(x1), float(y1), float(x2), float(y2), float(box.conf.item()))
                    )
        lines = remap_hall_and_filter_lines(
            detections,
            names,
            width,
            height,
            declared_th=declared,
            include_deprecated=include_deprecated,
        )
        rel = relative_to_regression(image_path, DEFAULT_REGRESSION_DIR)
        label_path = labels_dir / rel.with_suffix(".txt")
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        overlay_path = None
        if overlay_dir is not None:
            overlay_path = overlay_dir / f"{image_path.stem}.jpg"
            save_yolo_overlay(image_path, lines, names, overlay_path)

        counts: dict[str, int] = {}
        for line in lines:
            name = names[int(line.split()[0])]
            counts[name] = counts.get(name, 0) + 1
        entry = {
            "image": str(rel),
            "label_file": str(label_path.relative_to(DEFAULT_REGRESSION_DIR)),
            "declared_th": declared,
            "boxes": len(lines),
            "counts": counts,
            "overlay": str(overlay_path) if overlay_path else None,
        }
        summary["images"].append(entry)
        logging.info(
            "%s → %d boxes declared=%s hall_saved=%s",
            rel,
            len(lines),
            declared,
            [n for n in counts if n in HALL_NAMES],
        )

    return summary


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
        description="Pseudo-label regression screenshots (keremberke YOLOv5 or a fine-tune)."
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
    parser.add_argument(
        "--queue-new-th",
        action="store_true",
        help="Only the five new TH17/TH18 screenshots; use fine-tune weights and remap hall class from folder",
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default=None,
        help="Fine-tuned Ultralytics .pt (default with --queue-new-th: v6 then v5)",
    )
    parser.add_argument(
        "--overlay-dir",
        type=Path,
        default=None,
        help="Write small-font detection overlays (default with --queue-new-th: ml/runs/auto_label/overlays)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    cfg = load_train_config(args.config)
    pl_cfg = cfg.get("pseudo_label", {})
    conf = args.conf if args.conf is not None else pl_cfg.get("conf", DEFAULT_CONF)
    iou = args.iou if args.iou is not None else pl_cfg.get("iou", 0.45)
    imgsz = args.imgsz if args.imgsz is not None else pl_cfg.get("imgsz", 640)
    labels_dir = args.labels_dir or (args.regression_dir / "labels")

    if args.queue_new_th:
        weights = args.weights
        if weights is None:
            weights = V6_WEIGHTS if V6_WEIGHTS.is_file() else V5_WEIGHTS
        overlay_dir = args.overlay_dir or (ML_ROOT / "runs" / "auto_label" / "overlays")
        overlay_dir.mkdir(parents=True, exist_ok=True)
        if args.conf is None:
            conf = 0.25
        print(
            "\n⚠️  Auto-labels from the fine-tune. Hall class is taken from the folder "
            "(th17/th18), not the detector. Spot-check overlays before training.\n"
        )
        summary = write_finetune_labels(
            [p for p in NEW_TH17_TH18_QUEUE if p.is_file()],
            labels_dir,
            weights=weights,
            conf=conf,
            iou=iou,
            include_deprecated=args.include_deprecated,
            overlay_dir=overlay_dir,
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

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
