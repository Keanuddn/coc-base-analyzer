#!/usr/bin/env python3
"""Run inference on a single CoC base screenshot → JSON detections."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from kb_buildings import attach_knowledge_base
from count_gate import attach_count_gate
from model_utils import ML_ROOT, REPO_ROOT, model_class_names, load_keremberke_yolov5
from th_gate import (
    attach_gate_metadata,
    apply_th_gate,
    load_th_gate_table,
    resolve_town_hall,
)

DEFAULT_CONFIG = ML_ROOT / "configs" / "train_config.yaml"
# Ultralytics cv2 Annotator sets fontScale = line_width / 3 and ignores font_size.
# On 2552×1356 screenshots that becomes ~68px labels that bury the village. PIL
# lets us keep boxes thin while drawing small text independently.
DEFAULT_OVERLAY_LINE_WIDTH = 1
DEFAULT_OVERLAY_FONT_SIZE = 13


def load_train_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def find_latest_weights(runs_dir: Path) -> Path | None:
    candidates = sorted(runs_dir.glob("*/weights/best.pt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def infer_keremberke(
    image_path: Path,
    *,
    conf: float,
    iou: float,
    imgsz: int,
    town_hall: int | None = None,
) -> dict:
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

    payload = {
        "image": str(image_path),
        "model": "keremberke/yolov5m-clash-of-clans",
        "detection_count": len(buildings),
        "buildings": buildings,
    }
    return _apply_th_gate(payload, cli_th=town_hall, class_names=class_names)


def save_detection_overlay(
    result,
    output_path: Path,
    *,
    line_width: int = DEFAULT_OVERLAY_LINE_WIDTH,
    font_size: int = DEFAULT_OVERLAY_FONT_SIZE,
) -> Path:
    """Write a YOLO plot with small labels so dense CoC bases stay readable."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.plot(
        conf=True,
        labels=True,
        boxes=True,
        line_width=line_width,
        font_size=font_size,
        pil=True,
        save=True,
        filename=str(output_path),
    )
    return output_path


def _names_dict(names) -> dict[int, str]:
    if isinstance(names, dict):
        return {int(k): str(v) for k, v in names.items()}
    return {i: str(n) for i, n in enumerate(names)}


def _extract_buildings(results, names: dict[int, str]) -> list[dict]:
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
    return buildings


def _sync_result_boxes(result, buildings: list[dict]) -> None:
    """Rewrite YOLO boxes so the overlay matches gated class names."""
    boxes = result.boxes
    if boxes is None:
        return
    import torch

    device = boxes.data.device
    dtype = boxes.data.dtype
    if not buildings:
        result.update(boxes=torch.zeros((0, 6), device=device, dtype=dtype))
        return
    rows = [
        [*b["bbox_xyxy"], float(b["confidence"]), int(b["class_id"])] for b in buildings
    ]
    result.update(boxes=torch.tensor(rows, device=device, dtype=dtype))


def _apply_th_gate(
    payload: dict,
    *,
    cli_th: int | None,
    class_names: list[str] | None = None,
    result=None,
) -> dict:
    table = load_th_gate_table(class_names=class_names)
    town_hall, source = resolve_town_hall(payload["buildings"], cli_th=cli_th)
    gate = apply_th_gate(
        payload["buildings"],
        town_hall=town_hall,
        town_hall_source=source,
        table=table,
    )
    if result is not None and gate.applied:
        _sync_result_boxes(result, gate.buildings)
    gated = attach_gate_metadata(payload, gate)
    return attach_count_gate(attach_knowledge_base(gated))


def infer_ultralytics(
    weights: Path,
    image_path: Path,
    *,
    conf: float,
    iou: float,
    max_det: int,
    overlay_path: Path | None = None,
    overlay_line_width: int = DEFAULT_OVERLAY_LINE_WIDTH,
    overlay_font_size: int = DEFAULT_OVERLAY_FONT_SIZE,
    town_hall: int | None = None,
) -> dict:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    class_names = model_class_names()
    names = _names_dict(model.names or class_names)
    results = model.predict(
        source=str(image_path),
        conf=conf,
        iou=iou,
        max_det=max_det,
        verbose=False,
    )
    buildings = _extract_buildings(results, names)
    payload = {
        "image": str(image_path),
        "model": str(weights),
        "detection_count": len(buildings),
        "buildings": buildings,
    }
    payload = _apply_th_gate(
        payload,
        cli_th=town_hall,
        class_names=class_names,
        result=results[0] if results else None,
    )

    if overlay_path is not None and results:
        save_detection_overlay(
            results[0],
            overlay_path,
            line_width=overlay_line_width,
            font_size=overlay_font_size,
        )

    return payload


