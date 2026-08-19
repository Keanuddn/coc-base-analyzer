#!/usr/bin/env python3
"""Run inference on a single CoC base screenshot → JSON detections."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from model_utils import ML_ROOT, REPO_ROOT, model_class_names, load_keremberke_yolov5

DEFAULT_CONFIG = ML_ROOT / "configs" / "train_config.yaml"


def load_train_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def find_latest_weights(runs_dir: Path) -> Path | None:
    candidates = sorted(runs_dir.glob("*/weights/best.pt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def infer_keremberke(image_path: Path, *, conf: float, iou: float, imgsz: int) -> dict:
    class_names = model_class_names()
    model = load_keremberke_yolov5(conf=conf, iou=iou)
    results = model(str(image_path), size=imgsz)
    predictions = results.pred[0]

    buildings: list[dict] = []
    if predictions is not None and len(predictions) > 0:
        for row in predictions:
            x1, y1, x2, y2, score, cls_id = row.tolist()
            idx = int(cls_id)
            buildings.append(
                {
                    "class": class_names[idx] if idx < len(class_names) else str(idx),
                    "class_id": idx,
                    "confidence": round(float(score), 4),
                    "bbox_xyxy": [round(float(v), 2) for v in (x1, y1, x2, y2)],
                }
            )

    return {
        "image": str(image_path),
        "model": "keremberke/yolov5m-clash-of-clans",
        "detection_count": len(buildings),
        "buildings": buildings,
    }


def infer_ultralytics(weights: Path, image_path: Path, *, conf: float, iou: float, max_det: int) -> dict:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    names = model.names or {i: n for i, n in enumerate(model_class_names())}
    results = model.predict(
        source=str(image_path),
        conf=conf,
        iou=iou,
        max_det=max_det,
        verbose=False,
    )
    buildings: list[dict] = []
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        for box in boxes:
            cls_id = int(box.cls.item())
            score = float(box.conf.item())
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            buildings.append(
                {
                    "class": names.get(cls_id, str(cls_id)),
                    "class_id": cls_id,
                    "confidence": round(score, 4),
                    "bbox_xyxy": [round(v, 2) for v in (x1, y1, x2, y2)],
                }
            )

    return {
        "image": str(image_path),
        "model": str(weights),
        "detection_count": len(buildings),
        "buildings": buildings,
    }


def run_inference(
    image_path: Path,
    *,
    weights: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
    use_baseline: bool = False,
) -> dict:
    cfg = load_train_config(config_path)
    inf = cfg.get("inference", {})
    conf = inf.get("conf", 0.25)
    iou = inf.get("iou", 0.45)
    max_det = inf.get("max_det", 1000)
    imgsz = cfg.get("training", {}).get("imgsz", 640)

    if use_baseline or weights is None:
        resolved = find_latest_weights(REPO_ROOT / "ml" / "runs")
        if use_baseline or resolved is None:
            return infer_keremberke(image_path, conf=conf, iou=iou, imgsz=imgsz)
        weights = resolved

    if not weights.is_file():
        raise FileNotFoundError(f"Weights not found: {weights}")
    return infer_ultralytics(weights, image_path, conf=conf, iou=iou, max_det=max_det)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Infer buildings on a CoC screenshot.")
    parser.add_argument("image", type=Path, help="Path to screenshot PNG/JPG")
    parser.add_argument("--weights", type=Path, default=None, help="Fine-tuned .pt (default: latest in ml/runs/)")
    parser.add_argument("--baseline", action="store_true", help="Force keremberke YOLOv5 baseline")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("-o", "--output", type=Path, default=None, help="Write JSON to file")
    args = parser.parse_args(argv)

    if not args.image.is_file():
        print(f"Image not found: {args.image}", file=sys.stderr)
        return 1

    try:
        result = run_inference(
            args.image,
            weights=args.weights,
            config_path=args.config,
            use_baseline=args.baseline,
        )
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
