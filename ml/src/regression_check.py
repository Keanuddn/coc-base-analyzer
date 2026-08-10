#!/usr/bin/env python3
"""Compare fine-tuned model vs keremberke baseline on the regression set."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from infer import find_latest_weights, infer_keremberke, infer_ultralytics, load_train_config
from model_utils import ML_ROOT, REPO_ROOT
from pseudo_label import find_regression_images

DEFAULT_REGRESSION_DIR = ML_ROOT / "tests" / "regression_set"
DEFAULT_CONFIG = ML_ROOT / "configs" / "train_config.yaml"
DEFAULT_OUTPUT = ML_ROOT / "tests" / "regression_check_report.json"


def summarize_detections(result: dict) -> dict:
    classes = [b["class"] for b in result.get("buildings", [])]
    confidences = [b["confidence"] for b in result.get("buildings", [])]
    return {
        "detection_count": result.get("detection_count", 0),
        "class_counts": dict(Counter(classes)),
        "mean_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "min_confidence": round(min(confidences), 4) if confidences else 0.0,
        "max_confidence": round(max(confidences), 4) if confidences else 0.0,
    }


def compare_models(
    regression_dir: Path,
    *,
    weights: Path | None,
    config_path: Path,
    include_extras: bool,
) -> dict:
    cfg = load_train_config(config_path)
    inf = cfg.get("inference", {})
    conf = inf.get("conf", 0.25)
    iou = inf.get("iou", 0.45)
    max_det = inf.get("max_det", 1000)
    imgsz = cfg.get("training", {}).get("imgsz", 640)

    fine_weights = weights or find_latest_weights(REPO_ROOT / "ml" / "runs")
    has_fine_tuned = fine_weights is not None and fine_weights.is_file()

    images = find_regression_images(regression_dir, include_extras=include_extras)
    per_image: list[dict] = []

    for image_path in images:
        baseline = infer_keremberke(image_path, conf=conf, iou=iou, imgsz=imgsz)
        entry: dict = {
            "image": str(image_path.relative_to(REPO_ROOT)),
            "baseline": summarize_detections(baseline),
        }
        if has_fine_tuned:
            fine = infer_ultralytics(fine_weights, image_path, conf=conf, iou=iou, max_det=max_det)
            entry["fine_tuned"] = summarize_detections(fine)
            entry["fine_tuned_weights"] = str(fine_weights.relative_to(REPO_ROOT))
            b_count = entry["baseline"]["detection_count"]
            f_count = entry["fine_tuned"]["detection_count"]
            entry["delta_detections"] = f_count - b_count
        per_image.append(entry)

    totals_baseline = sum(e["baseline"]["detection_count"] for e in per_image)
    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "regression_dir": str(regression_dir.relative_to(REPO_ROOT)),
        "images_tested": len(per_image),
        "baseline_model": "keremberke/yolov5m-clash-of-clans",
        "fine_tuned_weights": str(fine_weights.relative_to(REPO_ROOT)) if has_fine_tuned else None,
        "totals": {
            "baseline_detections": totals_baseline,
            "fine_tuned_detections": sum(e.get("fine_tuned", {}).get("detection_count", 0) for e in per_image)
            if has_fine_tuned
            else None,
        },
        "per_image": per_image,
        "notes": (
            "Detection count deltas are indicative only — pseudo-labels and baseline "
            "both have high FP/FN rates on TH14+. Manual review required."
        ),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regression check: baseline vs fine-tuned model.")
    parser.add_argument("--regression-dir", type=Path, default=DEFAULT_REGRESSION_DIR)
    parser.add_argument("--weights", type=Path, default=None, help="Fine-tuned weights (default: latest ml/runs/)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--no-extras", action="store_true")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline-only", action="store_true", help="Skip fine-tuned comparison")
    args = parser.parse_args(argv)

    report = compare_models(
        args.regression_dir,
        weights=None if args.baseline_only else args.weights,
        config_path=args.config,
        include_extras=not args.no_extras,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(
        {
            "images_tested": report["images_tested"],
            "baseline_detections": report["totals"]["baseline_detections"],
            "fine_tuned_detections": report["totals"]["fine_tuned_detections"],
            "report": str(args.output.relative_to(REPO_ROOT)),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