def run_inference(
    image_path: Path,
    *,
    weights: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
    use_baseline: bool = False,
    overlay_path: Path | None = None,
    town_hall: int | None = None,
    conf: float | None = None,
    overlay_font_size: int | None = None,
) -> dict:
    cfg = load_train_config(config_path)
    inf = cfg.get("inference", {})
    conf_value = inf.get("conf", 0.25) if conf is None else conf
    iou = inf.get("iou", 0.45)
    max_det = inf.get("max_det", 1000)
    imgsz = cfg.get("training", {}).get("imgsz", 640)
    overlay_line_width = inf.get("overlay_line_width", DEFAULT_OVERLAY_LINE_WIDTH)
    font_size = inf.get("overlay_font_size", DEFAULT_OVERLAY_FONT_SIZE)
    if overlay_font_size is not None:
        font_size = overlay_font_size

    if use_baseline or weights is None:
        resolved = find_latest_weights(REPO_ROOT / "ml" / "runs")
        if use_baseline or resolved is None:
            return infer_keremberke(
                image_path,
                conf=conf_value,
                iou=iou,
                imgsz=imgsz,
                town_hall=town_hall,
            )
        weights = resolved

    if not weights.is_file():
        raise FileNotFoundError(f"Weights not found: {weights}")
    return infer_ultralytics(
        weights,
        image_path,
        conf=conf_value,
        iou=iou,
        max_det=max_det,
        overlay_path=overlay_path,
        overlay_line_width=overlay_line_width,
        overlay_font_size=font_size,
        town_hall=town_hall,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Infer buildings on a CoC screenshot.")
    parser.add_argument("image", type=Path, help="Path to screenshot PNG/JPG")
    parser.add_argument("--weights", type=Path, default=None, help="Fine-tuned .pt (default: latest in ml/runs/)")
    parser.add_argument("--baseline", action="store_true", help="Force keremberke YOLOv5 baseline")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--th", type=int, default=None, help="Town Hall override (e.g. 15). Gate skipped if TH unknown.")
    parser.add_argument("--conf", type=float, default=None, help="Confidence threshold (default: from config)")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Write JSON to file")
    parser.add_argument("--overlay", type=Path, default=None, help="Write annotated JPEG overlay")
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
            overlay_path=args.overlay,
            town_hall=args.th,
            conf=args.conf,
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
    if args.overlay:
        print(f"Wrote overlay {args.overlay}")
    summary = result.get("summary") or {}
    targeting = summary.get("defenses_targeting") or {}
    if targeting:
        print(
            "defenses targeting: "
            f"air={targeting.get('air', 0)} ground={targeting.get('ground', 0)} "
            f"both={targeting.get('both', 0)} unknown={targeting.get('unknown', 0)}"
        )
    gate = result.get("th_gate") or {}
    if gate:
        print(
            f"TH-gate TH={result.get('town_hall')} source={result.get('town_hall_source')} "
            f"applied={gate.get('applied')} remapped={gate.get('remapped', 0)} "
            f"dropped={gate.get('dropped', 0)}"
        )
        before = gate.get("class_counts_before") or {}
        after = gate.get("class_counts_after") or {}
        changed = sorted(k for k in set(before) | set(after) if before.get(k, 0) != after.get(k, 0))
        for name in changed:
            print(f"  {name}: {before.get(name, 0)} -> {after.get(name, 0)}")
    count_gate = result.get("count_gate") or {}
    over_max = count_gate.get("over_max") or []
    if over_max:
        print("count-gate over wiki max:")
        for row in over_max:
            merge = " (merge cap)" if row.get("merge_cap") else ""
            print(
                f"  {row['class']}: {row['detected']} > {row['wiki_max']} "
                f"(+{row['excess']}){merge}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
