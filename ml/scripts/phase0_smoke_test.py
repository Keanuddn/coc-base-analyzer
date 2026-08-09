#!/usr/bin/env python3
"""Phase 0 smoke test: load keremberke/yolov5m-clash-of-clans and run inference."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ML_ROOT = PROJECT_ROOT / "ml"
REGRESSION_SET = ML_ROOT / "tests" / "regression_set"
NOTEBOOKS_DIR = ML_ROOT / "notebooks"
RESULTS_CSV = NOTEBOOKS_DIR / "phase0_results.csv"

MODEL_ID = "keremberke/yolov5m-clash-of-clans"
CLASS_NAMES = [
    "ad", "airsweeper", "bombtower", "canon", "clancastle", "eagle", "inferno",
    "kingpad", "mortar", "queenpad", "rcpad", "scattershot", "th13", "wardenpad",
    "wizztower", "xbow",
]


def find_regression_images() -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    images: list[Path] = []
    if REGRESSION_SET.exists():
        for p in sorted(REGRESSION_SET.rglob("*")):
            if p.suffix.lower() in exts and p.is_file():
                images.append(p)
    return images


def infer_th_level(path: Path) -> str:
    for part in path.parts:
        if part.startswith("th") and part[2:].isdigit():
            return part
    return "unknown"


def load_model():
    import yolov5

    model = yolov5.load(MODEL_ID)
    model.conf = 0.25
    model.iou = 0.45
    model.max_det = 1000
    return model


def run_inference(model, image_path: Path) -> dict:
    results = model(str(image_path), size=640)
    predictions = results.pred[0]
    if predictions is None or len(predictions) == 0:
        return {"count": 0, "classes": [], "scores": []}

    categories = predictions[:, 5].int().tolist()
    scores = predictions[:, 4].tolist()
    class_names = [CLASS_NAMES[int(c)] if int(c) < len(CLASS_NAMES) else str(int(c)) for c in categories]
    return {"count": len(predictions), "classes": class_names, "scores": [round(s, 3) for s in scores]}


def download_hf_sample() -> Path | None:
    try:
        from datasets import load_dataset

        ds = load_dataset("keremberke/clash-of-clans-object-detection", name="full", split="test")
        sample_dir = NOTEBOOKS_DIR / "hf_sample_images"
        sample_dir.mkdir(parents=True, exist_ok=True)
        out = sample_dir / "hf_test_000.jpg"
        if not out.exists():
            img = ds[0]["image"]
            img.save(out)
        return out
    except Exception as exc:
        print(f"HF sample download failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    NOTEBOOKS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading model: {MODEL_ID}")
    try:
        model = load_model()
        print("Model loaded successfully.")
    except Exception as exc:
        print(f"Model load FAILED: {exc}", file=sys.stderr)
        return 1

    images = find_regression_images()
    smoke_only = False
    if not images:
        print("No regression set images found.")
        sample = download_hf_sample()
        if sample:
            images = [sample]
            smoke_only = True
            print(f"Using HF dataset sample: {sample}")
        else:
            import yolov5
            fallback = Path(yolov5.__file__).parent / "data" / "images" / "zidane.jpg"
            if fallback.exists():
                images = [fallback]
                smoke_only = True
                print(f"Using yolov5 fallback image: {fallback}")

    rows = []
    for img_path in images:
        det = run_inference(model, img_path)
        try:
            rel = str(img_path.relative_to(PROJECT_ROOT))
        except ValueError:
            rel = str(img_path)
        rows.append({
            "image_path": rel,
            "th_level": infer_th_level(img_path),
            "model_detections": det["count"],
            "detected_classes": json.dumps(det["classes"]),
            "detection_scores": json.dumps(det["scores"]),
            "correct": "",
            "false_positives": "",
            "false_negatives": "",
            "notes": "smoke_test_only" if smoke_only else "",
            "evaluated_at": "",
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
        })
        preview = det["classes"][:5]
        suffix = "..." if len(det["classes"]) > 5 else ""
        print(f"  {img_path.name}: {det['count']} detections — {preview}{suffix}")

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_CSV, index=False)
    print(f"\nResults saved to: {RESULTS_CSV}")
    print(f"Images tested: {len(images)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
